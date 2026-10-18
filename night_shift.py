"""The night shift: every night the agents run the whole Find customers chain on their own.

Scout finds businesses on the owner's chosen beats (trade + suburb), Inspector checks their
websites, Designer matches each lead to a story mock-up, Writer drafts the next message,
Chaser lines up follow-ups and Caretaker drafts monthly-client work. It runs once a day after
2 am (Sydney time) inside the AgencyOS worker, or straight away when the Mac wakes later.
Everything lands in the morning queue for the owner's tap. Nothing is ever sent or published.
"""
import json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from flask import flash,redirect,render_template,request,session,url_for
from phase3_store import WorkflowError,stamp
from phase4_store import paused
from sales_store import log
import client_plans
import lead_engine
import playbook
import smart_writer

TZ=ZoneInfo('Australia/Sydney')
START_HOUR=2
BEATS_PER_NIGHT=2
CHECKS_PER_NIGHT=40
DRAFTS_PER_NIGHT=15
AGENTS=(
 ('scout','Scout','Finds businesses'),('inspector','Inspector','Checks websites'),('designer','Designer','Matches story mock-ups'),
 ('writer','Writer','Drafts messages'),('chaser','Chaser','Lines up follow-ups'),('caretaker','Caretaker','Looks after monthly clients'),
)


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS night_shift_settings (owner_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, next_beat INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS night_shift_beats (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, trade TEXT NOT NULL, town TEXT NOT NULL, radius_km INTEGER NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(owner_id,trade,town));
    CREATE TABLE IF NOT EXISTS night_shift_runs (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, local_date TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL, counts_json TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS night_shift_runs_idx ON night_shift_runs(owner_id,local_date);
    ''')


def now_local():
    return datetime.now(TZ)


def settings(conn,owner):
    row=conn.execute('SELECT * FROM night_shift_settings WHERE owner_id=?',(owner,)).fetchone()
    return dict(row) if row else dict(owner_id=owner,enabled=1,next_beat=0)


def beats(conn,owner):
    return conn.execute('SELECT * FROM night_shift_beats WHERE owner_id=? ORDER BY id',(owner,)).fetchall()


def last_run(conn,owner):
    row=conn.execute('SELECT * FROM night_shift_runs WHERE owner_id=? AND finished_at!=\'\' ORDER BY id DESC LIMIT 1',(owner,)).fetchone()
    return dict(row,counts=json.loads(row['counts_json'])) if row else None


def _due_drafts(conn,owner,on):
    """Businesses whose next message the Writer should draft now: good new leads and follow-ups due."""
    rows=conn.execute("""SELECT * FROM prospects WHERE owner_id=? AND (
        (stage='New' AND score>=50 AND (email!='' OR phone!='')) OR (stage='Contacted' AND next_on!='' AND next_on<=?))
      ORDER BY stage='Contacted' DESC, score DESC, id""",(owner,on.isoformat())).fetchall()
    return [p for p in rows if not smart_writer.stored(p)]


def run(conn,owner,source='night',on=None):
    """One full shift. Returns the counts it recorded. Never raises for a busy map service or a bad beat."""
    started=stamp();local=on or now_local().date();notes=[]
    cur=conn.execute('INSERT INTO night_shift_runs(owner_id,local_date,started_at,source) VALUES(?,?,?,?)',(owner,local.isoformat(),started,source))
    run_id=cur.lastrowid;conn.commit()
    counts=dict(found=0,checked=0,weak=0,mockups=0,drafts=0,ai_drafts=0,follow_ups=0,posts=0)
    # Scout: a couple of beats a night, rotating, so the free map service is never hammered.
    all_beats=beats(conn,owner);s=settings(conn,owner)
    if all_beats:
        start=s['next_beat']%len(all_beats)
        for i in range(min(BEATS_PER_NIGHT,len(all_beats))):
            beat=all_beats[(start+i)%len(all_beats)]
            try:counts['found']+=len(lead_engine.find(conn,owner,beat['trade'],beat['town'],beat['radius_km'])['added'])
            except WorkflowError as exc:conn.rollback();notes.append(beat['trade']+' near '+beat['town']+': '+str(exc))
        conn.execute('INSERT INTO night_shift_settings(owner_id,enabled,next_beat) VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET next_beat=excluded.next_beat',
          (owner,s['enabled'],(start+BEATS_PER_NIGHT)%len(all_beats)))
    else:notes.append('No search areas set yet, so Scout had nothing to search.')
    # Inspector: check websites found by the Scout (and any left over from manual searches).
    counts['checked']=lead_engine.check_websites(conn,owner,limit=CHECKS_PER_NIGHT)
    # Chaser: retire leads that never replied, then count follow-ups due today.
    lead_engine.expire(conn,owner,local)
    counts['follow_ups']=conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND stage='Contacted' AND next_on!='' AND next_on<=?",(owner,local.isoformat())).fetchone()[0]
    # Writer and Designer: draft the next message for the best leads; each gets the mock-up that suits it.
    ls=lead_engine.settings(conn,owner)
    for p in _due_drafts(conn,owner,local)[:DRAFTS_PER_NIGHT]:
        how=smart_writer.write(conn,owner,p,ls)
        counts['drafts']+=1;counts['ai_drafts']+=how=='ai'
        if p['stage']=='New':counts['mockups']+=1
    counts['weak']=conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND stage='New' AND score>=50",(owner,)).fetchone()[0]
    # Caretaker: this month's Google posts and review requests for Profile Care clients.
    counts['posts']=client_plans.ensure_profile_posts(conn,owner,local)
    conn.execute('UPDATE night_shift_runs SET finished_at=?,counts_json=?,notes=? WHERE id=?',(stamp(),json.dumps(counts),' '.join(notes)[:1000],run_id))
    log(conn,owner,'Night shift: found '+str(counts['found'])+', checked '+str(counts['checked'])+', drafted '+str(counts['drafts'])+'. Nothing was sent.')
    conn.commit()
    return counts


def due(conn,owner,at=None):
    """True once a day after 2 am Sydney time, if switched on and the agency is not paused."""
    at=at or now_local()
    if at.hour<START_HOUR or paused(conn) or not settings(conn,owner)['enabled']:return False
    return not conn.execute('SELECT 1 FROM night_shift_runs WHERE owner_id=? AND local_date=?',(owner,at.date().isoformat())).fetchone()


def worker_tick(path):
    """Called by the AgencyOS worker loop. Runs at most one shift per day for the one owner."""
    from contextlib import closing
    from phase3_store import connect
    with closing(connect(path)) as conn:
        owner=conn.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()
        if not owner or not due(conn,owner[0]):return False
        run(conn,owner[0])
        return True


def morning(conn,owner,limit=8):
    """The morning queue: every draft waiting for the owner's tap, most important first."""
    ls=lead_engine.settings(conn,owner)
    leads=[lead_engine.card(p,ls) for p in lead_engine.queue(conn,owner,limit=limit)]
    requests=conn.execute("SELECT r.*,c.client_name FROM plan_requests r JOIN plan_clients c ON c.id=r.client_id WHERE r.owner_id=? AND r.status='New' ORDER BY r.id LIMIT 5",(owner,)).fetchall()
    posts=conn.execute("SELECT p.*,c.client_name FROM profile_posts p JOIN plan_clients c ON c.id=p.client_id WHERE p.owner_id=? AND p.status='New' ORDER BY p.id LIMIT 6",(owner,)).fetchall()
    gmail=conn.execute("SELECT COUNT(*) FROM gmail_drafts WHERE owner_id=? AND status='Needs review'",(owner,)).fetchone()[0]
    return dict(leads=leads,requests=requests,posts=posts,gmail=gmail,total=len(leads)+len(requests)+len(posts)+(1 if gmail else 0),
                last=last_run(conn,owner),beats=len(beats(conn,owner)),enabled=bool(settings(conn,owner)['enabled']),writer=smart_writer.ai_status(conn,owner))


def register(app,get_db,login_required):
    @app.get('/night-shift',strict_slashes=False)
    @login_required
    def night_shift_home():
        conn=get_db();owner=session['user_id']
        runs=[dict(r,counts=json.loads(r['counts_json'])) for r in conn.execute('SELECT * FROM night_shift_runs WHERE owner_id=? ORDER BY id DESC LIMIT 7',(owner,))]
        return render_template('night_shift.html',settings=settings(conn,owner),beats=beats(conn,owner),runs=runs,trades=lead_engine.TRADES,radii=lead_engine.RADII,
          agents=AGENTS,writer=smart_writer.ai_status(conn,owner),stories=playbook.STORIES,niches=playbook.NICHES,start_hour=START_HOUR,paused=paused(conn))

    @app.post('/night-shift/beats')
    @login_required
    def night_shift_add_beat():
        conn=get_db();owner=session['user_id']
        trade=request.form.get('trade','');town=' '.join(request.form.get('town','').split());radius=request.form.get('radius',type=int)
        if trade not in lead_engine.TRADES or radius not in lead_engine.RADII or not 2<=len(town)<=100:
            raise WorkflowError('Pick a trade, type a suburb like "Mona Vale NSW", and pick a distance.')
        if len(beats(conn,owner))>=12:raise WorkflowError('Twelve search areas is the limit. Remove one first.')
        conn.execute('INSERT OR IGNORE INTO night_shift_beats(owner_id,trade,town,radius_km,created_at) VALUES(?,?,?,?,?)',(owner,trade,town,radius,stamp()));conn.commit()
        flash('Added. The Scout will search '+trade.lower()+' near '+town+' on a coming night.','success')
        return redirect(url_for('night_shift_home'))

    @app.post('/night-shift/beats/<int:beat_id>/remove')
    @login_required
    def night_shift_remove_beat(beat_id):
        conn=get_db();conn.execute('DELETE FROM night_shift_beats WHERE id=? AND owner_id=?',(beat_id,session['user_id']));conn.commit()
        flash('Removed.','success');return redirect(url_for('night_shift_home'))

    @app.post('/night-shift/toggle')
    @login_required
    def night_shift_toggle():
        conn=get_db();owner=session['user_id'];on=request.form.get('enabled')=='1'
        conn.execute('INSERT INTO night_shift_settings(owner_id,enabled) VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET enabled=excluded.enabled',(owner,int(on)));conn.commit()
        flash('The night shift is on. It runs after 2 am while AgencyOS is open.' if on else 'The night shift is off. Nothing runs overnight.','success')
        return redirect(url_for('night_shift_home'))

    @app.post('/night-shift/run')
    @login_required
    def night_shift_run():
        conn=get_db();owner=session['user_id']
        if paused(conn):raise WorkflowError('The agency is paused. Press Start on Home first.')
        c=run(conn,owner,source='manual')
        flash('Shift done: found '+str(c['found'])+', checked '+str(c['checked'])+' websites, drafted '+str(c['drafts'])+' messages. Nothing was sent.','success')
        return redirect(url_for('business_home')+'#ready')

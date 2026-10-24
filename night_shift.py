"""Shifts: around the clock, every 2 hours, the agents run the whole Find customers chain on their own.

Scout finds businesses on the owner's chosen beats (trade + suburb), Inspector checks their
websites, Designer matches each lead to a story mock-up, Writer drafts the next message,
Chaser lines up follow-ups and Caretaker drafts monthly-client work. It runs once a day after
2 am (Sydney time) inside the AgencyOS worker, or straight away when the Mac wakes later.
Everything lands in the morning queue for the owner's tap. Nothing is ever sent or published.
"""
import json
from datetime import datetime,timedelta,timezone
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
SHIFTS_A_DAY=12  # around the clock: a shift every 2 hours while the Mac is awake
SHIFT_GAP=timedelta(hours=24/SHIFTS_A_DAY)
BEATS_PER_NIGHT=2
CHECKS_PER_NIGHT=40
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
        (stage='New' AND score>=50 AND email!='') OR (stage='Contacted' AND next_on!='' AND next_on<=? AND email!='' AND replied_at=''))
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
    if all_beats and not conn.execute('SELECT 1 FROM night_shift_runs WHERE owner_id=? AND local_date=? AND id!=?',(owner,local.isoformat(),run_id)).fetchone():
        start=s['next_beat']%len(all_beats)
        for i in range(min(BEATS_PER_NIGHT,len(all_beats))):
            beat=all_beats[(start+i)%len(all_beats)]
            try:counts['found']+=len(lead_engine.find(conn,owner,beat['trade'],beat['town'],beat['radius_km'])['added'])
            except WorkflowError as exc:conn.rollback();notes.append(beat['trade']+' near '+beat['town']+': '+str(exc))
        conn.execute('INSERT INTO night_shift_settings(owner_id,enabled,next_beat) VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET next_beat=excluded.next_beat',
          (owner,s['enabled'],(start+BEATS_PER_NIGHT)%len(all_beats)))
    import team,sweep
    the_plan=team.plan(conn,owner);conn.commit()
    # Inspector first: read the websites already found (finding emails is the bottleneck, not finding businesses).
    # Idle agents (no clients yet for the Builder, Carer, Bookkeeper...) help the Inspector, so more leads get an email address each shift.
    import brain
    helping=brain.snapshot(conn,owner)['helpers'];counts['helpers']=len(helping)
    counts['checked']=lead_engine.check_websites(conn,owner,limit=CHECKS_PER_NIGHT+brain.HELP_CHECKS*len(helping))
    # Scout's big job: sweep the map square by square (Sydney first). It waits while the Inspector has a backlog of websites to read,
    # so leads never pile up faster than their emails can be found.
    backlog=unchecked(conn,owner);counts['backlog']=backlog
    if backlog>=BACKLOG:notes.append('Scout waited: '+str(backlog)+' websites still to read first.')
    elif the_plan['tiles']:
        try:swept,squares,sweep_notes=sweep.run(conn,owner,the_plan['tiles'],the_plan['all_australia'])
        except Exception:conn.rollback();swept,squares,sweep_notes=0,0,['The map sweep stopped early; it carries on next shift.']
        counts['swept']=swept;counts['squares']=squares;notes+=sweep_notes
    elif not all_beats:notes.append('No search areas set and the map sweep is off, so Scout had nothing to search.')
    # Chaser: retire leads that never replied, then count follow-ups due today.
    lead_engine.expire(conn,owner,local)
    counts['follow_ups']=conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND stage='Contacted' AND next_on!='' AND next_on<=?",(owner,local.isoformat())).fetchone()[0]
    # Writer and Designer: draft the next message for the best leads; each gets the mock-up that suits it.
    ls=lead_engine.settings(conn,owner);short=team.learned(conn,owner)['short'];drafted=[]
    bad=set(team.learned(conn,owner)['bad_trades'])
    due=[p for p in _due_drafts(conn,owner,local) if not (p['stage']=='New' and p['trade'] in bad)]
    # Follow-ups always; new businesses only up to the Chief of Staff's daily limit.
    follow=[p for p in due if p['stage']!='New'];fresh=sorted((p for p in due if p['stage']=='New'),key=lambda p:not playbook.story_for(p['trade']))[:the_plan['drafts']]  # builders, landscapers and salons first: the story demos are our edge
    for p in follow[:the_plan['safe']]+fresh:  # one daily number: the Deliverability Guard's
        how=smart_writer.write(conn,owner,p,ls,coaching=team.coaching(conn,owner,p['trade']) if smart_writer.ai_status(conn,owner)['ready'] else '',short=short)
        counts['drafts']+=1;counts['ai_drafts']+=how=='ai';drafted.append(p['id'])
        if p['stage']=='New':counts['mockups']+=1
    # CEO: check every draft before it reaches the owner.
    review=team.ceo_review(conn,owner,drafted)
    counts['ceo_ready']=review['ready'];counts['ceo_held']=review['held']
    counts['weak']=conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND stage='New' AND score>=50",(owner,)).fetchone()[0]
    # Caretaker: this month's Google posts and review requests for Profile Care clients.
    counts['posts']=client_plans.ensure_profile_posts(conn,owner,local)
    conn.execute('UPDATE night_shift_runs SET finished_at=?,counts_json=?,notes=? WHERE id=?',(stamp(),json.dumps(counts),' '.join(notes)[:1000],run_id))
    log(conn,owner,'Shift: found '+str(counts['found']+counts.get('swept',0))+', checked '+str(counts['checked'])+', drafted '+str(counts['drafts'])+', CEO passed '+str(counts['ceo_ready'])+'. Nothing was sent.')
    conn.commit()
    return counts


def due(conn,owner,at=None):
    """True every 2 hours, day and night, if switched on and the agency is not paused."""
    at=at or now_local()
    if paused(conn) or not settings(conn,owner)['enabled']:return False
    last=conn.execute('SELECT started_at FROM night_shift_runs WHERE owner_id=? ORDER BY id DESC LIMIT 1',(owner,)).fetchone()
    if not last:return True
    try:started=datetime.fromisoformat(last['started_at'])
    except ValueError:return True
    if started.tzinfo is None:started=started.replace(tzinfo=timezone.utc)
    return at-started>=SHIFT_GAP-timedelta(minutes=5)


def drafted_today(conn,owner,on=None):
    """New-business drafts written by today's shifts, so the day's limit holds across all 12."""
    total=0
    for r in conn.execute('SELECT counts_json FROM night_shift_runs WHERE owner_id=? AND local_date=?',(owner,(on or now_local().date()).isoformat())):
        try:total+=json.loads(r['counts_json'] or '{}').get('mockups',0)
        except ValueError:pass
    return total


def worker_tick(path):
    """Called by the AgencyOS worker loop. Runs a shift every 2 hours, day and night, for the one owner."""
    from contextlib import closing
    from phase3_store import connect
    with closing(connect(path)) as conn:
        owner=conn.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()
        if owner:
            import pitch
            try:pitch.detect_replies(conn,owner[0])  # a lead wrote back: stop chasing them and buzz the owner's phone
            except Exception:conn.rollback()
            import autosend
            try:autosend.tick(conn,owner[0])  # opt-out replies always; sends only if Benji switched CEO auto-send on
            except Exception:conn.rollback()
            import team
            try:lead_engine.sync_gmail(conn,owner[0])  # approved drafts that Benji sent: schedule their follow-ups
            except Exception:conn.rollback()
            try:
                import ceo_live
                ceo_live.budget_alert(conn,owner[0])  # AI budget used up: one email a month with how to top it up
            except Exception:conn.rollback()
            try:team.notify(conn,owner[0])  # drafts ready: buzz the owner's phone (7 am to 9 pm, at most 3 a day)
            except Exception:conn.rollback()
            try:
                if team.settings(conn,owner[0])['keep_awake']:keep_awake()
            except Exception:pass
            try:inspect(conn,owner[0])  # between shifts too: a few websites a minute, so emails are found all day, not 40 every 2 hours
            except Exception:conn.rollback()
        if not owner or not due(conn,owner[0]):return False
        awake=_stay_awake()
        try:run(conn,owner[0])
        finally:
            if awake:awake.terminate()
        return True


BACKLOG=300  # websites waiting to be read: at or above this, the Scout stops adding new businesses until the Inspector catches up


def unchecked(conn,owner):
    return conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND website!='' AND checked_at='' AND stage='New'",(owner,)).fetchone()[0]


INSPECT_EVERY,INSPECT_BATCH=60,5  # seconds, websites: about 7,000 a day, one quick homepage (and Contact page) visit each
_LAST_INSPECT=[0.0]


def inspect(conn,owner,clock=None):
    """The Inspector keeps working between shifts while shifts are on: a few websites a minute, reading each business's email. Returns how many it checked."""
    import time
    now=(clock or time.monotonic)()
    if now-_LAST_INSPECT[0]<INSPECT_EVERY or paused(conn) or not settings(conn,owner)['enabled']:return 0
    _LAST_INSPECT[0]=now
    return lead_engine.check_websites(conn,owner,limit=INSPECT_BATCH)


_AWAKE=None


def keep_awake():
    """While AgencyOS is open on a plugged-in Mac, stop it going to sleep (caffeinate -s only works on power). Free.
    Renewed every few minutes by the worker loop, so it stops by itself soon after AgencyOS closes."""
    global _AWAKE
    import shutil,subprocess,sys
    if sys.platform!='darwin' or not shutil.which('caffeinate'):return None
    if _AWAKE is not None and _AWAKE.poll() is None:return _AWAKE
    try:_AWAKE=subprocess.Popen(['caffeinate','-s','-i','-t','900'])
    except OSError:_AWAKE=None
    return _AWAKE


def _stay_awake():
    """On a Mac, stop it dozing off mid-shift after its 2 am wake. Free; ends when the shift does."""
    import shutil,subprocess,sys
    if sys.platform!='darwin' or not shutil.which('caffeinate'):return None
    try:return subprocess.Popen(['caffeinate','-i','-t','3600'])
    except OSError:return None


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
        flash('Shifts are on. The team works every 2 hours, day and night, while AgencyOS is open.' if on else 'Shifts are off. The team is not working.','success')
        return redirect(url_for('ceo_live') if request.form.get('next')=='ceo' else url_for('night_shift_home'))

    @app.post('/night-shift/run')
    @login_required
    def night_shift_run():
        conn=get_db();owner=session['user_id']
        if paused(conn):raise WorkflowError('The agency is paused. Press Start on Home first.')
        c=run(conn,owner,source='manual')
        flash('Shift done: found '+str(c['found'])+', checked '+str(c['checked'])+' websites, drafted '+str(c['drafts'])+' messages, CEO passed '+str(c.get('ceo_ready',0))+'.','success')
        return redirect(url_for('ceo_live') if request.form.get('next')=='ceo' else url_for('business_home')+'#ready')

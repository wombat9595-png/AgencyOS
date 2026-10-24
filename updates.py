"""Updates: every 35 minutes, day and night, a short plain-English note in AgencyOS of what happened since the last one.

Only reads what the app already records: the lead log (emails, replies, bounces, opt-outs), the leads table (new leads,
websites checked, emails found) and the team shift log. It never sends anything, so it costs nothing. Each note covers
exactly the time since the previous note, and each 35-minute slot is written once, so a restart cannot repeat one.
"""
import json
from datetime import datetime,timedelta,timezone
from flask import render_template,session
from phase3_store import stamp
from phase4_store import paused
import autosend

EVERY=35*60  # seconds
KEEP_DAYS=30
CATCH_UP=timedelta(hours=24)  # after a long sleep, one note covers at most the last day


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS activity_updates (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, slot INTEGER NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
      headline TEXT NOT NULL, lines_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT '',
      UNIQUE(owner_id,slot));
    ''')


def _iso(at):return at.astimezone(timezone.utc).isoformat()


def _clock(at):return at.astimezone(autosend.TZ).strftime('%-I:%M %p').lower().replace(' ',' ')


def _names(rows,most=3):
    names=[r['name']+(' ('+r['suburb']+')' if r['suburb'] else '') for r in rows]
    if len(names)<=most:return ', '.join(names[:-1])+(' and ' if len(names)>1 else '')+names[-1]
    return ', '.join(names[:most])+' and '+str(len(names)-most)+' more'


def _plural(n,one,many=None):return str(n)+' '+(one if n==1 else (many or one+'s'))


def _since(at):
    """'Since 2:00 pm' or, when the gap is over a day long, with the date."""
    local=at.astimezone(autosend.TZ)
    return local.strftime('%-I:%M %p')+('' if local.date()==autosend.now_local().date() else local.strftime(', %a %-d %b'))


def summarise(conn,owner,start,end):
    """The note for start..end: (headline, lines). Every line comes from a log the app already keeps."""
    a,b=_iso(start),_iso(end)
    def events(action):
        return conn.execute("""SELECT DISTINCT p.id,p.name,p.suburb FROM prospect_log l JOIN prospects p ON p.id=l.prospect_id
          WHERE l.owner_id=? AND l.action=? AND l.created_at>=? AND l.created_at<? ORDER BY l.id""",(owner,action,a,b)).fetchall()
    auto=events('auto_sent');auto_ids={r['id'] for r in auto}
    mine=[r for r in events('sent') if r['id'] not in auto_ids]  # an auto-send is logged as a send too; count it once
    replied=events('replied');opted=events('opted_out');bounced=events('bounced');approved=events('approved')
    interested=events('interested');customers=events('customer')
    new_leads=conn.execute('SELECT COUNT(*) FROM prospects WHERE owner_id=? AND created_at>=? AND created_at<?',(owner,a,b)).fetchone()[0]
    checked=conn.execute('SELECT email,site_check FROM prospects WHERE owner_id=? AND checked_at>=? AND checked_at<?',(owner,a,b)).fetchall()
    found=0
    for r in checked:
        try:found+=bool(r['email'] and json.loads(r['site_check'] or '{}').get('email'))
        except ValueError:pass
    shifts=conn.execute("SELECT started_at,counts_json FROM night_shift_runs WHERE owner_id=? AND started_at>=? AND started_at<? AND finished_at!='' ORDER BY id",(owner,a,b)).fetchall()

    lines=[];bits=[]
    if customers:lines.append('🎉 '+_names(customers)+(' is' if len(customers)==1 else ' are')+' now a customer.');bits.append(_plural(len(customers),'new customer'))
    if interested:lines.append(_names(interested)+' said they are interested. Open Find customers and reply today.');bits.append(_plural(len(interested),'interested lead'))
    if replied:lines.append(_plural(len(replied),'business','businesses')+' wrote back: '+_names(replied)+'. Their follow-ups have stopped. Reply from Gmail soon.');bits.append(_plural(len(replied),'reply','replies'))
    if auto:lines.append('The CEO emailed '+_plural(len(auto),'business','businesses')+': '+_names(auto)+'.');bits.append(_plural(len(auto),'email')+' sent')
    if mine:lines.append('You emailed '+_names(mine)+'.')
    if approved:lines.append('You approved '+_plural(len(approved),'draft')+' (they wait in Gmail Drafts until you press Send).')
    if opted:lines.append(_names(opted)+' asked not to be emailed. They are on Do not contact now.')
    if bounced:lines.append(_plural(len(bounced),'email')+' bounced ('+_names(bounced)+'). Those addresses will not be used again.');bits.append(_plural(len(bounced),'bounce'))
    if new_leads:lines.append('The Scout added '+_plural(new_leads,'new lead')+'.');bits.append(_plural(new_leads,'new lead'))
    if checked:
        lines.append('The team checked '+_plural(len(checked),'website')+' and found '+('no new email addresses.' if not found else _plural(found,'new email address','new email addresses')+' on them.'))
        if found:bits.append(_plural(found,'email')+' found')
    for r in shifts:
        try:c=json.loads(r['counts_json'] or '{}')
        except ValueError:c={}
        lines.append('A team shift ran at '+_clock(datetime.fromisoformat(r['started_at']))+': drafted '+str(c.get('drafts',0))+', the CEO passed '+str(c.get('ceo_ready',0))+(' and held '+str(c['ceo_held']) if c.get('ceo_held') else '')+'.')
    lines.extend(_right_now(conn,owner,quiet=not lines))
    headline=', '.join(bits[:3]).capitalize() if bits else ('Shift ran, nothing new to send' if shifts else 'Quiet: nothing new happened')
    return headline,lines


def _right_now(conn,owner,quiet):
    """One or two lines on where things stand, so a quiet note still says why it was quiet."""
    out=[]
    if paused(conn):return ['AgencyOS is paused, so nobody is working. Press Start on Home to carry on.']
    try:
        auto=autosend.status(conn,owner)
        if not auto['polling']:out.append('Inbox checking is off, so replies, bounces and opt-outs cannot be seen until you turn it on in Inbox.')
        if auto['enabled']:out.append('Today so far: '+str(auto['sent_today'])+' of '+str(auto['daily_max'])+' emails sent'+('. '+auto['waiting'] if auto['waiting'] and quiet else '.'))
        elif quiet:out.append('Auto-send is off, so the CEO is not emailing anyone.')
    except Exception:
        out.append('Could not read the auto-send status this time.')
    return out


def tick(conn,owner,now=None):
    """Write the note for the 35-minute slot that just ended, once. Returns True if it wrote one."""
    now=now or datetime.now(timezone.utc)
    slot=int(now.timestamp())//EVERY
    end=datetime.fromtimestamp(slot*EVERY,timezone.utc)
    last=conn.execute('SELECT slot,period_end FROM activity_updates WHERE owner_id=? ORDER BY slot DESC LIMIT 1',(owner,)).fetchone()
    if last and last['slot']>=slot:return False
    start=datetime.fromisoformat(last['period_end']) if last else end-timedelta(seconds=EVERY)
    gap_note=''
    if end-start>CATCH_UP:start=end-CATCH_UP
    if end-start>timedelta(seconds=EVERY*1.5):
        gap_note='This note covers since '+_since(start)+', because AgencyOS was closed or the Mac was asleep for a while.'
    headline,lines=summarise(conn,owner,start,end)
    if gap_note:lines.insert(0,gap_note)
    conn.execute('INSERT OR IGNORE INTO activity_updates(owner_id,slot,period_start,period_end,headline,lines_json,created_at) VALUES(?,?,?,?,?,?,?)',
      (owner,slot,_iso(start),_iso(end),headline,json.dumps(lines),stamp()))
    conn.execute('DELETE FROM activity_updates WHERE owner_id=? AND period_end<?',(owner,_iso(end-timedelta(days=KEEP_DAYS))))
    conn.commit()
    return True


def recent(conn,owner,limit=41):
    """Newest first. 41 notes is about one day."""
    items=[]
    for r in conn.execute('SELECT * FROM activity_updates WHERE owner_id=? ORDER BY slot DESC LIMIT ?',(owner,limit)).fetchall():
        start,end=datetime.fromisoformat(r['period_start']),datetime.fromisoformat(r['period_end'])
        items.append(dict(id=r['id'],headline=r['headline'],lines=json.loads(r['lines_json']),unread=not r['read_at'],
          time=_since(end),span=_clock(start)+' to '+_clock(end)))
    return items


def unread(conn,owner):
    try:return conn.execute("SELECT COUNT(*) FROM activity_updates WHERE owner_id=? AND read_at=''",(owner,)).fetchone()[0]
    except Exception:return 0


def register(app,get_db,login_required):
    @app.context_processor
    def updates_badge():
        if not session.get('user_id'):return {}
        return {'updates_unread':lambda:unread(get_db(),session['user_id'])}

    @app.get('/updates',strict_slashes=False)
    @login_required
    def updates_home():
        conn=get_db();owner=session['user_id']
        items=recent(conn,owner)
        conn.execute("UPDATE activity_updates SET read_at=? WHERE owner_id=? AND read_at=''",(stamp(),owner));conn.commit()
        return render_template('updates.html',items=items)

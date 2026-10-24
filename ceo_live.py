"""CEO live: one page that shows what the agents and CEO auto-send are doing right now, plus the AI budget alert.

The page refreshes itself every 30 seconds. It only reads, except for the on/off buttons it shares with the Inbox
and Shifts pages. The budget alert emails the owner once a month when the AI writer's monthly cap is used up.
"""
import json
from datetime import date,datetime,timedelta
from flask import render_template,session
from phase3_store import WorkflowError,stamp
from phase4_store import paused
import autosend
import gmail_agent
import lead_engine
import night_shift
import smart_writer

ANTHROPIC_BILLING='https://console.anthropic.com/settings/billing'
GMAIL='https://mail.google.com/mail/?authuser='+gmail_agent.ACCOUNT  # always the business inbox, even when the browser's main Gmail is another account


def gmail_links(conn,owner):
    """Buttons that open the business Gmail itself, plus how many leads wrote back."""
    replied=conn.execute("SELECT COUNT(DISTINCT prospect_id) FROM prospect_log WHERE owner_id=? AND action='replied'",(owner,)).fetchone()[0]
    return dict(account=gmail_agent.ACCOUNT,sent=GMAIL+'#sent',inbox=GMAIL+'#inbox',spam=GMAIL+'#spam',replied=replied)
EVENTS={'auto_sent':'CEO emailed','sent':'You emailed','approved':'You approved (in Gmail Drafts)','replied':'Wrote back','opted_out':'Said no thanks',
  'bounced':'Email bounced','interested':'Interested','customer':'Became a customer'}


def migrate(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS budget_alerts (owner_id INTEGER NOT NULL, month TEXT NOT NULL, sent_at TEXT NOT NULL, PRIMARY KEY(owner_id,month))')


def leads(conn,owner):
    def n(where):return conn.execute('SELECT COUNT(*) FROM prospects WHERE owner_id=? AND '+where,(owner,)).fetchone()[0]
    total=n('1');with_email=n("email!=''")
    emailed=n("email!='' AND (touches>0 OR stage IN ('Contacted','Interested','Customer','Not interested','No reply'))")
    blocked=n("email!='' AND touches=0 AND stage IN ('Do not contact','Skipped')")
    return dict(total=total,with_email=with_email,no_email=total-with_email,emailed=emailed,
      left=max(0,with_email-emailed-blocked),ready=len(autosend.candidates(conn,owner)),
      unchecked=n("website!='' AND checked_at='' AND stage='New'"),no_site=n("email='' AND website=''"),
      site_no_email=n("email='' AND website!='' AND checked_at!=''"),in_drafts=n("stage='Approved' AND gmail_draft_id!=''"))


def finish_date(conn,owner,left,today=None):
    """When every lead that has an email address will have had one, at the warm-up pace (20 a day for a week, then +5 a day, up to the limit)."""
    import team
    today=today or autosend.now_local().date()
    if not left:return today
    held=autosend.daily_cap(conn,owner,today)<team.safe_daily(conn,owner,today)  # bounces are holding the cap at 20
    started=conn.execute("SELECT 1 FROM prospect_log WHERE owner_id=? AND action IN ('sent','auto_sent') LIMIT 1",(owner,)).fetchone()
    day=today;cap=autosend.daily_cap(conn,owner,today)
    for i in range(3650):
        left-=cap
        if left<=0:return day
        day+=timedelta(days=1)
        if not held:cap=team.safe_daily(conn,owner,day) if started else min(team.settings(conn,owner)['daily_drafts'],team.GMAIL_SAFE_MAX,team.WARM_START+team.WARM_STEP*max(0,i-5))
        if not cap:return None
    return None


def feed(conn,owner,limit=40):
    rows=conn.execute("""SELECT l.created_at,l.action,l.detail,p.name,(SELECT a.gmail_id FROM autosend_log a WHERE a.owner_id=l.owner_id AND a.prospect_id=l.prospect_id AND a.gmail_id!='' ORDER BY a.id DESC LIMIT 1) gmail_id
      FROM prospect_log l JOIN prospects p ON p.id=l.prospect_id
      WHERE l.owner_id=? AND l.action IN ("""+','.join('?'*len(EVENTS))+""") ORDER BY l.id DESC LIMIT ?""",(owner,*EVENTS,limit)).fetchall()
    items=[];seen=set()
    auto={(r['name'],r['created_at'][:16]) for r in rows if r['action']=='auto_sent'}
    for r in rows:
        key=(r['action'],r['name'],r['created_at'][:16])
        # One line per thing that happened: an auto-send is also logged as a send, and a re-approval as a second approval.
        if key in seen or (r['action']=='sent' and (r['name'],r['created_at'][:16]) in auto):continue
        seen.add(key)
        items.append(dict(at=r['created_at'],what=EVENTS[r['action']],who=r['name'],detail=r['detail'] if r['action'] in ('auto_sent','opted_out','bounced') else '',
          link=GMAIL+'#all/'+r['gmail_id'] if r['action']=='auto_sent' and r['gmail_id'] else ''))
    for r in conn.execute("SELECT started_at,counts_json FROM night_shift_runs WHERE owner_id=? AND finished_at!='' ORDER BY id DESC LIMIT 10",(owner,)).fetchall():
        try:c=json.loads(r['counts_json'] or '{}')
        except ValueError:c={}
        items.append(dict(at=r['started_at'],what='Team shift',who='Found '+str(c.get('found',0)+c.get('swept',0))+', checked '+str(c.get('checked',0))+' websites, drafted '+str(c.get('drafts',0))+', CEO passed '+str(c.get('ceo_ready',0)),detail=''))
    items.sort(key=lambda i:i['at'],reverse=True)
    for i in items:i['time']=_clock(i['at'])
    return items[:limit]


def _clock(iso):
    try:
        at=datetime.fromisoformat(iso).astimezone(autosend.TZ);today=autosend.now_local().date()
        return at.strftime('%-I:%M %p')+('' if at.date()==today else at.strftime(', %a %-d %b'))
    except ValueError:return ''


def next_email(conn,owner,auto):
    """Plain words for when the next email goes, or why it can't."""
    if not auto['enabled']:return 'Auto-send is off. Switch it on below and the CEO starts emailing.'
    if auto['waiting'].startswith('Spacing'):
        at=datetime.fromtimestamp(auto['last_attempt'],autosend.TZ)+autosend.gap(auto['daily_max'])
        return 'Next email at about '+at.strftime('%-I:%M %p')+'.'
    if auto['waiting']:return auto['waiting']
    return 'Sending the next email now.' if auto['ready'] else 'Nothing ready to send. The team drafts more on every shift.'


def budget_alert(conn,owner,send=None,today=None):
    """Once a month, when the AI writer's cap is used up, email the owner how to top it up. Returns True if it sent."""
    status=smart_writer.ai_status(conn,owner)
    if not status['enabled'] or status['spent_cents']<status['cap_cents']:return False
    month=(today or autosend.now_local().date()).strftime('%Y-%m')
    if conn.execute('SELECT 1 FROM budget_alerts WHERE owner_id=? AND month=?',(owner,month)).fetchone():return False
    s=lead_engine.settings(conn,owner);cap='A$'+format(status['cap_cents']/100,'.2f')
    body=('Hi '+s['name'].split()[0]+',\n\nYour AI writer has used this month\'s '+cap+' budget. Until you raise it, emails are still written and sent, '
      'but with the plain template instead of the AI.\n\nTo keep the AI writing:\n'
      '1. Add credit to your Anthropic account (if it is low): '+ANTHROPIC_BILLING+'\n'
      '2. Raise the monthly cap in AgencyOS: open http://127.0.0.1:5050/night-shift on your Mac, change "Monthly cap (A$)", press Save.\n\n'
      'This email is from AgencyOS on your Mac. You get one a month at most.')
    try:
        (send or gmail_agent.send_outreach)(conn,owner,s['email'],'AgencyOS: your '+cap+' AI budget is used up',body)
    except WorkflowError:
        return False
    import pitch
    pitch.ping(conn,owner,'AI budget used up','Check your email for how to top it up.')
    conn.execute('INSERT INTO budget_alerts(owner_id,month,sent_at) VALUES(?,?,?)',(owner,month,stamp()));conn.commit()
    return True


def register(app,get_db,login_required):
    @app.get('/ceo',strict_slashes=False)
    @login_required
    def ceo_live():
        conn=get_db();owner=session['user_id']
        auto=autosend.status(conn,owner);numbers=leads(conn,owner)
        return render_template('ceo_live.html',auto=auto,leads=numbers,feed=feed(conn,owner),next_email=next_email(conn,owner,auto),
          finish=finish_date(conn,owner,numbers['left']),shifts=night_shift.settings(conn,owner),last_shift=night_shift.last_run(conn,owner),
          paused=paused(conn),writer=smart_writer.ai_status(conn,owner),gmail=gmail_links(conn,owner))

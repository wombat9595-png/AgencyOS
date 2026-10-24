"""CEO auto-send: OFF by default. Once the owner switches it on, AgencyOS sends first emails the CEO has passed, by itself.

Every limit is checked again right before every single send:
- Only drafts the CEO passed (ceo_status 'ready') that still pass the playbook: they name the business, carry the
  owner's name and keep the "no thanks" opt-out.
- Every day of the week, 6 am to 10 pm Sydney time, spread evenly so it looks like a person sending.
- A daily cap that warms the inbox up: 20 a day in the first week, 10 more each week (the Deliverability Guard's
  number), but held at 20 whenever more than 3 in 100 recent emails bounce.
- Bounces: Gmail's "address not found" notices mark that business and count against the inbox. Too many bounces
  (5 in a day, or over 5 in 100 across the last week) switch auto-send off before Gmail flags the account.
- Never the same business twice: first emails only, and one ever per email address, per business name and suburb,
  and per business email domain. Follow-ups stay the owner's tap.
- Opt-outs: any reply saying "no thanks", unsubscribe and the like marks the business "Do not contact" as soon as the
  inbox check sees it. If the inbox check has not worked for 2 hours, sending stops, so an opt-out is never missed
  for long (well inside the Spam Act's 5 working days).
- Needs Gmail's separate sending permission, which only the owner can grant (Reconnect with the sending box ticked).
A send that fails or has an unknown outcome switches auto-send off; nothing is ever retried.
"""
import re
import time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from flask import flash,redirect,request,session,url_for
from phase3_store import WorkflowError,stamp
from phase4_store import paused
from production_security import audit
from sales_store import log
import gmail_agent
import lead_engine
import playbook
import sales_email
import smart_writer

TZ=ZoneInfo('Australia/Sydney')
START_HOUR,END_HOUR=6,22  # 6:00 am up to 10:00 pm, every day
MIN_GAP,MAX_GAP=timedelta(minutes=5),timedelta(minutes=25)  # the day's emails spread over the window, never in a burst
HOLD_RATE,STOP_RATE,STOP_DAY=0.03,0.05,5  # bounce rate that holds the cap at 20; rate and daily count that stop sending
BOUNCE_FROM=re.compile(r'^(mailer-daemon|postmaster)@',re.I)
BOUNCE_SUBJECT=re.compile(r'(delivery status notification|undeliver|mail delivery (failed|subsystem)|address not found|returned mail|failure notice)',re.I)
INBOX_FRESH=timedelta(hours=2)
# Shared mail services: two businesses on gmail.com are not the same business.
FREE_MAIL={'gmail.com','googlemail.com','outlook.com','hotmail.com','live.com','live.com.au','msn.com','yahoo.com','yahoo.com.au',
  'icloud.com','me.com','mac.com','bigpond.com','bigpond.net.au','bigpond.com.au','optusnet.com.au','iinet.net.au','internode.on.net',
  'tpg.com.au','westnet.com.au','aol.com','protonmail.com','proton.me','outlook.com.au','hotmail.com.au'}
OPT_OUT=re.compile(r"\b(no,? thanks?|no thank you|not interested|unsubscribe|remove me|take me off|opt(?:-| )?out|stop (?:emailing|contacting|sending)|"
  r"do not (?:contact|email)|don'?t (?:contact|email)|please stop)\b")
# Where a reply's quoted copy of our own email starts (Gmail, Apple Mail, Outlook, phones).
QUOTE_START=re.compile(r'^\s*(>|on .{3,200} wrote:|-{2,}\s*original message|from:\s|sent from my)',re.I)


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS autosend_settings (
      owner_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, changed_at TEXT NOT NULL DEFAULT '',
      last_attempt REAL NOT NULL DEFAULT 0, optout_cursor INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS autosend_log (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, prospect_id INTEGER NOT NULL, business TEXT NOT NULL,
      email TEXT NOT NULL, business_key TEXT NOT NULL, domain TEXT NOT NULL DEFAULT '', local_date TEXT NOT NULL,
      sent_at TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL, gmail_id TEXT NOT NULL DEFAULT '',
      UNIQUE(owner_id,email), UNIQUE(owner_id,business_key));
    CREATE INDEX IF NOT EXISTS autosend_log_day ON autosend_log(owner_id,local_date);
    ''')


def now_local():
    return datetime.now(TZ)


def settings(conn,owner):
    row=conn.execute('SELECT * FROM autosend_settings WHERE owner_id=?',(owner,)).fetchone()
    return dict(row) if row else dict(owner_id=owner,enabled=0,changed_at='',last_attempt=0,optout_cursor=0,note='')


def _save(conn,owner,**values):
    current=settings(conn,owner);current.update(values)
    conn.execute('''INSERT INTO autosend_settings(owner_id,enabled,changed_at,last_attempt,optout_cursor,note) VALUES(:owner_id,:enabled,:changed_at,:last_attempt,:optout_cursor,:note)
      ON CONFLICT(owner_id) DO UPDATE SET enabled=excluded.enabled,changed_at=excluded.changed_at,last_attempt=excluded.last_attempt,
      optout_cursor=excluded.optout_cursor,note=excluded.note''',current)


def in_window(at=None):
    """Every day, 6 am to 10 pm Sydney time."""
    at=(at or now_local()).astimezone(TZ)
    return START_HOUR<=at.hour<END_HOUR


def domain_of(email):
    domain=email.rsplit('@',1)[-1].casefold()
    return '' if domain in FREE_MAIL else domain


def business_key(p):
    return lead_engine.norm(p['name'])+'|'+lead_engine.norm(p['suburb'])


def own_words(text):
    """The reply's own words: drop the quoted copy of our email, which itself says "no thanks"."""
    lines=[]
    for line in text.splitlines():
        if QUOTE_START.match(line):break
        lines.append(line)
    return '\n'.join(lines)


def is_opt_out(text):
    return bool(OPT_OUT.search(own_words(text).casefold().replace('’',"'")))


def opt_out(conn,owner,email,why):
    """Stop every future email to this address and its business, for good."""
    email=email.casefold();domain=domain_of(email)
    rows=conn.execute("SELECT * FROM prospects WHERE owner_id=? AND stage!='Do not contact' AND email!='' AND (lower(email)=? OR (?!='' AND lower(email) LIKE ?))",
      (owner,email,domain,'%@'+domain)).fetchall()
    for p in rows:
        conn.execute("UPDATE prospects SET stage='Do not contact',next_on='',ceo_status='held',ceo_note='Opted out' WHERE id=?",(p['id'],))
        lead_engine.record(conn,owner,p,'opted_out',why)
    try:sales_email.suppress(conn,owner,email,'Replied asking for no more emails')
    except WorkflowError:pass
    return len(rows)


def process_optouts(conn,owner):
    """Read new incoming mail (already imported by the inbox check) and act on every opt-out. Runs even with auto-send off."""
    s=settings(conn,owner);cursor=s['optout_cursor'];found=0
    for m in conn.execute("SELECT * FROM gmail_mail WHERE owner_id=? AND direction='incoming' AND id>? ORDER BY id LIMIT 200",(owner,cursor)).fetchall():
        cursor=m['id']
        try:content=gmail_agent.unseal(m['content_cipher'])
        except WorkflowError:continue
        if is_bounce(m['sender'],content.get('subject','')):
            bounced(conn,owner,content.get('body',''));continue
        if is_opt_out(content.get('subject','')+'\n'+content.get('body','')):
            found+=opt_out(conn,owner,m['sender'],'Reply: '+own_words(content.get('body',''))[:200])
    if cursor!=s['optout_cursor']:_save(conn,owner,optout_cursor=cursor)
    return found


def is_bounce(sender,subject):
    return bool(BOUNCE_FROM.match(sender or '') or BOUNCE_SUBJECT.search(subject or ''))


def bounced(conn,owner,body):
    """A "could not deliver" notice: find which auto-sent address it is about, mark it, and stop if the inbox is at risk."""
    text=body.casefold();hits=0
    for r in conn.execute("SELECT * FROM autosend_log WHERE owner_id=? AND status='Sent' ORDER BY id DESC LIMIT 500",(owner,)).fetchall():
        if r['email'] in text:
            conn.execute("UPDATE autosend_log SET status='Bounced' WHERE id=?",(r['id'],))
            conn.execute("UPDATE prospects SET stage='No reply',next_on='',ceo_note='Email address bounced' WHERE id=? AND owner_id=?",(r['prospect_id'],owner))
            p=conn.execute('SELECT * FROM prospects WHERE id=?',(r['prospect_id'],)).fetchone()
            if p:lead_engine.record(conn,owner,p,'bounced',r['email'])
            hits+=1
    if hits and settings(conn,owner)['enabled']:
        today,rate=bounces_today(conn,owner),bounce_rate(conn,owner)
        if today>=STOP_DAY or rate>STOP_RATE:
            _save(conn,owner,enabled=0,changed_at=stamp(),note='Switched itself off: too many emails bounced ('+str(today)+' today, '+str(round(rate*100))+' in 100 this week). Sending more could get Gmail to block the account.')
            log(conn,owner,'CEO auto-send stopped: too many bounced emails.')
    return hits


def bounces_today(conn,owner,on=None):
    return conn.execute("SELECT COUNT(*) FROM autosend_log WHERE owner_id=? AND status='Bounced' AND local_date=?",(owner,(on or now_local().date()).isoformat())).fetchone()[0]


def bounce_rate(conn,owner,on=None):
    """Share of the last 7 days' auto-sent emails that bounced. Needs 10 sends before it counts."""
    since=((on or now_local().date())-timedelta(days=6)).isoformat()
    row=conn.execute("SELECT COUNT(*) n,SUM(status='Bounced') b FROM autosend_log WHERE owner_id=? AND local_date>=?",(owner,since)).fetchone()
    return (row['b'] or 0)/row['n'] if row['n']>=10 else 0.0


def daily_cap(conn,owner,on=None):
    """Emails auto-send may send today: the Deliverability Guard's warm-up number, held at the starting 20 while bounces are high."""
    import team
    safe=team.safe_daily(conn,owner,on)
    return min(safe,team.WARM_START) if bounce_rate(conn,owner,on)>HOLD_RATE else safe


def gap(cap):
    """Time between emails: the sending window shared out over the day's cap, between 5 and 25 minutes."""
    share=timedelta(hours=END_HOUR-START_HOUR)/max(cap,1)
    return max(MIN_GAP,min(MAX_GAP,share))


def sent_today(conn,owner,on=None):
    return conn.execute("SELECT COUNT(*) FROM autosend_log WHERE owner_id=? AND local_date=?",(owner,(on or now_local().date()).isoformat())).fetchone()[0]


def inbox_fresh(conn,owner,now=None):
    row=conn.execute('SELECT polling,last_sync,error FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
    return bool(row and row['polling'] and not row['error'] and row['last_sync']>=(now or time.time())-INBOX_FRESH.total_seconds())


def blocked(conn,owner,at=None):
    """Why auto-send cannot send right now, in plain English. Empty string means it may send."""
    at=at or now_local();s=settings(conn,owner)
    if not s['enabled']:return 'Auto-send is off.'
    if paused(conn):return 'AgencyOS is paused.'
    if not in_window(at):return 'Outside sending hours (6 am to 10 pm Sydney time, every day). It starts again at 6 am.'
    try:
        if not gmail_agent.can_send(conn,owner):return 'Gmail send permission is missing. Press Reconnect with the sending box ticked.'
    except WorkflowError:return 'Gmail is not readable on this Mac.'
    if not inbox_fresh(conn,owner):return 'The inbox check has not worked in the last 2 hours, so opt-outs could be missed. Turn on inbox checking.'
    day=at.astimezone(TZ).date()
    cap=daily_cap(conn,owner,day)
    if sent_today(conn,owner,day)>=cap:return 'Today\'s '+str(cap)+' are sent. More tomorrow from 6 am.'
    total=conn.execute("SELECT COUNT(DISTINCT prospect_id) FROM prospect_log WHERE owner_id=? AND on_date=? AND action='sent'",(owner,day.isoformat())).fetchone()[0]
    if total>=cap:return 'Today\'s safe email number is reached (counting the ones you sent yourself).'
    wait=gap(cap)
    if time.time()-s['last_attempt']<wait.total_seconds():return 'Spacing emails out: the next one goes about '+str(int(wait.total_seconds()//60))+' minutes after the last.'
    return ''


def problems(conn,owner,p,s):
    """Reasons this exact draft must not go out by itself. Empty list means it may."""
    found=[]
    if p['stage']!='New' or p['touches']:found.append('already emailed')
    if p['ceo_status']!='ready':found.append('not passed by the CEO')
    if p['draft_kind']!='first' or not smart_writer.stored(p):found.append('not a first email')
    if not p['email']:return found+['no email address']
    subject,body=p['draft_subject'],p['draft_body']
    import team
    found+=playbook.review(subject,body,p,s,'first')+playbook.review_words(subject,body,team.avoid_words(conn,owner))
    if 'no thanks' not in body.casefold():found.append('missing the "no thanks" opt-out')
    if s['name'].casefold() not in body.casefold():found.append('missing your name')
    email=p['email'].casefold();domain=domain_of(email)
    if conn.execute('SELECT 1 FROM p5_suppressions WHERE user_id=? AND email=?',(owner,email)).fetchone():found.append('opted out')
    if conn.execute("SELECT 1 FROM prospect_log WHERE owner_id=? AND prospect_id=? AND action='sent'",(owner,p['id'])).fetchone():found.append('already emailed')
    if conn.execute("""SELECT 1 FROM prospects WHERE owner_id=? AND id!=? AND (lower(email)=? OR (?!='' AND lower(email) LIKE ?))
        AND (touches>0 OR stage IN ('Approved','Contacted','Interested','Customer','Not interested','No reply','Do not contact'))""",(owner,p['id'],email,domain,'%@'+domain)).fetchone():
        found.append('this business was already emailed or opted out')
    if conn.execute("SELECT 1 FROM autosend_log WHERE owner_id=? AND (email=? OR business_key=? OR (?!='' AND domain=?))",(owner,email,business_key(p),domain,domain)).fetchone():
        found.append('auto-send already emailed this business')
    return list(dict.fromkeys(found))


def candidates(conn,owner):
    """CEO-passed first emails in batch order: one trade in one area at a time, 50 or fewer per batch (campaign.order)."""
    import campaign
    rows=conn.execute("""SELECT * FROM prospects WHERE owner_id=? AND stage='New' AND touches=0 AND ceo_status='ready' AND draft_body!=''
      AND draft_kind='first' AND email!='' AND replied_at='' ORDER BY score DESC,id LIMIT 500""",(owner,)).fetchall()
    return campaign.order(conn,owner,rows)[:50]


def tick(conn,owner,at=None,send=None):
    """Called by the worker loop. Handles opt-outs, then sends at most one email if every rule allows. Returns what it did."""
    try:process_optouts(conn,owner);conn.commit()
    except Exception:conn.rollback()
    at=at or now_local();reason=blocked(conn,owner,at)
    if reason:return dict(sent=False,reason=reason)
    s=lead_engine.settings(conn,owner)
    for p in candidates(conn,owner):
        wrong=problems(conn,owner,p,s)
        if wrong:
            # Never picked again; the reason is saved on the business.
            conn.execute("UPDATE prospects SET ceo_status='held',ceo_note=? WHERE id=?",('Not auto-sent: '+'; '.join(wrong)[:280],p['id']));conn.commit()
            continue
        return _send(conn,owner,p,at,send or gmail_agent.send_outreach)
    return dict(sent=False,reason='No CEO-passed first emails waiting.')


def _send(conn,owner,p,at,send):
    email=p['email'].casefold();day=at.astimezone(TZ).date()
    # Claim first, so a crash or retry can never email this business again.
    if conn.in_transaction:conn.commit()
    conn.execute('BEGIN IMMEDIATE')
    try:
        log_id=conn.execute('INSERT INTO autosend_log(owner_id,prospect_id,business,email,business_key,domain,local_date,sent_at,subject,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
          (owner,p['id'],p['name'],email,business_key(p),domain_of(email),day.isoformat(),stamp(),p['draft_subject'],'Sending')).lastrowid
    except Exception:
        conn.rollback();return dict(sent=False,reason='Already claimed.')
    _save(conn,owner,last_attempt=time.time());conn.commit()
    try:
        gmail_id=send(conn,owner,email,p['draft_subject'],p['draft_body'])
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE autosend_log SET status='Outcome unknown' WHERE id=?",(log_id,))
        conn.execute("UPDATE prospects SET ceo_status='held',ceo_note='Auto-send could not confirm this one. Check Gmail Sent before doing anything.' WHERE id=?",(p['id'],))
        note='Switched itself off after a Gmail problem: '+(str(exc) if isinstance(exc,WorkflowError) else 'unexpected error')
        _save(conn,owner,enabled=0,changed_at=stamp(),note=note[:300]);audit(conn,'autosend_stopped',owner,{'log_id':log_id})
        log(conn,owner,'CEO auto-send stopped after a Gmail problem. Nothing was retried.');conn.commit()
        return dict(sent=False,reason=note)
    conn.execute("UPDATE autosend_log SET status='Sent',gmail_id=? WHERE id=?",(gmail_id,log_id))
    lead_engine.mark_sent(conn,owner,p,day)
    lead_engine.record(conn,owner,p,'auto_sent',p['draft_subject'])
    conn.commit()
    return dict(sent=True,reason='Sent to '+p['name']+'.')


def status(conn,owner):
    """Everything the Gmail page shows about auto-send."""
    s=settings(conn,owner);day=now_local().date()
    try:can=gmail_agent.can_send(conn,owner)
    except WorkflowError:can=False
    row=conn.execute('SELECT polling FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
    week=conn.execute("SELECT local_date,COUNT(*) n FROM autosend_log WHERE owner_id=? AND local_date>=? GROUP BY local_date ORDER BY local_date DESC",
      (owner,(day-timedelta(days=6)).isoformat())).fetchall()
    return dict(s,enabled=bool(s['enabled']),can_send=can,polling=bool(row and row['polling']),inbox_fresh=inbox_fresh(conn,owner),
      waiting=blocked(conn,owner) if s['enabled'] else '',sent_today=sent_today(conn,owner,day),daily_max=daily_cap(conn,owner,day),bounces=bounces_today(conn,owner,day),bounce_rate=round(bounce_rate(conn,owner,day)*100),
      today=[dict(r,time=_clock(r['sent_at'])) for r in conn.execute('SELECT * FROM autosend_log WHERE owner_id=? AND local_date=? ORDER BY id DESC',(owner,day.isoformat()))],
      week=week,ready=len(candidates(conn,owner)),
      optouts=conn.execute("SELECT l.*,p.name FROM prospect_log l JOIN prospects p ON p.id=l.prospect_id WHERE l.owner_id=? AND l.action='opted_out' ORDER BY l.id DESC LIMIT 10",(owner,)).fetchall())


def _clock(iso):
    try:return datetime.fromisoformat(iso).astimezone(TZ).strftime('%-I:%M %p')
    except ValueError:return ''


def switch(conn,owner,on,confirmed=False):
    if on:
        if not confirmed:raise WorkflowError('Tick the box to confirm you want AgencyOS to send CEO-passed first emails by itself.')
        if not gmail_agent.can_send(conn,owner):raise WorkflowError('Auto-send needs Gmail\'s send permission first: tick "Let AgencyOS send" and press Reconnect.')
        row=conn.execute('SELECT polling FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
        if not (row and row['polling']):raise WorkflowError('Turn on inbox checking first, so opt-out replies are seen.')
    _save(conn,owner,enabled=int(on),changed_at=stamp(),note='')
    if on:  # the team has to keep writing, or the CEO runs out of emails to send
        conn.execute('INSERT INTO night_shift_settings(owner_id,enabled) VALUES(?,1) ON CONFLICT(owner_id) DO UPDATE SET enabled=1',(owner,))
    audit(conn,'autosend_switched',owner,{'enabled':bool(on)})
    log(conn,owner,'CEO auto-send switched '+('on' if on else 'off')+'.')
    conn.commit()


def register(app,get_db,login_required):
    @app.post('/gmail/autosend')
    @login_required
    def gmail_autosend():
        on=request.form.get('enable')=='yes'
        switch(get_db(),session['user_id'],on,request.form.get('confirm')=='yes')
        flash('CEO auto-send is on. It sends every day from 6 am to 10 pm, up to today\'s safe number.' if on else 'CEO auto-send is off. Nothing will be sent by itself.','success')
        return redirect(url_for('ceo_live') if request.form.get('next')=='ceo' else url_for('gmail_home')+'#autosend')

"""The agent team: a real org chart that turns the night shift into checked drafts for the owner's yes or no.

17 roles: CEO, Chief of Staff, three division managers (Growth, Sales, Delivery) and twelve workers.

CEO           reviews every finished draft against the playbook and the owner's lessons, holds back bad ones,
              writes the morning brief and buzzes the owner's phone when drafts are ready.
Chief of Staff plans each night: how many map squares to sweep, how many drafts to write, and paces the AI budget.
Growth        Scout, Inspector, SEO Checker, Writer, Call Prepper and Designer find and draft.
Sales         Chaser, Reply Handler and Closer turn replies into yeses.
Delivery      Site Builder, Client Care and Bookkeeper keep clients happy and paying.

"Teaching" is real but simple: each agent has a written playbook, the owner can add lessons (plain-English rules
and words never to use), and every yes, edit and no is stored. The rules-only team obeys the lessons and the
owner's most common reasons for saying no; with Claude Haiku switched on, the Writer and CEO also read the
lessons and the emails the owner approved. Nothing here sends anything to a customer.
"""
import json
import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from flask import abort,flash,redirect,render_template,request,session,url_for,Response
from phase3_store import WorkflowError,stamp
from sales_store import log
import lead_engine
import playbook
import smart_writer
import sweep

TZ=ZoneInfo('Australia/Sydney')
# key, name, title, reports to, one-line job, playbook (the rules each one works to)
AGENTS=(
 ('ceo','CEO','Runs the agency','',
  'Checks every finished draft, holds back anything that breaks the rules, and puts the good ones in front of you.',
  ('Read every draft before Benji does. Nothing reaches him that breaks the playbook or his lessons.',
   'A draft must name the business, say who it is from, keep the "no thanks" opt-out and never promise results.',
   'If an AI draft fails, swap in the safe rules draft. If that fails too, hold it back and say why.',
   'Buzz Benji\'s phone when drafts are ready: at most three times a day, never before 7 am or after 9 pm.',
   'Every morning, write a short brief: what the team did, what needs Benji, and what is working.')),
 ('chief','Chief of Staff','Plans every night','ceo',
  'Decides how many map squares to sweep and drafts to write, and keeps the AI spend on budget.',
  ('Sweep Sydney first, square by square, then the other cities. Never more than the nightly limit.',
   'Only write as many new drafts as Benji can send: his daily draft limit minus what is already waiting.',
   'Spread the AI budget evenly over the month. If we are ahead of budget, the team uses the free rules until it catches up.',
   'Follow-ups that are due always come before new businesses.')),
 ('growth','Growth Manager','Runs the Growth team','chief',
  'Hands lead work to the six Growth workers and tracks who is getting yeses.',
  ('Best leads first: no website or a broken one, with a phone or email.',
   'Phone-only businesses go to the Call Prepper, email ones to the Writer.',
   'Track yes rates by trade and by channel, and push more of whatever is working.')),
 ('sales','Sales Manager','Turns replies into sales','chief',
  'Makes sure every follow-up goes out, every reply gets answered fast and every "yes" gets a proposal.',
  ('A lead who replies is the most valuable thing in the business: answer within the hour.',
   'Interested means: mock-up, proposal and price in front of them within a day.',
   'Stop chasing anyone who says no or asks to stop. Never contact "Do not contact".')),
 ('delivery','Delivery Manager','Keeps clients happy and paying','chief',
  'Runs the websites you are building, the monthly clients and the money coming in.',
  ('Every paying client hears from us at least once a month.',
   'Change requests get a drafted reply the same day.',
   'Chase overdue money politely, and only after checking the bank.')),
 ('scout','Scout','Finds businesses','growth',
  'Sweeps all of Australia for local businesses with no website listed, Sydney first, plus your saved search areas.',
  ('Sydney first, then every capital and big city, then regional towns in every state, then the rest of each state.',
   'Use free OpenStreetMap data only. Search slowly so the free service is never overloaded.',
   'Skip any business already in the list, and never re-add one marked "Do not contact".',
   '"No website listed" is not proof. Benji does a ten-second Google check before he sends.')),
 ('inspector','Inspector','Checks websites','growth',
  'Opens each business\'s homepage once and notes if it is down, not secure, not phone-friendly or out of date.',
  ('One look at the public homepage, like a visitor. No logging in, no forms, no hammering.',
   'Only report what was actually seen. Never guess.')),
 ('seo','SEO Checker','Checks how Google sees them','growth',
  'Looks for the simple Google and phone basics: a description, a main heading, tap-to-call, local business details.',
  ('SEO means "how easily Google finds and shows a business". Check the basics only.',
   'Give the Writer one plain-English line it can use, never jargon.')),
 ('writer','Writer','Drafts emails','growth',
  'Writes the first email and two follow-ups for each business, from the playbook and your lessons.',
  (playbook.VOICE,'Offer: '+playbook.OFFER+'.','Never mention prices in an email. Always keep the "no thanks" line.',
   'First email up to '+str(playbook.MAX_WORDS['first'])+' words; follow-ups shorter.')),
 ('caller','Call Prepper','Gets your calls ready','growth',
  'Builds the call sheet for businesses with only a phone number: opener, likely objections, best time to ring.',
  ('Calls only in legal hours: weekdays 9 am to 8 pm, Saturday 9 to 5, never Sunday or national holidays.',
   'Every call opens with who Benji is and why he is calling, in one breath.')),
 ('designer','Designer','Matches mock-ups','growth',
  'Picks the free mock-up for each business: the animated story for builders, landscapers and salons.',
  ('Builders get the blueprint-to-house story, landscapers the yard makeover, salons the cut-and-colour story.',
   'Everyone else gets the clean one-page mock-up with a big tap-to-call button.')),
 ('chaser','Chaser','Follows up','sales',
  'Drafts follow-up 1 and 2 on the right day, and stops when they reply or after the last one.',
  ('Follow up after 4 days, then 6 more, then stop. Short and friendly every time.',)),
 ('replier','Reply Handler','Answers replies','sales',
  'Spots when a lead writes back, stops their follow-ups, buzzes your phone and drafts your reply in Gmail.',
  ('Reply drafts only. Benji presses Send.','A reply means call them back within the hour.')),
 ('closer','Closer','Gets the yes','sales',
  'For every interested business: the mock-up, a proposal page and the right package, ready to send.',
  ('Lead with the mock-up, then one clear package and price. No pressure, no fake deadlines.',)),
 ('builder','Site Builder','Builds the websites','delivery',
  'Tracks every website you are building, from plan to live.',
  ('A client site is never published without Benji\'s OK and the client\'s OK.',)),
 ('carer','Client Care','Looks after monthly clients','delivery',
  'Drafts the monthly Google posts, review requests and replies to change requests.',
  ('Every monthly client gets their Google posts and a check-in every month.',)),
 ('bookkeeper','Bookkeeper','Gets you paid','delivery',
  'Makes invoices, watches what is due and drafts polite reminders for overdue ones.',
  ('Only mark something paid after Benji checks the bank.',)),
)
DIVISIONS=(('growth',('scout','inspector','seo','writer','caller','designer')),('sales',('chaser','replier','closer')),('delivery',('builder','carer','bookkeeper')))
NAMES={a[0]:a[1] for a in AGENTS}
WORKERS=tuple(k for _,keys in DIVISIONS for k in keys)
NO_REASONS={'too_long':'Too long','too_salesy':'Too salesy','wrong':'Got a fact wrong','not_me':'Does not sound like me','bad_fit':'Not a good business for us'}
LEARN_AFTER=3  # the same reason this many times in the last 20 no's becomes a standing rule


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS team_settings (
      owner_id INTEGER PRIMARY KEY, pings INTEGER NOT NULL DEFAULT 1, phone_url TEXT NOT NULL DEFAULT '',
      tiles_per_night INTEGER NOT NULL DEFAULT 60, all_australia INTEGER NOT NULL DEFAULT 1, daily_drafts INTEGER NOT NULL DEFAULT 25,
      ping_day TEXT NOT NULL DEFAULT '', pings_today INTEGER NOT NULL DEFAULT 0, last_ping_at TEXT NOT NULL DEFAULT '', last_ping_count INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS team_lessons (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, agent TEXT NOT NULL, lesson TEXT NOT NULL, avoid TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS team_feedback (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, agent TEXT NOT NULL, prospect_id INTEGER, trade TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL DEFAULT '', verdict TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
      original TEXT NOT NULL DEFAULT '', final TEXT NOT NULL DEFAULT '', edited INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS team_feedback_idx ON team_feedback(owner_id,agent,id);
    ''')
    sweep.migrate(conn)


def now_local():
    return datetime.now(TZ)


DEFAULTS=dict(pings=1,phone_url='',tiles_per_night=60,all_australia=1,daily_drafts=25,ping_day='',pings_today=0,last_ping_at='',last_ping_count=0)


def settings(conn,owner):
    row=conn.execute('SELECT * FROM team_settings WHERE owner_id=?',(owner,)).fetchone()
    return dict(row) if row else dict(DEFAULTS,owner_id=owner)


def _save(conn,owner,**values):
    s=settings(conn,owner);s.update(values);s['owner_id']=owner
    cols=list(DEFAULTS)
    conn.execute('INSERT OR REPLACE INTO team_settings(owner_id,'+','.join(cols)+') VALUES(?'+',?'*len(cols)+')',[owner]+[s[c] for c in cols])


# ---------- Teaching: lessons and feedback ----------

def lessons(conn,owner,agent=None):
    if agent:return conn.execute("SELECT * FROM team_lessons WHERE owner_id=? AND agent IN (?,'all') ORDER BY id",(owner,agent)).fetchall()
    return conn.execute('SELECT * FROM team_lessons WHERE owner_id=? ORDER BY id',(owner,)).fetchall()


def teach(conn,owner,agent,lesson,avoid=''):
    lesson=' '.join(lesson.split());avoid=', '.join(w.strip() for w in avoid.split(',') if w.strip())
    if agent not in NAMES and agent!='all':raise WorkflowError('Pick who you are teaching.')
    if not 3<=len(lesson)<=400 or len(avoid)>200:raise WorkflowError('Write the lesson in a sentence (up to 400 characters).')
    if len(lessons(conn,owner))>=60:raise WorkflowError('That is 60 lessons. Remove an old one first.')
    conn.execute('INSERT INTO team_lessons(owner_id,agent,lesson,avoid,created_at) VALUES(?,?,?,?,?)',(owner,agent,lesson,avoid,stamp()))


def avoid_words(conn,owner,agent='writer'):
    return [w.strip() for r in lessons(conn,owner,agent) for w in r['avoid'].split(',') if w.strip()]


def _text(pair):
    return (pair[0] or '')+'\n\n'+(pair[1] or '')


def feedback(conn,owner,p,verdict,original,final=None,reason=''):
    """Store the owner's yes (with any edits) or no on a draft. This is what the team learns from."""
    kind=p['draft_kind'] or smart_writer.current_kind(p)
    orig=_text(original) if original else '';fin=_text(final) if final else ''
    edited=int(bool(final) and ' '.join(orig.split())!=' '.join(fin.split()))
    conn.execute('INSERT INTO team_feedback(owner_id,agent,prospect_id,trade,kind,verdict,reason,source,original,final,edited,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      (owner,'caller' if kind=='call' else 'writer',p['id'],p['trade'],kind,verdict,reason,p['draft_source'] or 'rules',orig[:6000],fin[:6000],edited,stamp()))


def send_back(conn,owner,p,reason):
    """The owner said no to a draft. Bad fit: drop the business. Otherwise the Writer redoes it tonight."""
    if reason not in NO_REASONS:raise WorkflowError('Pick why it is a no.')
    feedback(conn,owner,p,'no',smart_writer.stored(p) or lead_engine.draft(p,lead_engine.settings(conn,owner)),reason=reason)
    if reason=='bad_fit':
        conn.execute("UPDATE prospects SET stage='Skipped',next_on='' WHERE id=?",(p['id'],));lead_engine.record(conn,owner,p,'skip','not a fit')
        return 'Dropped. The team learns which businesses you do not want.'
    conn.execute("UPDATE prospects SET draft_body='',draft_subject='',ceo_status='redo',ceo_note=? WHERE id=?",('You said: '+NO_REASONS[reason].lower(),p['id']))
    return 'Sent back. The Writer redoes it on the next shift with your note.'


def learned(conn,owner):
    """What the team has worked out from the owner's yeses, edits and no's."""
    rows=conn.execute("SELECT * FROM team_feedback WHERE owner_id=? AND agent='writer' ORDER BY id DESC LIMIT 40",(owner,)).fetchall()
    yes=[r for r in rows if r['verdict']=='yes'];no=[r for r in rows if r['verdict']=='no']
    reasons={}
    for r in no[:20]:reasons[r['reason']]=reasons.get(r['reason'],0)+1
    rules=[]
    if reasons.get('too_long',0)>=LEARN_AFTER:rules.append('Benji keeps saying drafts are too long. Keep first emails under 90 words.')
    if reasons.get('too_salesy',0)>=LEARN_AFTER:rules.append('Benji keeps saying drafts are too salesy. Sound like a neighbour, not an advert. No selling words.')
    if reasons.get('not_me',0)>=LEARN_AFTER:rules.append('Benji says drafts do not sound like him. Copy the style of the emails he approved below.')
    if reasons.get('wrong',0)>=LEARN_AFTER:rules.append('Benji caught wrong facts. Only say what the website check actually found.')
    bad_trades={}
    for r in no:
        if r['reason']=='bad_fit':bad_trades[r['trade']]=bad_trades.get(r['trade'],0)+1
    return dict(total=len(rows),yes=len(yes),no=len(no),edited=sum(r['edited'] for r in yes),reasons=reasons,rules=rules,
      short=reasons.get('too_long',0)>=LEARN_AFTER,rate=round(100*len(yes)/len(rows)) if rows else 0,
      bad_trades=sorted((t for t,n in bad_trades.items() if n>=LEARN_AFTER and t)),
      examples=[r for r in yes if r['edited']][:3])


def coaching(conn,owner,trade=''):
    """The Writer's memory for the AI: the owner's lessons, learned rules and emails he approved after editing."""
    parts=[]
    taught=[r['lesson'] for r in lessons(conn,owner,'writer')]
    if taught:parts.append('Benji\'s rules for you (follow them exactly):\n- '+'\n- '.join(taught))
    l=learned(conn,owner)
    if l['rules']:parts.append('Learned from Benji\'s feedback:\n- '+'\n- '.join(l['rules']))
    examples=sorted(l['examples'],key=lambda r:r['trade']!=trade)[:2]
    for r in examples:
        body=r['final']
        p=conn.execute('SELECT name FROM prospects WHERE id=?',(r['prospect_id'],)).fetchone()
        if p:body=body.replace(p['name'],'THEIR BUSINESS')
        parts.append('An email Benji approved after editing it (match this style, not the details):\n'+body[:1200])
    return '\n\n'.join(parts)[:4000]


# ---------- The CEO ----------

CEO_PROMPT=('You are the CEO of a one-person Australian web design agency, checking a cold email before the owner sees it. '
  'Reply OK if it is friendly, specific to this business, honest and short. Otherwise reply FIX: then one sentence on what to change. '
  'Only judge the email below.')


def _ask_ceo(prompt):
    return smart_writer._ask_haiku(prompt)


def ceo_review(conn,owner,ids,ask=None,write_ask=None):
    """Check each freshly drafted business. Returns counts of ready and held drafts."""
    s=lead_engine.settings(conn,owner);words=avoid_words(conn,owner);out=dict(ready=0,held=0,fixed=0)
    for pid in ids:
        p=conn.execute('SELECT * FROM prospects WHERE id=? AND owner_id=?',(pid,owner)).fetchone()
        if not p or not p['draft_body']:continue
        kind=p['draft_kind'] or smart_writer.current_kind(p)
        if kind=='call':
            conn.execute("UPDATE prospects SET ceo_status='ready',ceo_note='Call script checked' WHERE id=?",(pid,));out['ready']+=1;continue
        problems=playbook.review(p['draft_subject'],p['draft_body'],p,s,kind)+playbook.review_words(p['draft_subject'],p['draft_body'],words)
        note=''
        if not problems and p['draft_source']=='ai' and smart_writer.ai_status(conn,owner)['ready']:
            # A second opinion from the AI CEO on AI drafts only (rules drafts are fixed templates).
            try:
                text,tin,tout=(ask or _ask_ceo)(CEO_PROMPT+'\n\n'+coaching(conn,owner,p['trade'])+'\n\nSubject: '+p['draft_subject']+'\n'+p['draft_body'])
                smart_writer.record_usage(conn,owner,tin,tout)
                if text.strip().upper().startswith('FIX'):
                    note=text.split(':',1)[-1].strip()[:200]
                    smart_writer.write(conn,owner,p,s,ask=write_ask,coaching=coaching(conn,owner,p['trade'])+'\n\nThe CEO asked for this change: '+note,short=learned(conn,owner)['short'])
                    p=conn.execute('SELECT * FROM prospects WHERE id=?',(pid,)).fetchone();out['fixed']+=1
                    problems=playbook.review(p['draft_subject'],p['draft_body'],p,s,kind)+playbook.review_words(p['draft_subject'],p['draft_body'],words)
            except Exception:  # Offline or provider trouble: the rules check above still stands.
                pass
        if problems and p['draft_source']=='ai':
            subject,body=lead_engine.draft(p,s,kind,short=learned(conn,owner)['short'])
            conn.execute("UPDATE prospects SET draft_subject=?,draft_body=?,draft_source='rules' WHERE id=?",(subject,body,pid))
            problems=playbook.review(subject,body,p,s,kind)+playbook.review_words(subject,body,words)
            note='Swapped the AI draft for the safe version'
        if problems:
            conn.execute("UPDATE prospects SET ceo_status='held',ceo_note=? WHERE id=?",('Held back: '+'; '.join(problems)[:300],pid));out['held']+=1
        else:
            conn.execute("UPDATE prospects SET ceo_status='ready',ceo_note=? WHERE id=?",(note or 'Checked by the CEO',pid));out['ready']+=1
    return out


def plan(conn,owner):
    """The Chief of Staff's plan for tonight."""
    t=settings(conn,owner)
    waiting=conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND stage='New' AND draft_body!='' AND ceo_status='ready'",(owner,)).fetchone()[0]
    nxt=sweep.next_tiles(conn,owner,1,bool(t['all_australia']))
    return dict(tiles=max(0,min(200,t['tiles_per_night'])),drafts=max(0,min(60,t['daily_drafts']-waiting)),waiting=waiting,
      region=nxt[0][0][1] if nxt else '',writer=smart_writer.ai_status(conn,owner),all_australia=bool(t['all_australia']))


def ready_count(conn,owner):
    """Drafts and follow-ups waiting for the owner's yes or no."""
    return sum(1 for p in lead_engine.queue(conn,owner,limit=200) if p['stage'] in ('New','Contacted'))


def notify(conn,owner,at=None,send=None):
    """Buzz the owner's phone when new drafts are ready. At most 3 a day, 7 am to 9 pm, only when the pile grows."""
    import pitch
    at=at or now_local();t=settings(conn,owner);send=send or pitch.ping
    if not t['pings'] or not 7<=at.hour<21:return False
    day=at.date().isoformat();today_n=t['pings_today'] if t['ping_day']==day else 0
    if today_n>=3:return False
    if t['last_ping_at'] and t['ping_day']==day and at-datetime.fromisoformat(t['last_ping_at'])<timedelta(hours=3):return False
    n=ready_count(conn,owner)
    if not n or (t['ping_day']==day and n<=t['last_ping_count']):return False
    click=(t['phone_url'].rstrip('/')+'/m') if t['phone_url'] else ''
    if not send(conn,owner,'AgencyOS: '+str(n)+' ready for your yes or no','The CEO checked them. Tap to open.' if click else 'The CEO checked them. Open AgencyOS on your Mac.',click):return False
    _save(conn,owner,ping_day=day,pings_today=today_n+1,last_ping_at=at.isoformat(),last_ping_count=n);conn.commit()
    return True


def brief(conn,owner,on=None):
    """The CEO's morning brief, in plain sentences, from local records only."""
    on=on or lead_engine.today()
    import night_shift
    last=night_shift.last_run(conn,owner);l=learned(conn,owner);c=lead_engine.counts(conn,owner,on)
    lines=[]
    if last:
        k=last['counts']
        lines.append('Last shift ('+last['local_date']+'): the team found '+str(k.get('found',0)+k.get('swept',0))+' businesses, checked '+str(k.get('checked',0))+
          ' websites and wrote '+str(k.get('drafts',0))+' drafts. I passed '+str(k.get('ceo_ready',0))+(' and held back '+str(k['ceo_held']) if k.get('ceo_held') else '')+'.')
    else:lines.append('No shift has run yet. The first one runs after 2 am while AgencyOS is open, or press "Run a shift now".')
    n=ready_count(conn,owner)
    lines.append(str(n)+' waiting for your yes or no.' if n else 'Nothing is waiting for you right now.')
    if c['interested']:lines.append(str(c['interested'])+' interested: send their mock-up today, that is where the money is.')
    if l['total']:lines.append('You have said yes to '+str(l['rate'])+'% of drafts'+(', and edited '+str(l['edited'])+' of them' if l['edited'] else '')+'.'+(' Standing rules learned: '+str(len(l['rules']))+'.' if l['rules'] else ''))
    return lines


# ---------- Airtasker (inside its rules) ----------

CONTACT=re.compile(r'(https?://|www\.|\.com|\.au\b|@|\b0\d[\d ]{7,}\b|\+61)',re.I)


def airtasker_quote(task,s):
    """A quote Benji pastes into Airtasker himself. Airtasker bans contact details before an offer is accepted."""
    task=' '.join(task.split())[:1500]
    me=s['name'].split()[0]
    words=set(re.findall(r'[a-z]+',task.casefold()))
    what='an online shop' if words&{'shopify','shop','store','ecommerce','products'} else 'a booking website' if words&{'booking','bookings','appointments','salon'} else 'a website'
    return ('Hi, I am '+me+', a local web designer. I build '+what+' that looks sharp on phones, loads fast and has a big tap-to-call button.\n\n'
      'For your task I would: 1) make you a free one-page mock-up first so you can see the look before you commit, '
      '2) build the full site once you are happy, 3) set up your Google listing basics so people find you.\n\n'
      'Happy to answer any questions here on Airtasker.')


def airtasker_problems(text):
    return ['remove contact details or links (Airtasker rule until an offer is accepted)'] if CONTACT.search(text) else []


# ---------- Scorecards for the Team page ----------

def scorecards(conn,owner):
    def n(sql,args=()):return conn.execute(sql,(owner,)+args).fetchone()[0]
    l=learned(conn,owner);c=lead_engine.counts(conn,owner)
    seo=0
    for r in conn.execute("SELECT site_check FROM prospects WHERE owner_id=? AND site_check!=''",(owner,)):
        try:seo+=bool(json.loads(r['site_check']).get('seo'))
        except ValueError:pass
    stories=tuple(t for t in lead_engine.TRADES if playbook.story_for(t))
    t=settings(conn,owner);prog=sweep.progress(conn,owner,bool(t['all_australia']))
    total=sum(r['total'] for r in prog);done=sum(r['done'] for r in prog)
    import client_plans
    plans=client_plans.summary(conn,owner)
    projects=conn.execute("SELECT COUNT(*) FROM projects WHERE status IN ('Planning','In progress','Review')").fetchone()[0]
    gmail_drafts=n("SELECT COUNT(*) FROM gmail_drafts WHERE owner_id=? AND status='Needs review'")
    overdue=n("SELECT COUNT(*) FROM bills WHERE owner_id=? AND status NOT IN ('Paid','Cancelled','Void') AND due_on<?",(lead_engine.today().isoformat(),))
    return dict(
      ceo=dict(big=n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND ceo_status='ready' AND stage='New'"),label='drafts passed, waiting for you',
               small=str(n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND ceo_status='held'"))+' held back · '+str(n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND ceo_status='redo'"))+' sent back by you'),
      chief=dict(big=t['daily_drafts'],label='drafts a day, max',small=str(t['tiles_per_night'])+' map searches a night'),
      growth=dict(big=c['contacted_today'],label='contacted today',small='target '+str(c['target'])+' a day'),
      sales=dict(big=c['interested'],label='interested right now',small=str(c['customers'])+' became customers'),
      delivery=dict(big=plans['clients'],label='monthly clients',small='A$'+format(plans['monthly_cents']/100,',.0f')+' a month'),
      scout=dict(big=n('SELECT COUNT(*) FROM prospects WHERE owner_id=?'),label='businesses found',small=str(done)+' of '+str(total)+' map searches across Australia'),
      chaser=dict(big=c['follow_ups'],label='follow-ups due today',small=str(c['waiting'])+' waiting for a reply'),
      replier=dict(big=n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND replied_at!=''"),label='leads who replied',small=str(gmail_drafts)+' reply drafts in Gmail to check'),
      closer=dict(big=c['interested'],label='proposals to send',small='mock-up + proposal + package'),
      builder=dict(big=projects,label='websites in progress',small='nothing goes live without your OK'),
      carer=dict(big=plans['requests']+plans['posts'],label='client jobs drafted',small=str(plans['requests'])+' change requests · '+str(plans['posts'])+' Google posts'),
      bookkeeper=dict(big=overdue,label='invoices overdue',small=str(plans['overdue'])+' monthly payments overdue'),
      inspector=dict(big=n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND checked_at!=''"),label='websites checked',small=str(n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND website='' AND facebook=''"))+' with no website listed'),
      seo=dict(big=seo,label='sites with Google gaps',small='used in the Writer\'s notes'),
      writer=dict(big=l['rate'] if l['total'] else '–',label='% of drafts you said yes to',small=str(l['yes'])+' yes · '+str(l['no'])+' no · '+str(l['edited'])+' edited'),
      caller=dict(big=n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND stage='New' AND email='' AND phone!='' AND score>=50"),label='phone-only leads ready',small='on the Calls page'),
      designer=dict(big=n('SELECT COUNT(*) FROM prospects WHERE owner_id=? AND trade IN ('+','.join('?'*len(stories))+')',stories) if stories else 0,label='get an animated story mock-up',small='others get the one-page mock-up'),
    ),prog


def org(conn,owner):
    cards,prog=scorecards(conn,owner)
    taught={}
    for r in lessons(conn,owner):taught.setdefault(r['agent'],[]).append(r)
    people=[dict(key=k,name=name,title=title,boss=boss,job=job,playbook=rules,card=cards[k],lessons=taught.get(k,[])) for k,name,title,boss,job,rules in AGENTS]
    by={p['key']:p for p in people}
    divisions=[dict(manager=by[m],workers=[by[k] for k in keys]) for m,keys in DIVISIONS]
    t=settings(conn,owner)
    return dict(people=by,workers=[p for p in people if p['key'] in WORKERS],divisions=divisions,progress=prog,
      states=sweep.by_state(conn,owner,bool(t['all_australia'])),general=taught.get('all',[]))


# ---------- Phone ----------

def phone_host_file():
    import os
    from pathlib import Path
    base=os.environ.get('AGENCYOS_PRIVATE_DATA','')
    return Path(base)/'phone_host' if base else None


def clean_phone_url(value):
    """Only a private Tailscale address (https://name.something.ts.net) is accepted, never a public one."""
    value=value.strip().rstrip('/')
    if not value:return ''
    m=re.fullmatch(r'https://([a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net)',value,re.I)
    if not m:raise WorkflowError('Paste the private Tailscale address, like https://benjis-laptop.tail1234.ts.net')
    return 'https://'+m.group(1).casefold()


MANIFEST=dict(name='AgencyOS',short_name='AgencyOS',start_url='/m',scope='/',display='standalone',background_color='#111111',theme_color='#111111',
  icons=[dict(src='/static/icons/icon-192.png',sizes='192x192',type='image/png'),dict(src='/static/icons/icon-512.png',sizes='512x512',type='image/png')])
SERVICE_WORKER="""// AgencyOS on the home screen. Nothing is cached: your business data stays on the Mac.
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>self.clients.claim());
self.addEventListener('fetch',()=>{});
"""


def register(app,get_db,login_required):
    def page(quote='',task=''):
        conn=get_db();owner=session['user_id']
        return render_template('team.html',org=org(conn,owner),plan=plan(conn,owner),brief=brief(conn,owner),learned=learned(conn,owner),
          settings=settings(conn,owner),names=NAMES,reasons=NO_REASONS,ntfy=bool(lead_engine.settings(conn,owner).get('ntfy_topic')),
          quote=quote,task=task)

    @app.get('/team',strict_slashes=False)
    @login_required
    def team_home():
        return page()

    @app.post('/team/teach')
    @login_required
    def team_teach():
        conn=get_db();owner=session['user_id'];agent=request.form.get('agent','')
        teach(conn,owner,agent,request.form.get('lesson',''),request.form.get('avoid',''));conn.commit()
        flash('Taught. '+('Everyone' if agent=='all' else NAMES[agent])+' uses it from the next shift.','success')
        return redirect(url_for('team_home')+'#teach')

    @app.post('/team/lessons/<int:lesson_id>/remove')
    @login_required
    def team_forget(lesson_id):
        conn=get_db();conn.execute('DELETE FROM team_lessons WHERE id=? AND owner_id=?',(lesson_id,session['user_id']));conn.commit()
        flash('Lesson removed.','success');return redirect(url_for('team_home')+'#teach')

    @app.post('/team/settings')
    @login_required
    def team_settings():
        conn=get_db();owner=session['user_id'];f=request.form
        tiles=f.get('tiles_per_night',type=int);drafts=f.get('daily_drafts',type=int)
        if tiles is None or not 0<=tiles<=200 or drafts is None or not 0<=drafts<=60:raise WorkflowError('Map squares: 0 to 200 a night. Drafts: 0 to 60 a day.')
        url=clean_phone_url(f.get('phone_url',''))
        _save(conn,owner,tiles_per_night=tiles,daily_drafts=drafts,all_australia=int(f.get('all_australia')=='1'),pings=int(f.get('pings')=='1'),phone_url=url)
        conn.commit()
        path=phone_host_file()
        if path and url:
            host=url.split('//',1)[1];path.write_text(host)
            hosts=app.config.get('TRUSTED_HOSTS')
            if isinstance(hosts,list) and host not in hosts:hosts.append(host)
        flash('Saved.','success');return redirect(url_for('team_home')+'#settings')

    @app.post('/team/airtasker')
    @login_required
    def team_airtasker():
        conn=get_db();task=request.form.get('task','')
        if len(task.split())<3:raise WorkflowError('Paste the Airtasker task description first.')
        return page(quote=airtasker_quote(task,lead_engine.settings(conn,session['user_id'])),task=task[:1500])

    @app.get('/m',strict_slashes=False)
    @login_required
    def phone_queue():
        conn=get_db();owner=session['user_id'];s=lead_engine.settings(conn,owner)
        cards=[lead_engine.card(p,s) for p in lead_engine.queue(conn,owner,limit=30)]
        return render_template('phone.html',cards=cards,brief=brief(conn,owner),reasons=NO_REASONS)

    @app.get('/manifest.webmanifest')
    def web_manifest():
        return Response(json.dumps(MANIFEST),mimetype='application/manifest+json')

    @app.get('/sw.js')
    def service_worker():
        return Response(SERVICE_WORKER,mimetype='text/javascript',headers={'Service-Worker-Allowed':'/'})

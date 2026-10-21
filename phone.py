"""Call Mode: the phone side of Find customers.

A daily call sheet of the best leads with a 30 second opener written around the real problem on
their website, one-tap answers to the usual objections, one-tap call logging, the "one-two"
follow-up (voicemail, email and text drafts after a missed call), lead grades A/B/C and a daily
scoreboard. Rule-based and local. Nothing is dialled, sent or texted from here: the owner calls
from his own phone and sends from his own email or Messages.
"""
import json
import re
from datetime import date,datetime,timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo
from flask import flash,redirect,render_template,request,session,url_for
from phase3_store import WorkflowError,stamp
import lead_engine

TZ=ZoneInfo('Australia/Sydney')
CALL_TARGET=5
SHEET_SIZE=10
# Trades by what a website is usually worth to them: big jobs first.
TRADE_VALUE={
 'Builders':20,'Roofers':20,'Gardeners and landscapers':18,'Electricians':16,'Plumbers':16,'Carpenters':15,'Painters':14,
 'Dentists':15,'Physios':13,'Beauty salons':13,'Hairdressers and barbers':12,'Mechanics':11,'Vets':11,'Tattoo studios':10,
 'Gyms':10,'Florists':8,'Restaurants':7,'Cafes':5,'Bakeries':5,
}
OUTCOMES={
 'no_answer':'No answer','voicemail':'Left a voicemail','callback':'Call back later','interested':'Interested',
 'not_interested':'Not interested','do_not_contact':'Do not call again','wrong_number':'Wrong number',
}
CONVERSATION=('callback','interested','not_interested','do_not_contact')
# The things tradies say on a cold call, and a calm answer for each. Short enough to read mid-call.
OBJECTIONS=(
 ('word','"I get all my work from word of mouth."','That is the best kind of work. These days, when someone gets your name from a mate, the first thing they do is look you up on their phone. The site just makes sure that check goes your way. That is why the mock-up is free, so you can judge it yourself.'),
 ('price','"How much is it?" / "Too expensive."','Sites start at A$800, then A$69 a month for hosting, security and small changes, with no lock-in, so you can stop any month. One extra job usually pays for the year. And the mock-up costs nothing, so you see it before you spend a cent.'),
 ('email','"Just send me an email."','Happy to. What is the best email? I will send it with a free preview of your new site already made, so it is worth opening. Can I give you a quick call Thursday to hear what you think?'),
 ('have','"I already have a website."','Good on you. I had a look and {problem} That is an easy fix. Would you like to see a free mock-up of how it could look next to what you have now?'),
 ('busy','"I\'m flat out, mate."','No worries, I will be quick. When is better, first thing tomorrow or after 4? I will have the free mock-up ready so it only takes two minutes.'),
 ('who','"Who are you? How did you get my number?"','I am {me}, a local web designer. Your number is listed publicly for {name}. I look at local businesses whose site is missing or not working on phones and offer a free mock-up. If you would rather I did not call again, I will take you off my list right now.'),
 ('later','"Call me back later."','Sure. What time suits, and is this the best number? I will put it in my calendar and have the mock-up ready.'),
 ('facebook','"I just use Facebook."','Facebook is great for regulars. New customers searching Google often cannot see it properly unless they log in, and it does not show up well in searches. A simple site sits next to your Facebook and points people to you. Want to see a free mock-up?'),
)


def now():
    return datetime.now(TZ)


def _easter(year):
    a=year%19;b,c=divmod(year,100);d,e=divmod(b,4);f=(b+8)//25;g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30;i,k=divmod(c,4);l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
    month,day=divmod(h+l-7*m+114,31)
    return date(year,month,day+1)


def national_holidays(year):
    easter=_easter(year)
    return {date(year,1,1),date(year,1,26),easter-timedelta(days=2),easter+timedelta(days=1),date(year,4,25),date(year,12,25),date(year,12,26)}


def calling_window(at=None):
    """Australian telemarketing hours: weekdays 9 am to 8 pm, Saturday 9 am to 5 pm, never Sunday or a national public holiday."""
    at=at or now()
    if at.weekday()==6 or at.date() in national_holidays(at.year):return False,'Do not call today: no telemarketing calls on Sundays or national public holidays.'
    close=17 if at.weekday()==5 else 20
    if at.hour<9:return False,'Too early. Calls can start at 9 am.'
    if at.hour>=close:return False,'Too late to call today. Calls stop at '+('5 pm on Saturdays.' if close==17 else '8 pm on weekdays.')
    return True,'Good time to call. You can call until '+('5 pm' if close==17 else '8 pm')+' today.'


def grade(p):
    """A, B or C: how likely this business is to pay for a website, from what we know."""
    points=lead_engine.REASONS.get(p['reason'],(50,''))[0]*0.6+TRADE_VALUE.get(p['trade'],9)
    points+=8 if p['phone'] else 0
    points+=4 if p['email'] else 0
    if p['stage'] in ('Interested',):points+=30
    return 'A' if points>=72 else 'B' if points>=58 else 'C'


def opener(p,s):
    """A 30 second opener built on the real problem with their site."""
    me=s['name'].split()[0]
    lines=['Hi, is that '+p['name']+'? Good, I will be quick. My name is '+me+', I am a local web designer'+(' in '+s['area'] if s['area'] else '')+'.',
      lead_engine.problem_line(p),
      lead_engine.why_it_matters(p),
      'I have already started a free mock-up of what a new site could look like for '+p['name']+'. No cost, no catch. Can I send it to you to have a look?']
    return lines


def objections(p,s):
    problem=lead_engine.problem_line(p)
    if problem.startswith('I had a look at') and ' and ' in problem:problem='it '+problem.split(' and ',1)[1]
    elif problem.startswith('I had a look at'):problem='there are a few quick wins.'
    else:problem='I could not find it when I searched, so customers probably cannot either.'
    return [(key,said,answer.format(problem=problem,me=s['name'].split()[0],name=p['name'])) for key,said,answer in OBJECTIONS]


def one_two(p,s,preview=''):
    """After a missed call: a voicemail script, a "just tried you" email and a text. The owner sends them himself."""
    me=s['name'].split()[0];phone=s['phone'] or 'this number'
    look=('Here is a preview I made for you: '+preview) if preview else 'I have made you a free mock-up of a new site and would love to show you.'
    voicemail=('Hi, it is '+me+', a local web designer. I had a look at '+p['name']+' online and made you a free mock-up of a new website. '
      'No cost and no obligation. Give me a call back on '+phone+' or reply to the text I am about to send. Thanks, bye.')
    subject='Just tried calling you'
    body=('Hi '+p['name']+' team,\n\nI just tried giving you a call. '+lead_engine.problem_line(p)+' '+look+'\n\n'
      'If it is easier, reply here or call me on '+phone+'.\n\nCheers,\n'+s['name']+'\n'+s['business']+'\n'+s['email']+('\n'+s['phone'] if s['phone'] else '')+
      '\n\nIf you would rather not hear from me, just reply "no thanks" and I will not contact you again.')
    text=('Hi, '+me+' here ('+s['business']+'). Just tried calling. '+look+' Call or text me back any time. Reply STOP and I will not text again.')
    tel=re.sub(r'[^0-9+]','',p['phone'])
    return dict(voicemail=voicemail,subject=subject,body=body,text=text,
      sms='sms:'+tel+'?&body='+quote(text) if tel else '',
      mailto=lead_engine.mailto(p,subject,body) if p['email'] else '')


def sheet(conn,owner,on=None,limit=SHEET_SIZE):
    """Today's calls: call-backs due first, then interested, then the best A and B leads with a phone number."""
    iso=(on or lead_engine.today()).isoformat()
    rows=conn.execute("""SELECT * FROM prospects WHERE owner_id=? AND phone!='' AND stage IN ('New','Approved','Contacted','Interested')
        AND (next_on='' OR next_on<=?) ORDER BY id""",(owner,iso)).fetchall()
    called={r['prospect_id']:r for r in conn.execute("SELECT prospect_id,MAX(on_date) last_on,COUNT(*) n FROM prospect_log WHERE owner_id=? AND action='called' GROUP BY prospect_id",(owner,))}
    def rank(p):
        g=grade(p);callback=p['stage']=='Contacted' and p['id'] in called
        return (0 if callback else 1 if p['stage']=='Interested' else 2,'ABC'.index(g),-p['score'],p['id'])
    picked=[p for p in sorted(rows,key=rank) if grade(p)!='C' or p['id'] in called][:limit]
    return [dict(p,grade=grade(p),calls=called[p['id']]['n'] if p['id'] in called else 0) for p in picked]


def log_call(conn,owner,p,outcome,callback_on=None,note=''):
    on=lead_engine.today()
    if outcome not in OUTCOMES:raise WorkflowError('Pick how the call went.')
    touches=p['touches']+1
    if outcome in ('no_answer','voicemail'):
        stage='Contacted' if touches<5 else 'No reply'
        next_on=(on+timedelta(days=2 if outcome=='no_answer' else 3)).isoformat() if stage=='Contacted' else ''
    elif outcome=='callback':
        if not callback_on or callback_on<on:raise WorkflowError('Pick the day to call them back.')
        stage,next_on='Contacted',callback_on.isoformat()
    else:
        stage={'interested':'Interested','not_interested':'Not interested','do_not_contact':'Do not contact','wrong_number':'Skipped'}[outcome];next_on=''
    conn.execute('UPDATE prospects SET stage=?,touches=?,last_contact_on=?,next_on=?,notes=CASE WHEN ?!=\'\' THEN trim(notes||char(10)||?) ELSE notes END WHERE id=?',
      (stage,touches,on.isoformat(),next_on,note,on.isoformat()+': '+note,p['id']))
    lead_engine.record(conn,owner,p,'called',outcome)
    return stage


def scoreboard(conn,owner,on=None):
    on=on or lead_engine.today();iso=on.isoformat()
    def day_counts(d):
        rows=conn.execute("SELECT action,detail FROM prospect_log WHERE owner_id=? AND on_date=?",(owner,d)).fetchall()
        calls=sum(1 for r in rows if r['action']=='called');talks=sum(1 for r in rows if r['action']=='called' and r['detail'] in CONVERSATION)
        sent=sum(1 for r in rows if r['action']=='sent');return calls,talks,sent
    calls,talks,sent=day_counts(iso)
    s=lead_engine.settings(conn,owner);email_target=s['daily_target'];call_target=s.get('call_target') or CALL_TARGET
    streak=0;d=on
    if calls<call_target or sent<email_target:d=d-timedelta(days=1)
    for _ in range(120):
        if d.weekday()>=5:d-=timedelta(days=1);continue
        c,_t,e=day_counts(d.isoformat())
        if c>=call_target and e>=email_target:streak+=1;d-=timedelta(days=1)
        else:break
    week=(on-timedelta(days=on.weekday())).isoformat()
    def n(sql,args):return conn.execute(sql,args).fetchone()[0]
    mockups=n("SELECT COUNT(*) FROM prospect_log WHERE owner_id=? AND on_date>=? AND action='interested'",(owner,week))+n("SELECT COUNT(*) FROM prospect_log WHERE owner_id=? AND on_date>=? AND action='called' AND detail='interested'",(owner,week))
    deals=n("SELECT COUNT(*) FROM prospect_log WHERE owner_id=? AND on_date>=? AND action='customer'",(owner,week))
    try:
        import getpaid
        money=getpaid.paid_cents(conn,owner,since=on.replace(day=1))
    except Exception:
        money=0
    return dict(calls=calls,call_target=call_target,talks=talks,sent=sent,email_target=email_target,streak=streak,
      interested_week=mockups,deals_week=deals,money_month=money,done=calls>=call_target and sent>=email_target)


def learn(conn,owner):
    """What is working: replies and yeses by trade, by channel and by first-email subject line."""
    rows=conn.execute("SELECT * FROM prospects WHERE owner_id=? AND touches>0",(owner,)).fetchall()
    def bucket(key):
        out={}
        for p in rows:
            k=key(p)
            if not k:continue
            b=out.setdefault(k,dict(name=k,tried=0,yes=0))
            b['tried']+=1;b['yes']+=1 if p['stage'] in ('Interested','Customer') else 0
        return sorted([dict(b,rate=round(100*b['yes']/b['tried'])) for b in out.values()],key=lambda b:(-b['rate'],-b['tried']))
    called={r[0] for r in conn.execute("SELECT DISTINCT prospect_id FROM prospect_log WHERE owner_id=? AND action='called'",(owner,))}
    return dict(trades=bucket(lambda p:p['trade'] or 'Other'),
      channels=bucket(lambda p:'Phone' if p['id'] in called else 'Email'),
      subjects=bucket(lambda p:(p['variant'] if 'variant' in p.keys() else '') or ''))


def register(app,get_db,login_required):
    @app.context_processor
    def _scoreboard_helper():
        def home_scoreboard():
            if not session.get('user_id'):return None
            try:return scoreboard(get_db(),session['user_id'])
            except Exception:return None
        return dict(home_scoreboard=home_scoreboard)

    @app.get('/calls',strict_slashes=False)
    @login_required
    def calls_home():
        conn=get_db();owner=session['user_id'];s=lead_engine.settings(conn,owner)
        import pitch
        cards=[];rows=sheet(conn,owner);just=request.args.get('just',type=int)
        if just and all(r['id']!=just for r in rows):
            extra=conn.execute('SELECT * FROM prospects WHERE id=? AND owner_id=?',(just,owner)).fetchone()
            if extra:rows=[dict(extra,grade=grade(extra),calls=0)]+rows
        for p in rows:
            preview=pitch.preview_url(conn,owner,p['id'])
            cards.append(dict(p,opener=opener(p,s),objections=objections(p,s),kit=one_two(p,s,preview),preview=preview,
              why=lead_engine.REASONS[p['reason']][1],mockup_url=pitch.mockup_url(p),tel=re.sub(r'[^0-9+]','',p['phone'])))
        ok,window=calling_window()
        return render_template('calls.html',cards=cards,board=scoreboard(conn,owner),ok=ok,window=window,outcomes=OUTCOMES,
          learn=learn(conn,owner),settings=s,just=just)

    @app.post('/calls/<int:prospect_id>/log')
    @login_required
    def calls_log(prospect_id):
        conn=get_db();owner=session['user_id'];p=lead_engine.prospect_for(conn,owner,prospect_id)
        outcome=request.form.get('outcome','');when=request.form.get('callback_on','')
        try:callback_on=date.fromisoformat(when) if when else None
        except ValueError:raise WorkflowError('Pick the day to call them back.') from None
        stage=log_call(conn,owner,p,outcome,callback_on,' '.join(request.form.get('note','').split())[:300])
        conn.commit()
        message={'Interested':'Get in. Their mock-up and proposal are one tap away on Find customers.','Do not contact':'Done. They will never be contacted or re-added.'}.get(stage,'Call logged.')
        if outcome in ('no_answer','voicemail'):message='Logged. Send the one-two now: the text and email are ready on their card.'
        flash(message,'success')
        return redirect(url_for('calls_home',just=p['id'] if outcome in ('no_answer','voicemail') else None)+'#c'+str(p['id']))

    @app.post('/calls/settings')
    @login_required
    def calls_settings():
        conn=get_db();owner=session['user_id'];target=request.form.get('call_target',type=int)
        if target not in range(1,51):raise WorkflowError('Pick a daily call target from 1 to 50.')
        s=lead_engine.settings(conn,owner)
        conn.execute('INSERT OR REPLACE INTO prospect_settings(owner_id,name,business,email,phone,area,daily_target,call_target) VALUES(?,?,?,?,?,?,?,?)',
          (owner,s['name'],s['business'],s['email'],s['phone'],s['area'],s['daily_target'],target))
        conn.commit();flash('Saved. Daily call target is '+str(target)+'.','success');return redirect(url_for('calls_home'))


def migrate(conn):
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospect_settings)')}
    if 'call_target' not in columns:
        conn.execute('ALTER TABLE prospect_settings ADD COLUMN call_target INTEGER NOT NULL DEFAULT '+str(CALL_TARGET))
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospects)')}
    if 'variant' not in columns:
        conn.execute("ALTER TABLE prospects ADD COLUMN variant TEXT NOT NULL DEFAULT ''")
    if 'replied_at' not in columns:
        conn.execute("ALTER TABLE prospects ADD COLUMN replied_at TEXT NOT NULL DEFAULT ''")
    if 'referred_by' not in columns:
        conn.execute('ALTER TABLE prospects ADD COLUMN referred_by INTEGER')

"""Monthly plan clients and their change requests. Owner-recorded only: nothing is charged, emailed or published."""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from flask import flash,redirect,render_template,request,session,url_for
from phase3_store import WorkflowError,stamp
from sales_store import log

# No lock-in: month to month, paid in advance, 30 days' notice. Yearly prepay = 10 months.
PLANS={
 'Care':dict(monthly_cents=6900,yearly_cents=69000,allowance=5,days=2),
 'Autopilot':dict(monthly_cents=14900,yearly_cents=149000,allowance=None,days=1),
}
PROFILE_CARE_CENTS=4900  # Google Profile Care add-on: two Google Business posts a month plus review requests
NOTICE_DAYS=30
SOURCES=('email','website chat','phone','text')


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS plan_clients (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, client_name TEXT NOT NULL, contact_email TEXT NOT NULL DEFAULT '',
      plan TEXT NOT NULL CHECK(plan IN ('Care','Autopilot')), billing TEXT NOT NULL CHECK(billing IN ('monthly','yearly')),
      started_on TEXT NOT NULL, next_due_on TEXT NOT NULL, ends_on TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS plan_payments (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, client_id INTEGER NOT NULL REFERENCES plan_clients(id),
      amount_cents INTEGER NOT NULL CHECK(amount_cents>0), bank_reference TEXT NOT NULL, received_on TEXT NOT NULL,
      recorded_at TEXT NOT NULL, UNIQUE(owner_id,bank_reference));
    CREATE TABLE IF NOT EXISTS plan_requests (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, client_id INTEGER NOT NULL REFERENCES plan_clients(id),
      source TEXT NOT NULL, request TEXT NOT NULL, size TEXT NOT NULL CHECK(size IN ('small','quote')),
      status TEXT NOT NULL DEFAULT 'New' CHECK(status IN ('New','Approved','Done')), reply TEXT NOT NULL,
      created_at TEXT NOT NULL, done_at TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS profile_posts (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, client_id INTEGER NOT NULL REFERENCES plan_clients(id), month TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('post','review')), slot INTEGER NOT NULL, text TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'New' CHECK(status IN ('New','Approved','Skipped')), created_at TEXT NOT NULL,
      UNIQUE(client_id,month,kind,slot));
    ''')
    if 'profile_care' not in {r[1] for r in conn.execute('PRAGMA table_info(plan_clients)')}:
        conn.execute('ALTER TABLE plan_clients ADD COLUMN profile_care INTEGER NOT NULL DEFAULT 0')


def today():
    return datetime.now(ZoneInfo('Australia/Sydney')).date()


def add_months(day,months):
    y,m=divmod(day.month-1+months,12);y+=day.year;m+=1
    for d in (day.day,30,29,28):
        try:return date(y,m,d)
        except ValueError:continue


def state(client,on=None):
    on=on or today()
    if not client['ends_on']:return 'Active'
    return 'Ended' if date.fromisoformat(client['ends_on'])<on else 'Cancelling'


def monthly_value(client):
    """What a client is worth per month; yearly prepay is spread over 12 months."""
    plan=PLANS[client['plan']]
    base=plan['monthly_cents'] if client['billing']=='monthly' else round(plan['yearly_cents']/12)
    return base+(PROFILE_CARE_CENTS if client['profile_care'] else 0)


# Seasonal ideas for Google Business posts (southern hemisphere). The owner edits before posting.
SEASONS={12:'summer',1:'summer',2:'summer',3:'autumn',4:'autumn',5:'autumn',6:'winter',7:'winter',8:'winter',9:'spring',10:'spring',11:'spring'}
POST_IDEAS=(
 '{season} is a busy time for us at {name}. If you have been putting a job off, now is a good time to book in. Call us or send a message through this profile and we will get back to you within a day.',
 'Thank you to everyone who has trusted {name} this {season}. Your reviews help other locals find us, and we read every one. If we have helped you recently, we would love to hear how it went.',
)
REVIEW_REQUEST=('Hi, thanks again for choosing {name}. If you were happy with the job, would you mind leaving us a quick Google review? '
  'It takes a minute and really helps a small local business. Here is the link: [your Google review link]. Thank you!')


def ensure_profile_posts(conn,owner,on=None):
    """Draft this month's two Google posts and the review-request message for each Profile Care client. Returns how many were drafted."""
    on=on or today();month=on.isoformat()[:7];season=SEASONS[on.month];made=0
    for client in conn.execute('SELECT * FROM plan_clients WHERE owner_id=? AND profile_care=1',(owner,)).fetchall():
        if state(client,on)=='Ended':continue
        drafts=[('post',i,idea.format(name=client['client_name'],season=season)) for i,idea in enumerate(POST_IDEAS)]+[('review',0,REVIEW_REQUEST.format(name=client['client_name']))]
        for kind,slot,text in drafts:
            text=text[0].upper()+text[1:]
            made+=conn.execute('INSERT OR IGNORE INTO profile_posts(owner_id,client_id,month,kind,slot,text,created_at) VALUES(?,?,?,?,?,?,?)',(owner,client['id'],month,kind,slot,text,stamp())).rowcount
    return made


def used_this_month(conn,client_id,on=None):
    on=on or today()
    return conn.execute("SELECT COUNT(*) FROM plan_requests WHERE client_id=? AND size='small' AND substr(created_at,1,7)=?",(client_id,on.isoformat()[:7])).fetchone()[0]


def draft_reply(client,request_text,size,used):
    """Rule-based reply for the owner to check and send themselves. Never sent from here."""
    plan=PLANS[client['plan']];first=client['client_name'].split()[0]
    days=str(plan['days'])+' business day'+('s' if plan['days']>1 else '')
    if size=='quote':
        body='This one is bigger than a small change, so I will send you a quick quote before I start.'
    elif plan['allowance'] and used>plan['allowance']:
        body='You have used the '+str(plan['allowance'])+' small changes included this month, so I will send you a quick price for this one, or I can do it next month at no charge.'
    else:
        count=' That is change '+str(used)+' of '+str(plan['allowance'])+' included this month.' if plan['allowance'] else ''
        body='I will have it done within '+days+' and let you know when it is live.'+count
    return 'Hi '+first+',\n\nThanks, I have got your request: "'+request_text+'".\n\n'+body+'\n\nCheers,\nBenji'


def summary(conn,owner,on=None):
    on=on or today();iso=on.isoformat()
    clients=conn.execute('SELECT * FROM plan_clients WHERE owner_id=? ORDER BY client_name',(owner,)).fetchall()
    live=[c for c in clients if state(c,on)!='Ended']
    return dict(monthly_cents=sum(monthly_value(c) for c in live if state(c,on)=='Active'),clients=len(live),
      overdue=sum(1 for c in live if c['next_due_on']<iso and (not c['ends_on'] or c['next_due_on']<=c['ends_on'])),
      requests=conn.execute("SELECT COUNT(*) FROM plan_requests WHERE owner_id=? AND status!='Done'",(owner,)).fetchone()[0],
      profile_care=sum(1 for c in live if c['profile_care']),
      posts=conn.execute("SELECT COUNT(*) FROM profile_posts WHERE owner_id=? AND status='New'",(owner,)).fetchone()[0])


def client_for(conn,owner,client_id):
    client=conn.execute('SELECT * FROM plan_clients WHERE id=? AND owner_id=?',(client_id,owner)).fetchone()
    if not client:raise WorkflowError('That client is not on a monthly plan here.')
    return client


def register(app,get_db,login_required):
    @app.get('/clients',strict_slashes=False)
    @login_required
    def plan_clients():
        conn=get_db();owner=session['user_id'];on=today()
        rows=conn.execute('SELECT * FROM plan_clients WHERE owner_id=? ORDER BY client_name',(owner,)).fetchall()
        clients=[dict(c,state=state(c,on),value=monthly_value(c),used=used_this_month(conn,c['id'],on),allowance=PLANS[c['plan']]['allowance'],overdue=c['next_due_on']<on.isoformat()) for c in rows]
        requests=conn.execute("SELECT r.*,c.client_name FROM plan_requests r JOIN plan_clients c ON c.id=r.client_id WHERE r.owner_id=? ORDER BY r.status='Done',r.id DESC LIMIT 50",(owner,)).fetchall()
        return render_template('plan_clients.html',clients=clients,requests=requests,totals=summary(conn,owner,on),plans=PLANS,sources=SOURCES,today=on.isoformat(),notice=NOTICE_DAYS,profile_care_cents=PROFILE_CARE_CENTS)

    @app.post('/clients/add')
    @login_required
    def plan_client_add():
        name=request.form.get('client_name','').strip();email=request.form.get('contact_email','').strip()
        plan=request.form.get('plan');billing=request.form.get('billing','monthly')
        try:started=date.fromisoformat(request.form.get('started_on',''))
        except ValueError:raise WorkflowError('Pick the date the plan starts.')
        if not 1<=len(name)<=160 or len(email)>254 or plan not in PLANS or billing not in ('monthly','yearly'):
            raise WorkflowError('Add the client name, a plan (Care or Autopilot) and monthly or yearly billing.')
        conn=get_db();owner=session['user_id']
        conn.execute('INSERT INTO plan_clients(owner_id,client_name,contact_email,plan,billing,started_on,next_due_on,created_at) VALUES(?,?,?,?,?,?,?,?)',(owner,name,email,plan,billing,started.isoformat(),started.isoformat(),stamp()))
        log(conn,owner,'Added '+name+' to the '+plan+' plan ('+billing+'). No payment taken.');conn.commit()
        flash(name+' is on the '+plan+' plan. Record their first payment when it lands in your bank.','success');return redirect(url_for('plan_clients'))

    @app.post('/clients/<int:client_id>/payment')
    @login_required
    def plan_client_payment(client_id):
        conn=get_db();owner=session['user_id'];client=client_for(conn,owner,client_id)
        reference=request.form.get('bank_reference','').strip()
        try:cents=round(float(request.form.get('amount','').replace('$','').replace(',',''))*100)
        except ValueError:cents=0
        if request.form.get('confirm')!='yes' or cents<=0 or not 1<=len(reference)<=160:
            raise WorkflowError('Enter the amount and bank reference, and tick that you checked it is in your bank.')
        if conn.execute('SELECT 1 FROM plan_payments WHERE owner_id=? AND bank_reference=?',(owner,reference)).fetchone():
            raise WorkflowError('That bank reference is already recorded.')
        due=date.fromisoformat(client['next_due_on'])
        conn.execute('INSERT INTO plan_payments(owner_id,client_id,amount_cents,bank_reference,received_on,recorded_at) VALUES(?,?,?,?,?,?)',(owner,client_id,cents,reference,today().isoformat(),stamp()))
        conn.execute('UPDATE plan_clients SET next_due_on=? WHERE id=?',(add_months(due,12 if client['billing']=='yearly' else 1).isoformat(),client_id))
        log(conn,owner,'Recorded a plan payment from '+client['client_name']+' (owner checked the bank).');conn.commit()
        flash('Payment recorded. It now counts in your money tiles.','success');return redirect(url_for('plan_clients'))

    @app.post('/clients/<int:client_id>/cancel')
    @login_required
    def plan_client_cancel(client_id):
        conn=get_db();owner=session['user_id'];client=client_for(conn,owner,client_id)
        if request.form.get('confirm')!='yes':raise WorkflowError('Tick to confirm the client gave notice.')
        if client['ends_on']:raise WorkflowError('This client has already given notice.')
        ends=today()+timedelta(days=NOTICE_DAYS)
        conn.execute('UPDATE plan_clients SET ends_on=? WHERE id=?',(ends.isoformat(),client_id))
        log(conn,owner,client['client_name']+' gave 30 days notice; plan ends '+ends.isoformat()+'.');conn.commit()
        flash(client['client_name']+' finishes on '+ends.strftime('%-d %b %Y')+'. Offer them the A$250 site handover or take the site down then.','success');return redirect(url_for('plan_clients'))

    @app.post('/clients/<int:client_id>/profile-care')
    @login_required
    def plan_client_profile_care(client_id):
        conn=get_db();owner=session['user_id'];client=client_for(conn,owner,client_id)
        on=request.form.get('on')=='1'
        conn.execute('UPDATE plan_clients SET profile_care=? WHERE id=?',(int(on),client_id))
        if on:ensure_profile_posts(conn,owner)
        log(conn,owner,client['client_name']+(' added' if on else ' removed')+' Google Profile Care (A$49 a month). Nothing charged or posted.');conn.commit()
        flash((client['client_name']+' now has Google Profile Care, A$49 a month on top of their plan. This month\'s posts are drafted for you.') if on else 'Google Profile Care removed.','success')
        return redirect(url_for('plan_clients'))

    @app.post('/clients/posts/<int:post_id>/<action>')
    @login_required
    def profile_post_update(post_id,action):
        conn=get_db();owner=session['user_id']
        row=conn.execute('SELECT * FROM profile_posts WHERE id=? AND owner_id=?',(post_id,owner)).fetchone()
        if not row or action not in ('approve','skip'):raise WorkflowError('That post was not found.')
        text=request.form.get('text',row['text']).strip()
        if action=='approve' and not 10<=len(text)<=1500:raise WorkflowError('The post needs some text (Google allows up to 1,500 characters).')
        conn.execute('UPDATE profile_posts SET status=?,text=? WHERE id=?',('Approved' if action=='approve' else 'Skipped',text,post_id));conn.commit()
        flash('Approved. Paste it into their Google Business Profile.' if action=='approve' else 'Skipped.','success')
        return redirect(url_for('business_home')+'#ready' if request.form.get('next')=='home' else url_for('plan_clients'))

    @app.post('/clients/requests')
    @login_required
    def plan_request_add():
        conn=get_db();owner=session['user_id'];client=client_for(conn,owner,request.form.get('client_id',type=int))
        text=' '.join(request.form.get('request','').split());source=request.form.get('source');size=request.form.get('size')
        if not 3<=len(text)<=1000 or source not in SOURCES or size not in ('small','quote'):
            raise WorkflowError('Write what the client asked for, where it came from, and whether it is a small change or needs a quote.')
        if state(client)=='Ended':raise WorkflowError('This client has left their plan.')
        used=used_this_month(conn,client['id'])+(size=='small')
        conn.execute('INSERT INTO plan_requests(owner_id,client_id,source,request,size,reply,created_at) VALUES(?,?,?,?,?,?,?)',(owner,client['id'],source,text,size,draft_reply(client,text,size,used),stamp()))
        conn.commit();flash('Request saved with a reply drafted for you to check.','success');return redirect(url_for('plan_clients'))

    @app.post('/clients/requests/<int:request_id>/<action>')
    @login_required
    def plan_request_update(request_id,action):
        conn=get_db();owner=session['user_id']
        row=conn.execute('SELECT * FROM plan_requests WHERE id=? AND owner_id=?',(request_id,owner)).fetchone()
        if not row or action not in ('approve','done'):raise WorkflowError('That request was not found.')
        if action=='approve':
            reply=request.form.get('reply','').strip()
            if not 1<=len(reply)<=4000:raise WorkflowError('The reply cannot be empty.')
            conn.execute("UPDATE plan_requests SET status='Approved',reply=? WHERE id=?",(reply,request_id))
            message='Reply approved. Copy it into your email and send it yourself.'
            if request.form.get('next')=='home':
                conn.commit();flash(message,'success');return redirect(url_for('business_home')+'#ready')
        else:
            conn.execute("UPDATE plan_requests SET status='Done',done_at=? WHERE id=?",(stamp(),request_id))
            message='Marked done.'
        conn.commit();flash(message,'success');return redirect(url_for('plan_clients'))

"""Small, private business workflow. No purchases, public deployment or legal filings."""
import json
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from flask import abort,flash,redirect,render_template,request,session,url_for
from phase3_store import WorkflowError,stamp
from phase4_store import paused
from sales_store import dumps,log
from production_security import audit
import gmail_agent
import discovery_preparation

PACKAGES=(
 ('Starter Website',60000,'one-page','One responsive page with up to five sections; client-approved text, service summary and contact details; basic page title/description; one revision round; static export and handover.'),
 ('Business Website',80000,'multi-page','Up to four responsive pages: Home, Services, About and Contact; client-approved copy and branding; basic technical SEO; two revision rounds; static export and handover.'),
 ('Premium Website',100000,'custom','Up to four responsive pages with tailored layout and expanded customer-approved content; basic technical SEO; three revision rounds; static export, handover guide and one handover call. Additional pages require a separate quote.'),
)
EXCLUSIONS='Domain, hosting, paid assets, ongoing maintenance, e-commerce, bookings, custom backends, paid form services, copywriting beyond agreed edits and public publication are excluded. Customer owns and pays for domain/hosting. No unlimited revisions or guaranteed results.'
FIELDS={
 'business_name':('Business name',200),'description':('What does the business do?',800),
 'objectives':('What should the website help customers do?',600),'pages':('Pages needed',300),
 'style':('Style and example references',600),'colours':('Colour preferences',150),
 'contact_email':('Approved business email for the website',254),'contact_phone':('Approved phone (optional)',80),
 'services':('Actual customer services — one per line',800),'about':('Approved about copy',800),
 'headline':('Approved homepage headline',140),'intro':('Approved homepage introduction',360),
 'assets':('Logo, images, branding and permission references',800),
 'functionality':('Functionality and special requests',600),'timeline':('Timeline',150),
 'budget':('Customer-stated budget (unknown is allowed)',150),'domain_hosting':('Existing domain and hosting',400),
}


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS first_sale_intake (
      flow_id INTEGER PRIMARY KEY REFERENCES p5_flows(id), owner_id INTEGER NOT NULL,
      answers_json TEXT NOT NULL, source TEXT NOT NULL, confirmed_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS first_sale_receipts (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, quote_id INTEGER NOT NULL REFERENCES p5_quotes(id),
      amount_cents INTEGER NOT NULL CHECK(amount_cents>0), bank_reference TEXT NOT NULL,
      evidence TEXT NOT NULL, received_on TEXT NOT NULL, recorded_at TEXT NOT NULL,
      UNIQUE(owner_id,bank_reference));
    CREATE TABLE IF NOT EXISTS first_sale_reports (
      owner_id INTEGER NOT NULL, local_date TEXT NOT NULL, report_json TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(owner_id,local_date));
    ''')


def metrics(conn,owner):
    def n(sql,args=()):return conn.execute(sql,args).fetchone()[0]
    # Older billing paths cannot issue live invoices. Never promote manual labels
    # or synthetic credits into earned revenue; bank evidence requires owner action.
    received=n("SELECT COALESCE(SUM(p.amount_cents),0) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE i.user_id=? AND i.synthetic=0 AND p.status='Verified'",(owner,))
    refunds=n("SELECT COALESCE(SUM(r.amount_cents),0) FROM p7_refunds r JOIN p7_invoices i ON i.id=r.invoice_id WHERE i.user_id=? AND i.synthetic=0 AND r.status IN ('verified','succeeded','complete')",(owner,))
    bank_received=n('SELECT COALESCE(SUM(amount_cents),0) FROM first_sale_receipts WHERE owner_id=?',(owner,))
    expenses=n('SELECT COALESCE(SUM(amount_cents),0) FROM prep_expenses WHERE user_id=? AND synthetic=0',(owner,))
    return dict(leads=n('SELECT COUNT(*) FROM leads'),opportunities=n('SELECT COUNT(*) FROM p5_flows WHERE user_id=? AND synthetic=0',(owner,)),
      quotes=n('SELECT COUNT(*) FROM p5_quotes q JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=? AND f.synthetic=0',(owner,)),
      accepted=n('SELECT COUNT(*) FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=? AND f.synthetic=0',(owner,)),
      received_cents=max(0,received-refunds)+bank_received,provider_and_legacy_receipts_cents=max(0,received-refunds),owner_bank_cents=bank_received,expense_cents=expenses,cash_surplus_cents=max(0,received-refunds)+bank_received-expenses,
      pending_approvals=n("SELECT COUNT(*) FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND j.status IN ('Needs review','Awaiting approval')",(owner,)),
      failed_jobs=n("SELECT COUNT(*) FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND j.status IN ('Failed','Interrupted')",(owner,)),
      gmail_incoming=n("SELECT COUNT(*) FROM gmail_mail WHERE owner_id=? AND direction='incoming'",(owner,)),
      gmail_drafts=n("SELECT COUNT(*) FROM gmail_drafts WHERE owner_id=? AND status='Needs review'",(owner,)),
      gmail_sent=n("SELECT COUNT(*) FROM gmail_drafts WHERE owner_id=? AND status='Sent'",(owner,)),
      suppressed=n('SELECT COUNT(*) FROM p5_suppressions WHERE user_id=?',(owner,)),
      projects=n('SELECT COUNT(*) FROM p5_project_briefs b JOIN p5_acceptances a ON a.id=b.acceptance_id JOIN p5_quotes q ON q.id=a.quote_id JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=? AND f.synthetic=0',(owner,)))


MILESTONES=(100,100000,1000000,10000000)


def money_in(conn,owner,today=None):
    """Verified money by month and week, for the home dashboard. Same sources as metrics(); quotes, tests and simulated payments never count."""
    today=today or datetime.now(ZoneInfo('Australia/Sydney')).date()
    rows=conn.execute("SELECT substr(p.created_at,1,10) day,p.amount_cents FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE i.user_id=? AND i.synthetic=0 AND p.status='Verified'",(owner,)).fetchall()
    rows+=conn.execute('SELECT substr(received_on,1,10) day,amount_cents FROM first_sale_receipts WHERE owner_id=?',(owner,)).fetchall()
    keys=[]
    y,mo=today.year,today.month
    for _ in range(6):keys.insert(0,(y,mo));y,mo=(y,mo-1) if mo>1 else (y-1,12)
    by_month={k:0 for k in keys};week=0;week_start=today-timedelta(days=today.weekday())
    for day,cents in rows:
        try:d=date.fromisoformat(day)
        except ValueError:continue
        if (d.year,d.month) in by_month:by_month[(d.year,d.month)]+=cents
        if week_start<=d<=today:week+=cents
    top=max(by_month.values()) or 1
    months=[dict(label=date(y,mo,1).strftime('%b'),cents=c,pct=round(100*c/top) if c else 0,current=(y,mo)==keys[-1],best=c==top and c>0) for (y,mo),c in by_month.items()]
    prev=months[-2]['cents']
    return dict(months=months,month_cents=months[-1]['cents'],prev_month_cents=prev,month_change_cents=months[-1]['cents']-prev,week_cents=week,has_money=any(m['cents'] for m in months))


def next_milestone(received_cents):
    """The first-sale, A$1k, A$10k and A$100k goals from the owner's plan."""
    goal=next((g for g in MILESTONES if received_cents<g),MILESTONES[-1])
    return dict(goal_cents=goal,first_sale=goal==100,pct=min(100,round(100*received_cents/goal)))


def daily_report(conn,now=None):
    if paused(conn):return
    day=(now or datetime.now(ZoneInfo('Australia/Sydney'))).date().isoformat()
    for owner in conn.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchall():
        conn.execute('INSERT OR IGNORE INTO first_sale_reports VALUES(?,?,?,?)',(owner[0],day,dumps(metrics(conn,owner[0])),stamp()))
    conn.commit()


def fit_score(snapshot,contact_eligible=False):
    """Sales suitability is separate from source completeness and intent."""
    lead=snapshot['lead'];industry=lead.get('industry','').casefold()
    service=any(v in industry for v in ('clean','landscap','garden','trade','plumb','electric','detail','mechanic','beauty','barber','retail','cafe','hospitality'))
    findings=sum(len(a.get('findings',[])) for a in snapshot.get('audits',[]))
    current=any(__import__('phase4_data').source_current(s) for s in snapshot.get('sources',[]))
    parts=[dict(points=25 if service else 0,reason='Recorded industry fits a small service-business offer' if service else 'Industry fit needs owner review'),
       dict(points=min(25,findings*5),reason='Current approved technical observations: '+str(findings)),
       dict(points=25 if current else 0,reason='Current owner-reviewed source permission' if current else 'Current source permission not established'),
       dict(points=25 if contact_eligible else 0,reason='Contact eligibility reviewed' if contact_eligible else 'Contact eligibility not established')]
    return dict(score=sum(p['points'] for p in parts),reasons=parts,purchase_intent='Unknown',budget='Unknown; do not infer ability to afford A$600–A$1,000',complexity='Requires scope review',limitation='Rule-based triage, not a purchase prediction.')


def configured(conn,owner):
    return bool(conn.execute("SELECT 1 FROM p5_packages WHERE user_id=? AND name='Starter Website'",(owner,)).fetchone())


def priorities(conn,owner,m,gmail,config):
    """At most five owner actions, most important first. Empty means nothing needs the owner."""
    items=[]
    def add(text,label,endpoint,anchor=''):items.append(dict(text=text,label=label,url=url_for(endpoint)+anchor))
    if m['failed_jobs']:add(str(m['failed_jobs'])+' job'+('s' if m['failed_jobs']>1 else '')+' failed and need a look','Open','operations')
    if m['pending_approvals']:add(str(m['pending_approvals'])+' item'+('s' if m['pending_approvals']>1 else '')+' waiting for your review','Review','sales_home')
    if m['gmail_drafts']:add(str(m['gmail_drafts'])+' email repl'+('ies' if m['gmail_drafts']>1 else 'y')+' drafted for you to check','Check','gmail_home')
    if config['gst_mode']=='unset':add('Confirm your GST status before your first quote','Set GST','sales_home')
    if not gmail:add('Connect your business Gmail (one-time sign-in)','Connect','gmail_home')
    if not m['leads']:add('Add your first potential customer','Add lead','leads')
    return items[:5]


def ceo_answer(question,m,todo,is_paused,runtime):
    """Rule-based answers from local records. Not a language model; never invents numbers."""
    q=question.casefold()
    queued=sum(c.get('Queued',0) for c in runtime['queues'].values())
    running=sum(c.get('Running',0) for c in runtime['queues'].values())
    state='paused' if is_paused else ('running' if runtime['workers'] else 'switched on, but the background worker is not running (open the AgencyOS launcher)')
    def money(cents):return 'A$'+format(cents/100,',.2f')
    if any(w in q for w in ('customer','sale','why','stuck','sell')):
        steps=[(m['leads'],'You have no leads yet. Add a real business you are allowed to contact; that is the first step.'),
          (m['opportunities'],'You have '+str(m['leads'])+' lead(s) but none has been started as an opportunity. Open Customers and start one.'),
          (m['quotes'],'You have '+str(m['opportunities'])+' opportunity(ies) but no quote yet. Finish the questionnaire and prepare a quote.'),
          (m['accepted'],'You have '+str(m['quotes'])+' quote(s) out and none accepted yet. Follow up with those customers.'),
          (m['received_cents'],'A quote was accepted but no payment is recorded. Once the money is in your bank, record it under Money.')]
        for value,reason in steps:
            if not value:return reason
        return 'You have recorded '+money(m['received_cents'])+' received. Keep the next quote moving.'
    if any(w in q for w in ('money','revenue','paid','earn','cash','profit')):
        return 'Money you have recorded as received: '+money(m['received_cents'])+'. Expenses: '+money(m['expense_cents'])+'. Test and simulated payments are not counted.'
    if any(w in q for w in ('working','doing','job','agent','busy')):
        return 'The agency is '+state+'. Right now '+str(running)+' job(s) are running and '+str(queued)+' are queued.'
    if any(w in q for w in ('need','todo','to do','should','waiting','approve')):
        if not todo:return 'Nothing needs you right now.'
        return 'Here is what needs you: '+'; '.join(t['text'] for t in todo)+'.'
    summary='The agency is '+state+'. You have '+str(m['leads'])+' lead(s), '+str(m['quotes'])+' quote(s), '+str(m['projects'])+' website project(s) and '+money(m['received_cents'])+' received.'
    return summary+(' '+str(len(todo))+' thing(s) need you; see What matters now.' if todo else ' Nothing needs you right now.')


CEO_SUGGESTIONS=("What's happening?","Why don't we have customers yet?","What's everyone working on?","How much money have we made?")


def register(app,get_db,login_required):
    @app.get('/business',strict_slashes=False)
    @login_required
    def business_home():
        import runtime_status
        conn=get_db();owner=session['user_id'];m=metrics(conn,owner)
        gmail=conn.execute('SELECT email FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
        runtime=runtime_status.status(conn,conn.execute('PRAGMA database_list').fetchone()[2],'5')
        todo=priorities(conn,owner,m,gmail,conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone())
        question=request.args.get('ask','').strip()[:300]
        answer=ceo_answer(question,m,todo,paused(conn),runtime) if question else ''
        return render_template('business_classic.html' if request.cookies.get('look')=='classic' else 'business.html',metrics=m,paused=paused(conn),worker=bool(runtime['workers']),todo=todo,
          configured=configured(conn,owner),question=question,answer=answer,suggestions=CEO_SUGGESTIONS,
          money=money_in(conn,owner),milestone=next_milestone(m['received_cents']))

    @app.get('/look/<name>')
    @login_required
    def set_look(name):
        if name not in ('bento','classic'):abort(404)
        response=redirect(url_for('business_home'))
        response.set_cookie('look',name,max_age=10*365*86400,httponly=True,samesite='Lax')
        return response

    @app.get('/business/details',strict_slashes=False)
    @login_required
    def business_details():
        import runtime_status
        conn=get_db();owner=session['user_id']
        return render_template('business_details.html',metrics=metrics(conn,owner),paused=paused(conn),
          gmail=conn.execute('SELECT email,last_sync,polling,error FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone(),
          runtime=runtime_status.status(conn,conn.execute('PRAGMA database_list').fetchone()[2],'5'),
          flows=conn.execute('SELECT * FROM p5_flows WHERE user_id=? ORDER BY id DESC LIMIT 50',(owner,)).fetchall(),
          projects=conn.execute('SELECT * FROM projects ORDER BY id DESC LIMIT 30').fetchall(),
          reports=conn.execute('SELECT * FROM first_sale_reports WHERE owner_id=? ORDER BY local_date DESC LIMIT 7',(owner,)).fetchall(),
          accepted_quotes=conn.execute('SELECT q.id,a.customer_name FROM p5_quotes q JOIN p5_acceptances a ON a.quote_id=q.id JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=? AND f.synthetic=0',(owner,)).fetchall(),
          receipts=conn.execute('SELECT * FROM first_sale_receipts WHERE owner_id=? ORDER BY id DESC LIMIT 20',(owner,)).fetchall(),
          config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone())

    @app.post('/business/configure')
    @login_required
    def business_configure():
        if request.form.get('confirm')!='yes':raise WorkflowError('Confirm the approved owner identity and package creation. GST is a separate owner decision.')
        conn=get_db();owner=session['user_id'];conn.execute('BEGIN IMMEDIATE')
        # Existing commercial records/quotes/packages remain immutable.
        for name,cents,category,scope in PACKAGES:
            previous=conn.execute('SELECT * FROM p5_packages WHERE user_id=? AND name=? ORDER BY version DESC LIMIT 1',(owner,name)).fetchone()
            if not previous or (previous['price_cents'],previous['category'],previous['scope'],previous['exclusions'])!=(cents,category,scope,EXCLUSIONS):
                version=previous['version']+1 if previous else 1
                conn.execute('INSERT INTO p5_packages(user_id,name,version,category,price_cents,cycle,scope,exclusions,created_at) VALUES(?,?,?,?,?,\'one-off\',?,?,?)',(owner,name,version,category,cents,scope,EXCLUSIONS,stamp()))
        conn.execute("UPDATE p5_control SET sender=?,provider='mock',daily_cents=0,daily_requests=0,input_rate=0,output_rate=0 WHERE id=1",(gmail_agent.ACCOUNT,))
        conn.execute("UPDATE p7_control SET business_name='Benji Price',business_email=?,provider='mock' WHERE id=1",(gmail_agent.ACCOUNT,))
        # No ABN, address or GST registration is invented or overwritten.
        conn.execute('INSERT OR IGNORE INTO prep_discovery VALUES(?,?,?)',(owner,dumps(discovery_preparation.DEFAULTS),stamp()))
        log(conn,owner,'Applied owner-approved Benji Price identity and first-sale packages; zero AI budget, no live sending. Existing packages/quotes preserved.')
        audit(conn,'first_sale_configured',owner);conn.commit();flash('Identity and packages ready. Confirm actual GST treatment in Sales before quoting.','success');return redirect(url_for('business_home'))

    @app.post('/business/receipts')
    @login_required
    def business_receipt():
        from datetime import date
        from sales_quotes import money_input
        conn=get_db();owner=session['user_id'];conn.execute('BEGIN IMMEDIATE')
        quote=conn.execute("SELECT q.* FROM p5_quotes q JOIN p5_acceptances a ON a.quote_id=q.id JOIN p5_flows f ON f.id=q.flow_id WHERE q.id=? AND f.user_id=? AND f.synthetic=0 AND q.content_hash=a.quote_hash",(request.form.get('quote_id',type=int),owner)).fetchone()
        amount=money_input(request.form.get('amount',''));reference=request.form.get('bank_reference','').strip();evidence=request.form.get('evidence','').strip()
        try:
            received_on=date.fromisoformat(request.form.get('received_on',''))
            if received_on>datetime.now(ZoneInfo('Australia/Sydney')).date():raise ValueError()
        except ValueError:raise WorkflowError('Enter the actual bank receipt date, not a future date.') from None
        if not quote or request.form.get('confirm')!='yes' or not 1<=amount or not 5<=len(evidence)<=1000 or not 1<=len(reference)<=160:raise WorkflowError('Select accepted real scope, actual receipt amount/reference, evidence and confirmation you independently checked your bank.')
        # Do not count the same payment through both the provider and bank ledgers.
        if conn.execute('SELECT 1 FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE i.quote_id=?',(quote['id'],)).fetchone():raise WorkflowError('This quote has another payment ledger. Reconcile there; do not duplicate receipts here.')
        existing=conn.execute('SELECT * FROM first_sale_receipts WHERE owner_id=? AND bank_reference=?',(owner,reference)).fetchone()
        if existing:
            if existing['quote_id']!=quote['id'] or existing['amount_cents']!=amount:raise WorkflowError('Bank reference reused with different details; inspect the existing receipt.')
            conn.rollback();flash('Existing bank receipt retained; no duplicate revenue.','success');return redirect(url_for('business_details'))
        total=json.loads(quote['content_json'])['totals']['one-off']['total_cents']
        paid=conn.execute('SELECT COALESCE(SUM(amount_cents),0) FROM first_sale_receipts WHERE quote_id=?',(quote['id'],)).fetchone()[0]
        if amount>total-paid:raise WorkflowError('Receipt exceeds the remaining accepted one-off total; review financial exceptions separately.')
        conn.execute('INSERT INTO first_sale_receipts(owner_id,quote_id,amount_cents,bank_reference,evidence,received_on,recorded_at) VALUES(?,?,?,?,?,?,?)',(owner,quote['id'],amount,reference,evidence,received_on.isoformat(),stamp()))
        audit(conn,'owner_bank_receipt_attested',owner,{'quote_id':quote['id'],'amount_cents':amount,'independent_bank_api':False});conn.commit()
        flash('Owner-confirmed bank receipt recorded. No bank API verification, invoice issuance or money transfer occurred.','success');return redirect(url_for('business_details'))

    @app.get('/business/flows/<int:flow_id>/intake')
    @login_required
    def business_intake(flow_id):
        conn=get_db();flow=conn.execute('SELECT * FROM p5_flows WHERE id=? AND user_id=?',(flow_id,session['user_id'])).fetchone()
        if not flow:abort(404)
        record=conn.execute('SELECT * FROM first_sale_intake WHERE flow_id=?',(flow_id,)).fetchone()
        lead=conn.execute('SELECT * FROM leads WHERE id=?',(flow['lead_id'],)).fetchone()
        defaults=dict(business_name=lead['business_name'] if lead else '',contact_email=lead['email'] if lead else '',domain_hosting='',description=lead['industry'] if lead else '')
        return render_template('business_intake.html',flow=flow,fields=FIELDS,answers=json.loads(record['answers_json']) if record else defaults,record=record)

    @app.post('/business/flows/<int:flow_id>/intake')
    @login_required
    def save_business_intake(flow_id):
        conn=get_db();owner=session['user_id'];conn.execute('BEGIN IMMEDIATE')
        flow=conn.execute('SELECT * FROM p5_flows WHERE id=? AND user_id=?',(flow_id,owner)).fetchone()
        if not flow:abort(404)
        if flow['state'] in ('Cancelled','Project brief ready'):raise WorkflowError('Accepted scope is frozen. Record later revisions against the website/project, not its original intake.')
        answers={k:request.form.get(k,'').strip() for k in FIELDS}
        if any(len(answers[k])>FIELDS[k][1] or any(ord(c)<32 and c not in '\n\r\t' for c in answers[k]) for k in FIELDS):raise WorkflowError('A questionnaire answer exceeds its limit or contains control characters.')
        source=request.form.get('source','').strip()
        if not source or len(source)>1000 or not answers['business_name'] or not answers['objectives']:raise WorkflowError('Business name, objectives and the actual information source are required; other unknown answers may remain blank.')
        if answers['contact_email']:answers['contact_email']=__import__('sales_email').address(answers['contact_email'])
        confirmed=stamp() if request.form.get('customer_confirmed')=='yes' else ''
        conn.execute('INSERT INTO first_sale_intake VALUES(?,?,?,?,?,?) ON CONFLICT(flow_id) DO UPDATE SET answers_json=excluded.answers_json,source=excluded.source,confirmed_at=excluded.confirmed_at,updated_at=excluded.updated_at',(flow_id,owner,dumps(answers),source,confirmed,stamp()))
        audit(conn,'customer_requirements_recorded',owner,{'flow_id':flow_id,'customer_confirmation_attested':bool(confirmed)})
        conn.commit();return redirect(url_for('business_intake',flow_id=flow_id))

    @app.post('/business/flows/<int:flow_id>/intake/proposal')
    @login_required
    def intake_proposal(flow_id):
        conn=get_db();owner=session['user_id'];conn.execute('BEGIN IMMEDIATE')
        record=conn.execute('SELECT * FROM first_sale_intake WHERE flow_id=? AND owner_id=?',(flow_id,owner)).fetchone()
        flow=conn.execute('SELECT * FROM p5_flows WHERE id=? AND user_id=?',(flow_id,owner)).fetchone()
        if not flow:abort(404)
        if paused(conn) or not record or not record['confirmed_at'] or flow['state'] in ('Cancelled','Project brief ready'):raise WorkflowError('Confirm the actual customer requirements before preparing a proposal; accepted scope stays frozen.')
        if not conn.execute("SELECT 1 FROM p5_drafts WHERE flow_id=? AND kind='outreach' AND status='Approved'",(flow_id,)).fetchone():raise WorkflowError('Review the existing research/outreach draft first. No email needs to be sent.')
        if conn.execute("SELECT 1 FROM p5_jobs WHERE flow_id=? AND kind IN ('proposal','quote') AND status IN ('Queued','Running','Needs review')",(flow_id,)).fetchone():raise WorkflowError('Review the current proposal/quote before creating another.')
        import sales_store
        answers=json.loads(record['answers_json'])
        requirements='\n'.join(FIELDS[k][0]+': '+v for k,v in answers.items() if v)
        snapshot=json.loads(flow['snapshot_json']);source='Owner-attested customer confirmation '+record['confirmed_at']+'; '+record['source']
        payload=dict(lead=snapshot['lead'],evidence=snapshot['evidence'],packages=json.loads(flow['package_json']),tone=flow['tone'],requirements=requirements,requirements_source=source,branding=answers['colours']+' '+answers['style'])
        payload.update(website_data=answers,website_data_source=record['source'],website_data_confirmation=record['confirmed_at'])
        conn.execute('UPDATE p5_flows SET requirements=?,requirements_source=?,branding=?,state=\'Proposal queued\' WHERE id=?',(requirements,source,payload['branding'],flow_id))
        sales_store.enqueue(conn,flow_id,'proposal',payload,key='intake-proposal-'+str(flow_id)+'-'+record['updated_at']);conn.commit()
        return redirect(url_for('sales_flow',flow_id=flow_id))

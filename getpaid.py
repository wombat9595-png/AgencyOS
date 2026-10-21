"""Get paid: real invoices with your ABN, bank details and an optional card or autopay link.

Pick the client and package, and AgencyOS makes the 50% deposit, the balance or the monthly
invoice as a PDF for you to attach. Bank details are typed in on this Mac, kept encrypted
(the launcher makes the key) and only ever printed onto the PDF. Nothing is emailed or
charged from here; the owner ticks "Paid" once the money is in the bank.
"""
import json
import re
from datetime import date,timedelta
from io import BytesIO
from flask import flash,redirect,render_template,request,send_file,session,url_for
from phase3_store import WorkflowError,stamp
from sales_store import log
import client_plans
import lead_engine
import phase7_billing

# Build prices and monthly fees in cents, before any GST.
PACKAGES={
 'Care':dict(setup=80000,monthly=6900),
 'Autopilot':dict(setup=140000,monthly=14900),
 'Signature':dict(setup=240000,monthly=14900),
 'Signature (founding)':dict(setup=190000,monthly=14900),
}
KINDS={'deposit':'50% deposit','balance':'Balance on launch','monthly':'Monthly plan','custom':'Other'}
PROFILE_CARE=client_plans.PROFILE_CARE_CENTS
DUE_DAYS={'deposit':7,'balance':7,'monthly':7,'custom':14}
STATUSES=('Ready','Paid','Cancelled')
STRIPE_LINK=re.compile(r'^https://(buy|checkout)\.stripe\.com/[A-Za-z0-9_\-/]+$')


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS bills (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, number TEXT NOT NULL, client_name TEXT NOT NULL, client_email TEXT NOT NULL DEFAULT '',
      package TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
      gst_cents INTEGER NOT NULL DEFAULT 0, total_cents INTEGER NOT NULL, issued_on TEXT NOT NULL, due_on TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Ready', paid_on TEXT NOT NULL DEFAULT '', paid_reference TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, UNIQUE(owner_id,number));
    CREATE TABLE IF NOT EXISTS pay_settings (owner_id INTEGER PRIMARY KEY, card_link TEXT NOT NULL DEFAULT '', debit_link TEXT NOT NULL DEFAULT '');
    ''')


def today():
    return lead_engine.today()


def control(conn):
    return dict(conn.execute('SELECT * FROM p7_control WHERE id=1').fetchone())


def bank(conn):
    """Decrypted bank details, or None. Only used to print the PDF."""
    row=control(conn)
    cipher=phase7_billing._fernet()
    if not row['bank_ciphertext'] or not cipher:return None
    try:return json.loads(cipher.decrypt(row['bank_ciphertext'].encode()))
    except Exception:return None


def pay_settings(conn,owner):
    row=conn.execute('SELECT * FROM pay_settings WHERE owner_id=?',(owner,)).fetchone()
    return dict(row) if row else dict(owner_id=owner,card_link='',debit_link='')


def ready(conn):
    """What is missing before a real invoice can go out. Empty list means good to go."""
    c=control(conn);missing=[]
    if not c['business_name']:missing.append('your business name')
    if not c['gst_mode']:missing.append('whether you are registered for GST')
    if not bank(conn):missing.append('your bank details')
    return missing


def money(cents):
    return 'A$'+format(cents/100,',.2f')


def next_number(conn,owner):
    n=conn.execute('SELECT COUNT(*) FROM bills WHERE owner_id=?',(owner,)).fetchone()[0]+1
    while conn.execute('SELECT 1 FROM bills WHERE owner_id=? AND number=?',(owner,'INV-'+format(n,'04d'))).fetchone():n+=1
    return 'INV-'+format(n,'04d')


def amount_for(package,kind,profile_care=False,custom_cents=None):
    if kind=='custom':
        if not custom_cents or custom_cents<100:raise WorkflowError('Enter the amount for this invoice.')
        return custom_cents
    if package not in PACKAGES:raise WorkflowError('Pick a package.')
    p=PACKAGES[package]
    if kind=='deposit':return p['setup']//2
    if kind=='balance':return p['setup']-p['setup']//2
    if kind=='monthly':return p['monthly']+(PROFILE_CARE if profile_care else 0)
    raise WorkflowError('Pick what the invoice is for.')


def describe(package,kind,profile_care=False,note=''):
    if kind=='custom':return note or 'Website services'
    site='Signature animated story website' if package.startswith('Signature') else package+' website'
    if kind=='deposit':return site+': 50% deposit to start (balance due on launch)'
    if kind=='balance':return site+': balance due on launch'
    month=today().strftime('%B %Y')
    return package.replace(' (founding)','')+' monthly plan, '+month+(' + Google Profile Care' if profile_care else '')+'. Month to month, 30 days notice, no lock-in.'


def create(conn,owner,form):
    c=control(conn)
    if c['gst_mode'] not in ('not_registered','registered_10'):raise WorkflowError('First tell AgencyOS whether you are registered for GST (in "Your invoice details" below).')
    name=' '.join(form.get('client_name','').split())[:160];email=form.get('client_email','').strip()[:254]
    if not name:raise WorkflowError('Add the client name.')
    if email and not lead_engine.clean_email(email):raise WorkflowError('That client email does not look right.')
    kind=form.get('kind','');package=form.get('package','')
    if kind not in KINDS:raise WorkflowError('Pick what the invoice is for.')
    custom=None
    if kind=='custom':
        try:custom=round(float(form.get('amount','0').replace('$','').replace(',',''))*100)
        except ValueError:raise WorkflowError('Enter the amount as a number, like 500.') from None
    profile=form.get('profile_care')=='yes'
    amount=amount_for(package,kind,profile,custom)
    gst=round(amount*0.1) if c['gst_mode']=='registered_10' else 0
    issued=today();number=next_number(conn,owner)
    conn.execute('''INSERT INTO bills(owner_id,number,client_name,client_email,package,kind,description,amount_cents,gst_cents,total_cents,issued_on,due_on,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(owner,number,name,email,package if kind!='custom' else '',kind,describe(package,kind,profile,' '.join(form.get('note','').split())[:200]),
      amount,gst,amount+gst,issued.isoformat(),(issued+timedelta(days=DUE_DAYS[kind])).isoformat(),stamp()))
    log(conn,owner,'Made invoice '+number+' for '+name+' ('+money(amount+gst)+'). Not sent: download the PDF and attach it.')
    return number


def bills(conn,owner):
    rows=conn.execute("SELECT * FROM bills WHERE owner_id=? ORDER BY CASE status WHEN 'Ready' THEN 0 WHEN 'Paid' THEN 1 ELSE 2 END, id DESC",(owner,)).fetchall()
    on=today().isoformat()
    return [dict(b,overdue=b['status']=='Ready' and b['due_on']<on) for b in rows]


def paid_cents(conn,owner,since=None):
    sql="SELECT COALESCE(SUM(total_cents),0) FROM bills WHERE owner_id=? AND status='Paid'";args=(owner,)
    if since:sql+=' AND paid_on>=?';args+=(since.isoformat(),)
    return conn.execute(sql,args).fetchone()[0]


def reminder(b,c):
    """A friendly nudge for an overdue invoice. The owner sends it himself."""
    return ('Hi '+b['client_name'].split()[0]+',\n\nJust a friendly reminder that invoice '+b['number']+' for '+money(b['total_cents'])+
      ' was due on '+date.fromisoformat(b['due_on']).strftime('%-d %B')+'. The bank details are on the invoice, and please use '+b['number']+' as the reference.\n\n'
      'If it has already gone through, thank you and please ignore this.\n\nCheers,\n'+(c['business_name'] or 'Benji'))


def pdf(conn,owner,b):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    c=control(conn);acct=bank(conn);links=pay_settings(conn,owner)
    out=BytesIO();page=canvas.Canvas(out,pagesize=A4);w,h=A4
    ink=colors.HexColor('#121626');muted=colors.HexColor('#5b6275');gold=colors.HexColor('#a8781b');line=colors.HexColor('#dcdfe9')
    page.setTitle(b['number']+' '+b['client_name'])
    page.setFillColor(ink);page.rect(0,h-46*mm,w,46*mm,fill=1,stroke=0)
    page.setFillColor(colors.white);page.setFont('Helvetica-Bold',20);page.drawString(20*mm,h-22*mm,c['business_name'] or 'Your business')
    page.setFont('Helvetica',9.5)
    meta=[x for x in (('ABN '+c['business_abn']) if c['business_abn'] else '',c['business_email'],c['business_address'].replace('\n',', ')) if x]
    page.drawString(20*mm,h-30*mm,'  ·  '.join(meta)[:120])
    title='TAX INVOICE' if c['gst_mode']=='registered_10' else 'INVOICE'
    page.setFillColor(colors.HexColor('#e2b350'));page.setFont('Helvetica-Bold',12);page.drawRightString(w-20*mm,h-22*mm,title)
    page.setFillColor(colors.white);page.setFont('Helvetica',9.5);page.drawRightString(w-20*mm,h-30*mm,b['number'])
    y=h-62*mm
    page.setFillColor(muted);page.setFont('Helvetica',8.5)
    for x,label in ((20,'BILL TO'),(110,'ISSUED'),(150,'DUE')):page.drawString(x*mm,y,label)
    page.setFillColor(ink);page.setFont('Helvetica-Bold',11)
    page.drawString(20*mm,y-6*mm,b['client_name'][:48])
    page.setFont('Helvetica',10.5)
    page.drawString(110*mm,y-6*mm,date.fromisoformat(b['issued_on']).strftime('%-d %b %Y'))
    page.drawString(150*mm,y-6*mm,date.fromisoformat(b['due_on']).strftime('%-d %b %Y'))
    if b['client_email']:page.setFillColor(muted);page.setFont('Helvetica',9.5);page.drawString(20*mm,y-11.5*mm,b['client_email'][:60])
    y-=28*mm
    page.setStrokeColor(line);page.line(20*mm,y+4*mm,w-20*mm,y+4*mm)
    page.setFillColor(muted);page.setFont('Helvetica',8.5);page.drawString(20*mm,y,'DESCRIPTION');page.drawRightString(w-20*mm,y,'AMOUNT')
    y-=8*mm;page.setFillColor(ink);page.setFont('Helvetica',10.5)
    words=b['description'].split();lines=[];cur=''
    for word in words:
        if len(cur)+len(word)+1>78:lines.append(cur);cur=word
        else:cur=(cur+' '+word).strip()
    lines.append(cur)
    for i,text in enumerate(lines):
        page.drawString(20*mm,y,text)
        if i==0:page.drawRightString(w-20*mm,y,money(b['amount_cents']))
        y-=5.5*mm
    y-=4*mm;page.line(110*mm,y+3*mm,w-20*mm,y+3*mm)
    rows=[('Subtotal',b['amount_cents'])]
    rows.append(('GST (10%)',b['gst_cents']) if c['gst_mode']=='registered_10' else ('GST','No GST: not registered'))
    for label,value in rows:
        page.setFillColor(muted);page.setFont('Helvetica',10);page.drawString(110*mm,y-2*mm,label)
        page.setFillColor(ink);page.drawRightString(w-20*mm,y-2*mm,money(value) if isinstance(value,int) else value);y-=6.5*mm
    page.setFillColor(ink);page.setFont('Helvetica-Bold',13);page.drawString(110*mm,y-3*mm,'Total due');page.drawRightString(w-20*mm,y-3*mm,money(b['total_cents']))
    y-=22*mm
    page.setFillColor(colors.HexColor('#f6ecd6'));box=44*mm+(8*mm if links['card_link'] else 0)+(8*mm if links['debit_link'] and b['kind']=='monthly' else 0)
    page.roundRect(20*mm,y-box+10*mm,w-40*mm,box,4*mm,fill=1,stroke=0)
    page.setFillColor(gold);page.setFont('Helvetica-Bold',9);page.drawString(26*mm,y+2*mm,'HOW TO PAY')
    page.setFillColor(ink);page.setFont('Helvetica',10.5);yy=y-5*mm
    if acct:
        for label,value in (('Bank transfer to',acct['account_name']),('BSB',acct['bsb']),('Account number',acct['account_number']),('Reference',b['number'])):
            page.setFillColor(muted);page.drawString(26*mm,yy,label);page.setFillColor(ink);page.setFont('Helvetica-Bold',10.5);page.drawString(70*mm,yy,value);page.setFont('Helvetica',10.5);yy-=6*mm
    else:
        page.drawString(26*mm,yy,'Bank details to follow.');yy-=6*mm
    if links['card_link']:
        page.setFillColor(muted);page.drawString(26*mm,yy,'Pay by card');page.setFillColor(ink);page.drawString(70*mm,yy,links['card_link'][:70]);page.linkURL(links['card_link'],(70*mm,yy-2,w-26*mm,yy+10));yy-=6*mm
    if links['debit_link'] and b['kind']=='monthly':
        page.setFillColor(muted);page.drawString(26*mm,yy,'Set up autopay');page.setFillColor(ink);page.drawString(70*mm,yy,links['debit_link'][:70]);page.linkURL(links['debit_link'],(70*mm,yy-2,w-26*mm,yy+10))
    page.setFillColor(muted);page.setFont('Helvetica',8.5)
    footer=(c['terms'] or 'Payment due by the date above.')+'  Monthly plans are month to month with 30 days notice and no lock-in.'
    page.drawString(20*mm,18*mm,footer[:130])
    if not c['business_abn']:page.drawString(20*mm,13*mm,'No ABN quoted on this invoice.')
    page.showPage();page.save()
    return out.getvalue()


def register(app,get_db,login_required):
    @app.get('/get-paid',strict_slashes=False)
    @login_required
    def get_paid():
        conn=get_db();owner=session['user_id'];c=control(conn)
        return render_template('get_paid.html',bills=bills(conn,owner),control=c,missing=ready(conn),bank_saved=bool(bank(conn)),
          can_encrypt=bool(phase7_billing._fernet()),packages=PACKAGES,kinds=KINDS,links=pay_settings(conn,owner),money=money,
          paid_month=paid_cents(conn,owner,since=today().replace(day=1)),
          clients=[r['client_name'] for r in conn.execute('SELECT client_name FROM plan_clients WHERE owner_id=? ORDER BY client_name',(owner,))],
          reminder=lambda b:reminder(b,c))

    @app.post('/get-paid/new')
    @login_required
    def get_paid_new():
        conn=get_db();number=create(conn,session['user_id'],request.form);conn.commit()
        flash(number+' is ready. Download the PDF and attach it to your email. Nothing was sent.','success')
        return redirect(url_for('get_paid')+'#bills')

    @app.get('/get-paid/<int:bill_id>/pdf')
    @login_required
    def get_paid_pdf(bill_id):
        conn=get_db();owner=session['user_id']
        b=conn.execute('SELECT * FROM bills WHERE id=? AND owner_id=?',(bill_id,owner)).fetchone()
        if not b:raise WorkflowError('That invoice is not in your list.')
        slug=re.sub(r'[^a-z0-9]+','-',b['client_name'].casefold()).strip('-')[:40] or 'client'
        return send_file(BytesIO(pdf(conn,owner,b)),mimetype='application/pdf',as_attachment=request.args.get('view')!='1',download_name=b['number']+'-'+slug+'.pdf')

    @app.post('/get-paid/<int:bill_id>/<action>')
    @login_required
    def get_paid_action(bill_id,action):
        conn=get_db();owner=session['user_id']
        b=conn.execute('SELECT * FROM bills WHERE id=? AND owner_id=?',(bill_id,owner)).fetchone()
        if not b:raise WorkflowError('That invoice is not in your list.')
        if action=='paid':
            if b['status']!='Ready':raise WorkflowError('Only an unpaid invoice can be marked paid.')
            if request.form.get('confirm')!='yes':raise WorkflowError('Tick that you checked the money is in your bank.')
            conn.execute("UPDATE bills SET status='Paid',paid_on=?,paid_reference=? WHERE id=?",(today().isoformat(),request.form.get('reference','').strip()[:120] or b['number'],bill_id))
            log(conn,owner,'Invoice '+b['number']+' from '+b['client_name']+' paid ('+money(b['total_cents'])+'), checked in the bank by the owner.')
            msg='Paid. '+money(b['total_cents'])+' added to your money in.'
        elif action=='cancel':
            if b['status']!='Ready':raise WorkflowError('Only an unpaid invoice can be cancelled.')
            conn.execute("UPDATE bills SET status='Cancelled' WHERE id=?",(bill_id,));msg='Cancelled. The number stays used so your records stay in order.'
        elif action=='unpaid':
            if b['status']!='Paid':raise WorkflowError('That invoice is not marked paid.')
            conn.execute("UPDATE bills SET status='Ready',paid_on='',paid_reference='' WHERE id=?",(bill_id,));msg='Marked unpaid again.'
        else:raise WorkflowError('Unknown action.')
        conn.commit();flash(msg,'success');return redirect(url_for('get_paid')+'#bills')

    @app.post('/get-paid/details')
    @login_required
    def get_paid_details():
        """Business identity and bank details. Bank details are encrypted with the key the launcher made and never shown again."""
        conn=get_db();c=control(conn)
        fields={k:request.form.get(k,'').strip() for k in ('business_name','business_abn','business_address','business_email','gst_mode','terms')}
        fields['business_abn']=re.sub(r'\s+',' ',fields['business_abn'])
        if fields['gst_mode'] not in ('not_registered','registered_10'):raise WorkflowError('Pick whether you are registered for GST.')
        if not fields['business_name'] or len(fields['business_name'])>160 or len(fields['business_address'])>500 or len(fields['business_email'])>254 or len(fields['terms'])>500:
            raise WorkflowError('Add your business name, and keep each field short.')
        if fields['business_abn'] and not re.fullmatch(r'\d{11}',fields['business_abn'].replace(' ','')):raise WorkflowError('An ABN is 11 digits.')
        if fields['business_email'] and not lead_engine.clean_email(fields['business_email']):raise WorkflowError('That email does not look right.')
        ciphertext=c['bank_ciphertext']
        acct=[' '.join(request.form.get(k,'').split()) for k in ('account_name','bsb','account_number')]
        if any(acct):
            name,bsb,number=acct;bsb=bsb.replace(' ','').replace('-','');number=number.replace(' ','').replace('-','')
            if not name or len(name)>160 or not re.fullmatch(r'\d{6}',bsb) or not re.fullmatch(r'\d{5,10}',number):
                raise WorkflowError('Bank details were not saved. Enter the account name, a 6 digit BSB and the account number.')
            cipher=phase7_billing._fernet()
            if not cipher:raise WorkflowError('Bank details need the private key the Desktop launcher makes. Open AgencyOS from the "Open AgencyOS" icon and try again.')
            ciphertext=cipher.encrypt(json.dumps(dict(account_name=name,bsb=bsb[:3]+'-'+bsb[3:],account_number=number)).encode()).decode()
        if request.form.get('forget_bank')=='yes':ciphertext=''
        conn.execute('UPDATE p7_control SET business_name=?,business_abn=?,business_address=?,business_email=?,gst_mode=?,terms=?,bank_ciphertext=?,updated_at=? WHERE id=1',
          (fields['business_name'],fields['business_abn'],fields['business_address'],fields['business_email'],fields['gst_mode'],fields['terms'] or 'Payment due within 7 days',ciphertext,stamp()))
        conn.commit();flash('Saved. Your bank details are encrypted on this Mac and only printed on your invoices.' if any(acct) else 'Saved.','success')
        return redirect(url_for('get_paid'))

    @app.post('/get-paid/links')
    @login_required
    def get_paid_links():
        conn=get_db();owner=session['user_id']
        card=request.form.get('card_link','').strip();debit=request.form.get('debit_link','').strip()
        for value in (card,debit):
            if value and (len(value)>300 or not STRIPE_LINK.match(value)):raise WorkflowError('Paste a Stripe Payment Link (it starts with https://buy.stripe.com/). Leave it empty to turn it off.')
        conn.execute('INSERT INTO pay_settings(owner_id,card_link,debit_link) VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET card_link=excluded.card_link,debit_link=excluded.debit_link',(owner,card,debit))
        conn.commit();flash('Saved. New invoice PDFs show these links.','success');return redirect(url_for('get_paid')+'#links')

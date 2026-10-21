"""Keep clients and grow from them: reviews, testimonials, referrals and a private page per client.

Drafts only. The owner sends review and referral messages himself, and a testimonial only
reaches the homepage once he ticks that the client said yes to it being shown. Client pages
go online only inside the publish pack, at a long random address hidden from search engines.
"""
from datetime import date,timedelta
from flask import flash,redirect,request,session,url_for
from phase3_store import WorkflowError,stamp
from sales_store import log
import client_plans
import lead_engine

STAGES=('Mock-up','Building','Your review','Live')
TESTIMONIAL_AFTER_DAYS=30
REFERRAL_OFFER='Send me a local business that signs up and your next month is free.'


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS client_growth (
      client_id INTEGER PRIMARY KEY REFERENCES plan_clients(id), site_stage TEXT NOT NULL DEFAULT 'Mock-up', site_url TEXT NOT NULL DEFAULT '',
      review_asked_on TEXT NOT NULL DEFAULT '', testimonial_asked_on TEXT NOT NULL DEFAULT '', testimonial TEXT NOT NULL DEFAULT '',
      testimonial_ok INTEGER NOT NULL DEFAULT 0, free_months_used INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS grow_settings (owner_id INTEGER PRIMARY KEY, review_url TEXT NOT NULL DEFAULT '');
    ''')


def growth(conn,client_id):
    row=conn.execute('SELECT * FROM client_growth WHERE client_id=?',(client_id,)).fetchone()
    if row:return dict(row)
    conn.execute('INSERT OR IGNORE INTO client_growth(client_id) VALUES(?)',(client_id,))
    return dict(conn.execute('SELECT * FROM client_growth WHERE client_id=?',(client_id,)).fetchone())


def review_url(conn,owner):
    row=conn.execute('SELECT review_url FROM grow_settings WHERE owner_id=?',(owner,)).fetchone()
    return row['review_url'] if row else ''


def messages(client,g,s,link):
    first=client['client_name'].split()[0];me=s['name'].split()[0]
    link=link or '[your Google review link: add it on the Studio page]'
    return dict(
      review=('Hi '+first+', '+me+' here. Thanks again for trusting me with your new website. If you are happy with it, would you mind leaving a quick Google review? '
        'It takes a minute and helps a one-person business more than you would think: '+link+'\n\nThanks heaps,\n'+me),
      testimonial=('Hi '+first+', it has been a month since your site went live. Has it brought in any calls or jobs? If you have a minute, could you send me one or two lines '
        'about what it has been like working with me? With your OK I would love to put it on my website with your business name.\n\nCheers,\n'+me),
      referral=('Hi '+first+', quick one. If you know another local business owner whose website needs some love, I would really appreciate the intro. '+REFERRAL_OFFER+
        ' Just reply with their name and number, or pass on mine: '+(s['phone'] or s['email'])+'.\n\nCheers,\n'+me))


def referrals(conn,owner):
    """Who referred whom, and the free months owed for referrals that became customers."""
    rows=conn.execute('''SELECT p.id,p.name,p.stage,p.referred_by,c.client_name FROM prospects p JOIN plan_clients c ON c.id=p.referred_by
        WHERE p.owner_id=? ORDER BY p.id DESC''',(owner,)).fetchall()
    owed={}
    for r in rows:
        if r['stage']=='Customer':owed[r['referred_by']]=owed.get(r['referred_by'],0)+1
    return [dict(r) for r in rows],owed


def page_data(conn,owner,on=None):
    on=on or client_plans.today();s=lead_engine.settings(conn,owner);link=review_url(conn,owner)
    made,owed=referrals(conn,owner);cards=[]
    for client in conn.execute('SELECT * FROM plan_clients WHERE owner_id=? ORDER BY client_name',(owner,)).fetchall():
        if client_plans.state(client,on)=='Ended':continue
        g=growth(conn,client['id']);started=date.fromisoformat(client['started_on'])
        due=[]
        if g['site_stage']=='Live' and not g['review_asked_on']:due.append('review')
        if g['site_stage']=='Live' and not g['testimonial_asked_on'] and on>=started+timedelta(days=TESTIMONIAL_AFTER_DAYS):due.append('testimonial')
        free=owed.get(client['id'],0)-g['free_months_used']
        import pitch
        cards.append(dict(client=dict(client),g=g,due=due,msg=messages(client,g,s,link),free_owed=max(0,free),
          portal=pitch.public_url(conn,owner,'client',client['id'])))
    conn.commit()
    leads=conn.execute("SELECT id,name FROM prospects WHERE owner_id=? AND referred_by IS NULL AND stage NOT IN ('Do not contact','Customer') ORDER BY id DESC LIMIT 200",(owner,)).fetchall()
    return dict(cards=cards,review_url=link,referrals=made,leads=leads,stages=STAGES,offer=REFERRAL_OFFER)


def portal_clients(conn,owner):
    on=client_plans.today()
    return [c for c in conn.execute('SELECT * FROM plan_clients WHERE owner_id=? ORDER BY id',(owner,)).fetchall() if client_plans.state(c,on)!='Ended']


def portal_data(conn,owner,client):
    """A client's private page: where their site is up to, their plan, change requests and invoices. No bank details on it."""
    import getpaid
    s=lead_engine.settings(conn,owner);g=growth(conn,client['id'])
    requests=conn.execute('SELECT request,status,created_at,done_at FROM plan_requests WHERE client_id=? ORDER BY id DESC LIMIT 12',(client['id'],)).fetchall()
    bills=conn.execute("SELECT number,description,total_cents,due_on,status FROM bills WHERE owner_id=? AND lower(client_name)=lower(?) AND status!='Cancelled' ORDER BY id DESC LIMIT 12",(owner,client['client_name'])).fetchall()
    plan=client_plans.PLANS[client['plan']]
    return dict(client=dict(client),g=g,s=s,stages=STAGES,step=STAGES.index(g['site_stage']) if g['site_stage'] in STAGES else 0,requests=[dict(r) for r in requests],
      bills=[dict(b) for b in bills],money=getpaid.money,monthly=getpaid.money(client_plans.monthly_value(client)),allowance=plan['allowance'],turnaround=plan['days'],
      ask='mailto:'+s['email']+'?subject='+_q('Change request: '+client['client_name']),year=lead_engine.today().year)


def _q(text):
    from urllib.parse import quote
    return quote(text)


def register(app,get_db,login_required):
    @app.post('/studio/clients/<int:client_id>/<action>')
    @login_required
    def grow_action(client_id,action):
        conn=get_db();owner=session['user_id'];client=client_plans.client_for(conn,owner,client_id);growth(conn,client_id);on=client_plans.today().isoformat()
        if action=='stage':
            stage=request.form.get('site_stage','');url=request.form.get('site_url','').strip()
            if stage not in STAGES:raise WorkflowError('Pick where their site is up to.')
            if url and not url.startswith('https://'):raise WorkflowError('Their site address should start with https://')
            conn.execute('UPDATE client_growth SET site_stage=?,site_url=? WHERE client_id=?',(stage,url[:300],client_id));msg='Updated. Their client page shows this next time you make a publish pack.'
        elif action in ('review','testimonial'):
            conn.execute('UPDATE client_growth SET '+action+'_asked_on=? WHERE client_id=?',(on,client_id));msg='Marked as asked.'
        elif action=='quote':
            text=' '.join(request.form.get('testimonial','').split())[:600]
            if text and request.form.get('ok')!='yes':raise WorkflowError('Tick that '+client['client_name']+' said you can show it on your website.')
            conn.execute('UPDATE client_growth SET testimonial=?,testimonial_ok=? WHERE client_id=?',(text,1 if text else 0,client_id))
            msg='Saved. It goes on your homepage with the next publish pack.' if text else 'Testimonial removed.'
        elif action=='free_month':
            conn.execute('UPDATE client_growth SET free_months_used=free_months_used+1 WHERE client_id=?',(client_id,));msg='Free month marked as given. Skip their next invoice.'
        else:raise WorkflowError('Unknown action.')
        log(conn,owner,'Studio: '+client['client_name']+' '+action+'.');conn.commit();flash(msg,'success')
        return redirect(url_for('studio')+'#k'+str(client_id))

    @app.post('/studio/referral')
    @login_required
    def grow_referral():
        conn=get_db();owner=session['user_id']
        client=client_plans.client_for(conn,owner,request.form.get('client_id',type=int) or 0)
        p=lead_engine.prospect_for(conn,owner,request.form.get('prospect_id',type=int) or 0)
        conn.execute('UPDATE prospects SET referred_by=? WHERE id=?',(client['id'],p['id']));lead_engine.record(conn,owner,p,'referred',client['client_name'])
        conn.commit();flash(p['name']+' is marked as referred by '+client['client_name']+'. If they sign, a free month shows here.','success')
        return redirect(url_for('studio')+'#referrals')

    @app.post('/studio/review-link')
    @login_required
    def grow_review_link():
        conn=get_db();owner=session['user_id'];url=request.form.get('review_url','').strip()
        if url and (not url.startswith('https://') or len(url)>300):raise WorkflowError('Paste your Google review link, starting with https://')
        conn.execute('INSERT INTO grow_settings(owner_id,review_url) VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET review_url=excluded.review_url',(owner,url))
        conn.commit();flash('Saved. Review requests now include your link.','success');return redirect(url_for('studio')+'#reviews')

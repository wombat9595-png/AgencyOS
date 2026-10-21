"""Pitch like a premium studio: proposal pages, private preview links, a 60 second video script,
a booking link, an instant phone ping when someone replies, and your own studio homepage with
niche pages.

Everything is made on this Mac. The "publish pack" is one zip the owner drags onto Cloudflare
Pages (free) when he says so; until then nothing is online. Preview and client pages sit at
long random addresses and are hidden from search engines.
"""
import io
import json
import os
import re
import secrets
import zipfile
from datetime import timedelta
from urllib import request as urlrequest,error as urlerror
from flask import Response,flash,redirect,render_template,request,session,url_for
from phase3_store import WorkflowError,stamp
from sales_store import log
import lead_engine
import playbook
import story_mockups

ROOT=os.path.dirname(os.path.abspath(__file__))
SITE_URL=re.compile(r'^https://[a-z0-9][a-z0-9.-]{1,120}\.[a-z]{2,}/?$')
BOOKING_URL=re.compile(r'^https://[A-Za-z0-9.-]+\.[a-z]{2,}/[^\s]{1,300}$')
PACK_STAGES=('New','Approved','Contacted','Interested')
PACK_LIMIT=80
NTFY='https://ntfy.sh/'
# Prices shown on proposals and the homepage (A$, before any GST).
OFFERS=(
 dict(name='Care',price='A$800',monthly='A$69 a month',line='A clean, fast site that looks sharp on phones, with hosting, security and small changes looked after.',points=('Up to 5 pages','Tap-to-call and quote form','Hosting, security and backups','Small changes each month')),
 dict(name='Autopilot',price='A$1,400',monthly='A$149 a month',line='Everything in Care, plus we keep it working for you every month.',points=('Everything in Care','Unlimited small changes','Monthly Google profile post','Priority turnaround')),
 dict(name='Signature',price='A$2,400',monthly='A$149 a month',line='An animated story site that shows your work as people scroll. The one people remember.',points=('Custom scroll story','Everything in Autopilot','Made around your best jobs','Founding price A$1,900 for the first three clients'),featured=True),
)


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS public_links (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('lead','client')), ref_id INTEGER NOT NULL,
      slug TEXT NOT NULL UNIQUE, packed_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(owner_id,kind,ref_id));
    ''')
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospect_settings)')}
    for column in ('booking_url','site_url','ntfy_topic'):
        if column not in columns:conn.execute('ALTER TABLE prospect_settings ADD COLUMN '+column+" TEXT NOT NULL DEFAULT ''")


def slug_for(conn,owner,kind,ref_id,create=True):
    row=conn.execute('SELECT slug FROM public_links WHERE owner_id=? AND kind=? AND ref_id=?',(owner,kind,ref_id)).fetchone()
    if row:return row['slug']
    if not create:return ''
    slug=secrets.token_urlsafe(12).replace('_','x').replace('-','y').lower()
    conn.execute('INSERT INTO public_links(owner_id,kind,ref_id,slug,created_at) VALUES(?,?,?,?,?)',(owner,kind,ref_id,slug,stamp()))
    return slug


def public_url(conn,owner,kind,ref_id):
    """The online address of a preview or client page, once it has gone into a publish pack and the site address is saved."""
    s=lead_engine.settings(conn,owner)
    row=conn.execute("SELECT slug FROM public_links WHERE owner_id=? AND kind=? AND ref_id=? AND packed_at!=''",(owner,kind,ref_id)).fetchone()
    if not row or not s.get('site_url'):return ''
    return s['site_url'].rstrip('/')+('/p/' if kind=='lead' else '/c/')+row['slug']+'/'


def preview_url(conn,owner,prospect_id):
    return public_url(conn,owner,'lead',prospect_id)


def mockup_url(p):
    story=playbook.story_for(p['trade'])
    return url_for('prospects_story' if story else 'prospects_mockup',prospect_id=p['id'])


def findings(p):
    check=json.loads(p['site_check']) if p['site_check'] else {}
    words={'not_mobile':'Does not fit phone screens, so visitors pinch and zoom','not_secure':'Browsers show "Not secure" next to it',
      'old':'Looks like it has not been updated since '+str(check.get('year') or 'a few years ago'),'down':'Did not load when we checked',
      'none':'No website we could find','facebook':'Only a Facebook page, which many people cannot see without logging in'}
    found=[words[f] for f in (check.get('findings') or [p['reason']]) if f in words]
    return found or ['A few quick wins to make it work harder for you']


def proposal_data(conn,owner,p,mockup_href):
    s=lead_engine.settings(conn,owner)
    subject='Your new website: '+p['name']
    body='Hi '+s['name'].split()[0]+',\n\nWe would like to go ahead with the [Care / Autopilot / Signature] package for '+p['name']+'.\n\nBest number to reach me: \n\nThanks'
    return dict(p=p,s=s,trade=(p['trade'] or 'local business').lower(),place=p['suburb'] or s['area'] or 'your area',findings=findings(p),angle=playbook.niche_angle(p['trade']),
      offers=OFFERS,mockup_href=mockup_href,story=playbook.story_for(p['trade']),booking=s.get('booking_url',''),
      accept='mailto:'+s['email']+'?subject='+_q(subject)+'&body='+_q(body),year=lead_engine.today().year,
      valid=(lead_engine.today()+timedelta(days=14)).strftime('%-d %B %Y'))


def _q(text):
    from urllib.parse import quote
    return quote(text)


def mockup_html(conn,owner,p):
    s=lead_engine.settings(conn,owner);story=playbook.story_for(p['trade'])
    if story:return story_mockups.render(p,s,story,inline=True)
    return render_template('mockup.html',m=lead_engine.mockup(p,s))


def video_script(p,s):
    """A 60 second screen-recording script about their site. The owner records it in QuickTime."""
    found=findings(p);me=s['name'].split()[0]
    return [
     ('0:00','Your face in the corner, their site (or Google search) on screen.','G\'day '+p['name']+' team, '+me+' here, a web designer'+(' in '+s['area'] if s['area'] else '')+'. I made this quick video just for you.'),
     ('0:10','Point at the first problem.',found[0]+'. '+lead_engine.why_it_matters(p)),
     ('0:30','Show the second thing, or scroll on a phone-sized window.',(found[1]+'.' if len(found)>1 else 'On a phone it is hard to find the number and tap to call.')+' That is usually where people give up and ring the next business.'),
     ('0:40','Open their free mock-up and scroll slowly.','So I went ahead and made you a free mock-up of what it could look like. '+('As you scroll, it tells the story of a job from start to finish.' if playbook.story_for(p['trade']) else 'Big tap-to-call button, your services up front, and it loads fast.')),
     ('0:55','Back to your face.','No cost to look and no obligation. Just reply to this email and I will send it over. Cheers.'),
    ]


def ping(conn,owner,title,message,click=''):
    """Buzz the owner's phone through the free ntfy app. Only to his own private topic; returns False if it is off or fails.
    click: the private phone address of AgencyOS to open when the notification is tapped."""
    s=lead_engine.settings(conn,owner);topic=s.get('ntfy_topic')
    if not topic:return False
    headers={'Title':title[:80].encode('ascii','ignore').decode(),'Tags':'telephone_receiver'}
    if click:headers['Click']=click
    req=urlrequest.Request(NTFY+topic,data=message[:300].encode(),headers=headers,method='POST')
    try:
        with urlrequest.urlopen(req,timeout=8):return True
    except (urlerror.URLError,OSError,ValueError):
        return False


def detect_replies(conn,owner,send=ping):
    """A lead wrote back: stop their follow-ups, put them top of the list and ping the owner's phone. Read-only on Gmail."""
    rows=conn.execute("""SELECT p.*,m.received_at FROM prospects p JOIN gmail_mail m ON lower(m.sender)=lower(p.email)
        WHERE p.owner_id=? AND m.owner_id=? AND m.direction='incoming' AND p.email!='' AND p.replied_at='' AND p.stage IN ('Approved','Contacted')
        AND m.received_at>=p.created_at GROUP BY p.id""",(owner,owner)).fetchall()
    for p in rows:
        conn.execute("UPDATE prospects SET replied_at=?,next_on=? WHERE id=?",(p['received_at'],lead_engine.today().isoformat(),p['id']))
        lead_engine.record(conn,owner,p,'replied')
        send(conn,owner,'A lead replied','Open AgencyOS and reply by email. Replying within the hour wins jobs.')
    conn.commit()
    return len(rows)


def niche_pages(conn,owner):
    """One page per search area: "Websites for builders in Mona Vale"."""
    pages=[];seen=set()
    try:beats=conn.execute('SELECT trade,town FROM night_shift_beats WHERE owner_id=? ORDER BY id',(owner,)).fetchall()
    except Exception:beats=[]
    for b in beats:
        town=re.sub(r'\s+(NSW|VIC|QLD|SA|WA|TAS|NT|ACT)$','',b['town'].strip(),flags=re.I)
        trade=b['trade'];short={'Gardeners and landscapers':'landscapers','Hairdressers and barbers':'hairdressers'}.get(trade,trade.lower())
        slug='websites-for-'+re.sub(r'[^a-z0-9]+','-',(short+' '+town).casefold()).strip('-')
        if slug in seen:continue
        seen.add(slug)
        pages.append(dict(slug=slug,trade=trade,short=short,town=town,angle=playbook.niche_angle(trade),story=playbook.story_for(trade)))
    return pages


def testimonials(conn,owner):
    try:return [dict(r) for r in conn.execute("SELECT c.client_name,g.testimonial FROM client_growth g JOIN plan_clients c ON c.id=g.client_id WHERE c.owner_id=? AND g.testimonial!='' AND g.testimonial_ok=1 ORDER BY g.client_id",(owner,))]
    except Exception:return []


def studio_data(conn,owner,prefix='',local=False):
    s=lead_engine.settings(conn,owner)
    demos=[dict(story,href=url_for('studio_demo',demo=story['demo']) if local else prefix+'demos/'+story['demo']+'/') for story in playbook.STORIES.values()]
    return dict(s=s,offers=OFFERS,demos=demos,niches=niche_pages(conn,owner),testimonials=testimonials(conn,owner),
      year=lead_engine.today().year,prefix=prefix,booking=s.get('booking_url',''),area=s['area'] or 'your area')


def pack_leads(conn,owner):
    import email_score
    rows=conn.execute("SELECT * FROM prospects WHERE owner_id=? AND stage IN ('New','Approved','Contacted','Interested') ORDER BY stage='Interested' DESC,score DESC,id LIMIT ?",(owner,PACK_LIMIT*3)).fetchall()
    return [p for p in rows if p['stage']!='New' or email_score.grade(p)=='A'][:PACK_LIMIT]


def publish_pack(conn,owner):
    """One zip with the homepage, niche pages, demos, every lead's preview and every client's page."""
    import grow
    out=io.BytesIO();z=zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED)
    data=studio_data(conn,owner)
    z.writestr('index.html',render_template('studio/home.html',**data))
    for page in data['niches']:
        z.writestr(page['slug']+'/index.html',render_template('studio/niche.html',page=page,**studio_data(conn,owner,'../')))
    for story in playbook.STORIES.values():
        with open(os.path.join(ROOT,'templates','stories',story['demo']+'.html'),encoding='utf-8') as handle:
            z.writestr('demos/'+story['demo']+'/index.html',handle.read())
    kit=os.path.join(ROOT,'static','motion')
    for folder,_dirs,files in os.walk(kit):
        for name in files:
            full=os.path.join(folder,name);rel=os.path.relpath(full,kit)
            z.write(full,rel)
    leads=pack_leads(conn,owner)
    for p in leads:
        slug=slug_for(conn,owner,'lead',p['id'])
        z.writestr('p/'+slug+'/index.html',render_template('proposal.html',**proposal_data(conn,owner,p,'site.html')))
        z.writestr('p/'+slug+'/site.html',mockup_html(conn,owner,p))
    clients=grow.portal_clients(conn,owner)
    for client in clients:
        slug=slug_for(conn,owner,'client',client['id'])
        z.writestr('c/'+slug+'/index.html',render_template('portal.html',**grow.portal_data(conn,owner,client)))
    z.writestr('robots.txt','User-agent: *\nDisallow: /p/\nDisallow: /c/\n')
    z.writestr('_headers','/p/*\n  X-Robots-Tag: noindex, nofollow\n  Referrer-Policy: no-referrer\n/c/*\n  X-Robots-Tag: noindex, nofollow\n  Referrer-Policy: no-referrer\n')
    z.writestr('README.txt','Upload this whole folder to Cloudflare Pages (free): dash.cloudflare.com > Workers & Pages > Create > Pages > Upload assets.\n'
      'Use the same project every time so the address stays the same. Then paste the address into AgencyOS > Studio > Online address.\n'
      'Preview pages (/p/) and client pages (/c/) have long random addresses and are hidden from Google.\n')
    z.close()
    now=stamp()
    for kind,items in (('lead',leads),('client',clients)):
        for item in items:conn.execute('UPDATE public_links SET packed_at=? WHERE owner_id=? AND kind=? AND ref_id=?',(now,owner,kind,item['id']))
    log(conn,owner,'Made a publish pack: homepage, '+str(len(data['niches']))+' niche pages, '+str(len(leads))+' previews, '+str(len(clients))+' client pages. Not uploaded.')
    conn.commit()
    return out.getvalue(),dict(niches=len(data['niches']),leads=len(leads),clients=len(clients))


def register(app,get_db,login_required):
    @app.get('/pitch/<int:prospect_id>/proposal')
    @login_required
    def pitch_proposal(prospect_id):
        conn=get_db();owner=session['user_id'];p=lead_engine.prospect_for(conn,owner,prospect_id)
        html=render_template('proposal.html',**proposal_data(conn,owner,p,mockup_url(p)))
        if request.args.get('download'):
            slug=re.sub(r'[^a-z0-9]+','-',p['name'].casefold()).strip('-') or 'proposal'
            html=render_template('proposal.html',**proposal_data(conn,owner,p,''))
            return Response(html,mimetype='text/html',headers={'Content-Disposition':'attachment; filename="'+slug+'-proposal.html"'})
        return html

    @app.get('/pitch/<int:prospect_id>/video')
    @login_required
    def pitch_video(prospect_id):
        conn=get_db();owner=session['user_id'];p=lead_engine.prospect_for(conn,owner,prospect_id);s=lead_engine.settings(conn,owner)
        return render_template('video_script.html',p=p,lines=video_script(p,s),mockup=mockup_url(p),preview=preview_url(conn,owner,p['id']))

    @app.get('/studio',strict_slashes=False)
    @login_required
    def studio():
        conn=get_db();owner=session['user_id'];s=lead_engine.settings(conn,owner)
        import grow
        packed=conn.execute("SELECT COUNT(*) FROM public_links WHERE owner_id=? AND packed_at!=''",(owner,)).fetchone()[0]
        last=conn.execute("SELECT MAX(packed_at) FROM public_links WHERE owner_id=?",(owner,)).fetchone()[0]
        return render_template('studio.html',s=s,niches=niche_pages(conn,owner),packed=packed,last=last,ready=len(pack_leads(conn,owner)),
          grow=grow.page_data(conn,owner))

    @app.get('/studio/site')
    @login_required
    def studio_site():
        conn=get_db();owner=session['user_id']
        return render_template('studio/home.html',**studio_data(conn,owner,local=True))

    @app.get('/studio/demo/<demo>')
    @login_required
    def studio_demo(demo):
        story=next((x for x in playbook.STORIES.values() if x['demo']==demo),None)
        if not story:raise WorkflowError('That demo does not exist.')
        page=story_mockups._read(ROOT,'templates','stories',demo+'.html').replace('../../kit/',url_for('static',filename='motion/kit/'))
        return page.replace('src="scene.js"','src="'+url_for('static',filename='motion/demos/'+demo+'/scene.js')+'"')

    @app.get('/studio/site/<slug>')
    @login_required
    def studio_niche(slug):
        conn=get_db();owner=session['user_id']
        page=next((n for n in niche_pages(conn,owner) if n['slug']==slug),None)
        if not page:raise WorkflowError('That page is not in your list. Add a search area on the Night shift page.')
        data=studio_data(conn,owner,local=True);data['home']=url_for('studio_site')
        return render_template('studio/niche.html',page=page,**data)

    @app.post('/studio/settings')
    @login_required
    def studio_settings():
        conn=get_db();owner=session['user_id']
        booking=request.form.get('booking_url','').strip();site=request.form.get('site_url','').strip().lower()
        if booking and (len(booking)>300 or not BOOKING_URL.match(booking)):raise WorkflowError('Paste the full booking link, starting with https://')
        if site and not SITE_URL.match(site):raise WorkflowError('Paste the address Cloudflare gave you, like https://benji-web.pages.dev')
        lead_engine.settings(conn,owner)
        conn.execute("INSERT OR IGNORE INTO prospect_settings(owner_id,name,business,email) VALUES(?,?,?,?)",(owner,'Benji Price','Benji Price Web Design',lead_engine.settings(conn,owner)['email']))
        conn.execute('UPDATE prospect_settings SET booking_url=?,site_url=? WHERE owner_id=?',(booking,site.rstrip('/'),owner))
        conn.commit();flash('Saved.','success');return redirect(url_for('studio'))

    @app.post('/studio/ping')
    @login_required
    def studio_ping():
        conn=get_db();owner=session['user_id'];action=request.form.get('action','')
        conn.execute("INSERT OR IGNORE INTO prospect_settings(owner_id,name,business,email) VALUES(?,?,?,?)",(owner,'Benji Price','Benji Price Web Design',lead_engine.settings(conn,owner)['email']))
        if action=='on':
            topic='agencyos-'+secrets.token_hex(8)
            conn.execute('UPDATE prospect_settings SET ntfy_topic=? WHERE owner_id=?',(topic,owner));conn.commit()
            flash('Phone pings are on. In the ntfy app, tap + and subscribe to: '+topic,'success')
        elif action=='off':
            conn.execute("UPDATE prospect_settings SET ntfy_topic='' WHERE owner_id=?",(owner,));conn.commit();flash('Phone pings are off.','success')
        elif action=='test':
            flash('Test ping sent. Check your phone.' if ping(conn,owner,'AgencyOS test','If you can read this, reply pings work.') else 'The ping did not go through. Check the topic in the ntfy app and your internet.','success')
        else:raise WorkflowError('Unknown action.')
        return redirect(url_for('studio')+'#pings')

    @app.get('/studio/pack.zip')
    @login_required
    def studio_pack():
        conn=get_db();owner=session['user_id'];blob,_counts=publish_pack(conn,owner)
        return Response(blob,mimetype='application/zip',headers={'Content-Disposition':'attachment; filename="agencyos-publish-pack.zip"'})

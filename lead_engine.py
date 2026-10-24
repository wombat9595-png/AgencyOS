"""Find local businesses that need a website, draft outreach, track follow-ups.

Free sources only: OpenStreetMap (Nominatim + Overpass) and a one-page check of each
business's own homepage. Nothing is ever sent from here: the owner approves each
draft and sends it from their own email. Email only: AgencyOS never makes or plans cold calls.
"""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta
from urllib import parse,request as urlrequest,error as urlerror
from urllib.parse import urlsplit,urljoin,quote,unquote
from zoneinfo import ZoneInfo
from flask import Response,flash,redirect,render_template,request,session,url_for
from phase3_store import WorkflowError,stamp
from sales_store import log
import gmail_agent

NOMINATIM='https://nominatim.openstreetmap.org/search'
OVERPASS='https://overpass-api.de/api/interpreter'
ATTRIBUTION='Business data © OpenStreetMap contributors (ODbL)'
# Trades that usually buy small-business websites, mapped to OpenStreetMap tags.
TRADES={
 'Plumbers':[('craft','plumber')],'Electricians':[('craft','electrician')],'Builders':[('craft','builder')],
 'Carpenters':[('craft','carpenter')],'Painters':[('craft','painter')],'Roofers':[('craft','roofer')],
 'Gardeners and landscapers':[('craft','gardener')],'Mechanics':[('shop','car_repair')],
 'Hairdressers and barbers':[('shop','hairdresser')],'Beauty salons':[('shop','beauty')],
 'Cafes':[('amenity','cafe')],'Restaurants':[('amenity','restaurant')],'Bakeries':[('shop','bakery')],
 'Florists':[('shop','florist')],'Dentists':[('amenity','dentist')],'Physios':[('healthcare','physiotherapist')],
 'Vets':[('amenity','veterinary')],'Gyms':[('leisure','fitness_centre')],'Tattoo studios':[('shop','tattoo')],
}
RADII=(5,10,25,50)
STAGES=('New','Approved','Contacted','Interested','Customer','Not interested','No reply','Do not contact','Skipped')
CLOSED=('Customer','Not interested','No reply','Do not contact','Skipped')
FOLLOW_UP_DAYS=(4,6,7)  # after the first message, after follow-up 1, after follow-up 2 (then No reply)
REASONS={
 'facebook':(85,'Only has a Facebook page'),'none':(80,'No website listed'),'down':(80,'Website did not load'),
 'not_mobile':(75,'Website does not fit phones'),'not_secure':(70,'Website shows "Not secure"'),
 'old':(60,'Website looks out of date'),'unchecked':(50,'Website not checked yet'),'ok':(15,'Website looks fine'),
}
UA='AgencyOS/1.0 (one-person web design business; contact: {})'


def today():
    return datetime.now(ZoneInfo('Australia/Sydney')).date()


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS prospects (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL, trade TEXT NOT NULL DEFAULT '',
      suburb TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
      website TEXT NOT NULL DEFAULT '', facebook TEXT NOT NULL DEFAULT '', site_check TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL DEFAULT '',
      reason TEXT NOT NULL DEFAULT 'unchecked', score INTEGER NOT NULL DEFAULT 50, stage TEXT NOT NULL DEFAULT 'New',
      subject TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '', touches INTEGER NOT NULL DEFAULT 0,
      next_on TEXT NOT NULL DEFAULT '', last_contact_on TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', lead_id INTEGER,
      created_at TEXT NOT NULL, UNIQUE(owner_id,source_id));
    CREATE TABLE IF NOT EXISTS prospect_log (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, prospect_id INTEGER NOT NULL REFERENCES prospects(id),
      on_date TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS prospect_settings (
      owner_id INTEGER PRIMARY KEY, name TEXT NOT NULL, business TEXT NOT NULL, email TEXT NOT NULL,
      phone TEXT NOT NULL DEFAULT '', area TEXT NOT NULL DEFAULT '', daily_target INTEGER NOT NULL DEFAULT 10);
    CREATE TABLE IF NOT EXISTS geo_cache (query TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL, label TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS prospects_stage_idx ON prospects(owner_id,stage);
    ''')
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospects)')}
    if 'ceo_status' not in columns:
        # The CEO's verdict on the current draft: '' not reviewed, ready, held (failed the rules), redo (owner sent it back).
        conn.execute("ALTER TABLE prospects ADD COLUMN ceo_status TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE prospects ADD COLUMN ceo_note TEXT NOT NULL DEFAULT ''")
    if 'gmail_draft_id' not in columns:
        conn.execute("ALTER TABLE prospects ADD COLUMN gmail_draft_id TEXT NOT NULL DEFAULT ''")
        conn.execute('ALTER TABLE prospects ADD COLUMN approved_epoch INTEGER NOT NULL DEFAULT 0')


def best_subject(conn,owner,minimum=15):
    """The first-email subject line that gets the most yeses, once every line has had a fair go."""
    try:
        rows=conn.execute("SELECT variant,COUNT(*) n,SUM(stage IN ('Interested','Customer')) yes FROM prospects WHERE owner_id=? AND variant!='' GROUP BY variant",(owner,)).fetchall()
    except Exception:
        return ''
    stats={r['variant']:(r['yes'] or 0)/r['n'] for r in rows if r['variant'] in SUBJECTS and r['n']>=minimum}
    if len(stats)<len(SUBJECTS):return ''
    ranked=sorted(stats.items(),key=lambda kv:-kv[1])
    return ranked[0][0] if ranked[0][1]>ranked[1][1] else ''


def settings(conn,owner):
    row=conn.execute('SELECT * FROM prospect_settings WHERE owner_id=?',(owner,)).fetchone()
    if row:return dict(row,best_subject=best_subject(conn,owner))
    import gmail_agent
    return dict(best_subject=best_subject(conn,owner),owner_id=owner,name='Benji Price',business='Benji Price Web Design',email=gmail_agent.ACCOUNT,phone='',area='',daily_target=10,
      call_target=5,booking_url='',site_url='',ntfy_topic='',card_link='',debit_link='')


# ---------- Finding businesses (OpenStreetMap, free) ----------

def http_json(url,data,contact):
    req=urlrequest.Request(url,data=data,headers={'User-Agent':UA.format(contact),'Accept':'application/json'})
    try:
        with urlrequest.urlopen(req,timeout=40) as response:
            body=response.read(5_000_001)
        if len(body)>5_000_000:raise WorkflowError('The map service sent back too much data. Try a smaller radius.')
        return json.loads(body)
    except urlerror.HTTPError as exc:
        if exc.code in (429,504):raise WorkflowError('The free map service is busy right now. Wait a minute and try again.') from None
        raise WorkflowError('The map service returned an error ('+str(exc.code)+'). Nothing was added.') from None
    except (urlerror.URLError,OSError,ValueError):
        raise WorkflowError('Could not reach the free map service. Check your internet connection and try again. Nothing was added.') from None


def geocode(conn,town,contact):
    key=' '.join(town.casefold().split())
    row=conn.execute('SELECT * FROM geo_cache WHERE query=?',(key,)).fetchone()
    if row:return row['lat'],row['lon'],row['label']
    found=http_json(NOMINATIM+'?'+parse.urlencode({'q':town,'format':'jsonv2','limit':1,'countrycodes':'au'}),None,contact)
    if not isinstance(found,list) or not found:raise WorkflowError('Could not find "'+town+'" in Australia. Try the suburb and state, like "Penrith NSW".')
    lat,lon,label=float(found[0]['lat']),float(found[0]['lon']),str(found[0].get('display_name',town))[:200]
    conn.execute('INSERT OR REPLACE INTO geo_cache VALUES(?,?,?,?,?)',(key,lat,lon,label,stamp()));conn.commit()
    return lat,lon,label


def overpass_query(trade,lat,lon,radius_km):
    parts=''.join(f'nwr["{k}"="{v}"]["name"](around:{radius_km*1000},{lat:.5f},{lon:.5f});' for k,v in TRADES[trade])
    return f'[out:json][timeout:30];({parts});out center tags 300;'


def clean_url(value):
    value=(value or '').strip().split(';')[0].strip()
    if not value or len(value)>300 or any(c.isspace() for c in value):return ''
    if not re.match(r'https?://',value,re.I):value='https://'+value
    try:
        parts=urlsplit(value)
        if not parts.hostname or '.' not in parts.hostname or parts.username or parts.password:return ''
    except ValueError:return ''
    return value


def clean_email(value):
    value=(value or '').strip().split(';')[0].strip()
    return value if re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+',value) and len(value)<=254 else ''


def from_osm(element,trade):
    tags=element.get('tags') or {}
    name=' '.join(str(tags.get('name','')).split())[:160]
    if not name:return None
    get=lambda *keys:next((str(tags[k]) for k in keys if tags.get(k)),'')
    website=clean_url(get('website','contact:website','url'))
    facebook=clean_url(get('contact:facebook','facebook'))
    if website and 'facebook.com' in (urlsplit(website).hostname or ''):facebook,website=website,''
    suburb=get('addr:suburb','addr:city','addr:town','addr:place')
    street=' '.join(p for p in (get('addr:housenumber'),get('addr:street')) if p)
    address=', '.join(p for p in (street,suburb,get('addr:state'),get('addr:postcode')) if p)
    return dict(source_id='osm:'+str(element.get('type'))+'/'+str(element.get('id')),name=name,trade=trade,suburb=suburb[:100],address=address[:250],
                phone=get('phone','contact:phone','contact:mobile','mobile')[:60].split(';')[0].strip(),email=clean_email(get('email','contact:email')),
                website=website,facebook=facebook)


def norm(value):
    return re.sub(r'\W+','',(value or '').casefold())


def find(conn,owner,trade,town,radius_km):
    if trade not in TRADES:raise WorkflowError('Pick a trade from the list.')
    if radius_km not in RADII:raise WorkflowError('Pick a search distance.')
    town=' '.join(town.split())
    if not 2<=len(town)<=100:raise WorkflowError('Type a suburb or town, like "Penrith NSW".')
    contact=settings(conn,owner)['email']
    lat,lon,label=geocode(conn,town,contact)
    found=http_json(OVERPASS,parse.urlencode({'data':overpass_query(trade,lat,lon,radius_km)}).encode(),contact)
    if not isinstance(found,dict) or not isinstance(found.get('elements'),list):raise WorkflowError('The map service sent back something unexpected. Nothing was added.')
    added,already=add_rows(conn,owner,[from_osm(e,trade) for e in found['elements']],town)
    log(conn,owner,'Found '+str(len(added))+' new '+trade.lower()+' near '+town+' on OpenStreetMap. Nothing was sent.')
    conn.commit()
    return dict(added=added,already=already,label=label)


def add_rows(conn,owner,rows,fallback_suburb):
    """Save new businesses, skipping any already in the list (same map id, or same name in the same suburb)."""
    existing={(norm(r['name']),norm(r['suburb'])) for r in conn.execute('SELECT name,suburb FROM prospects WHERE owner_id=?',(owner,))}
    known={r[0] for r in conn.execute('SELECT source_id FROM prospects WHERE owner_id=?',(owner,))}
    added=[];already=0
    for row in rows:
        if not row:continue
        if row['source_id'] in known or (norm(row['name']),norm(row['suburb'])) in existing:already+=1;continue
        known.add(row['source_id']);existing.add((norm(row['name']),norm(row['suburb'])))
        row['suburb']=row['suburb'] or fallback_suburb
        reason='facebook' if row['facebook'] and not row['website'] else 'none' if not row['website'] else 'unchecked'
        cur=conn.execute('INSERT INTO prospects(owner_id,source_id,name,trade,suburb,address,phone,email,website,facebook,reason,score,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (owner,row['source_id'],row['name'],row['trade'],row['suburb'],row['address'],row['phone'],row['email'],row['website'],row['facebook'],reason,0,stamp()))
        rescore(conn,cur.lastrowid);added.append(cur.lastrowid)
    return added,already


def add_manual(conn,owner,form):
    row={k:' '.join(form.get(k,'').split()) for k in ('name','trade','suburb','phone','email','website','notes')}
    if not 1<=len(row['name'])<=160 or any(len(v)>300 for v in row.values()):raise WorkflowError('Add at least the business name (keep each field short).')
    if row['email'] and not clean_email(row['email']):raise WorkflowError('That email address does not look right.')
    website=clean_url(row['website']) if row['website'] else ''
    if row['website'] and not website:raise WorkflowError('That website address does not look right.')
    facebook=''
    if website and 'facebook.com' in (urlsplit(website).hostname or ''):facebook,website=website,''
    if (norm(row['name']),norm(row['suburb'])) in {(norm(r['name']),norm(r['suburb'])) for r in conn.execute('SELECT name,suburb FROM prospects WHERE owner_id=?',(owner,))}:
        raise WorkflowError(row['name']+' is already in your list.')
    reason='facebook' if facebook else 'none' if not website else 'unchecked'
    cur=conn.execute('INSERT INTO prospects(owner_id,source_id,name,trade,suburb,phone,email,website,facebook,notes,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      (owner,'manual:'+stamp(),row['name'],row['trade'],row['suburb'],row['phone'],clean_email(row['email']),website,facebook,row['notes'],reason,stamp()))
    rescore(conn,cur.lastrowid)
    return cur.lastrowid


# ---------- Checking a business's homepage (one request, public addresses only) ----------

class _Pinned(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):
        super().__init__(host,timeout=timeout,context=ssl.create_default_context());self.address=address
    def connect(self):
        raw=socket.create_connection((self.address,443),self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:raw.close();raise


def _get(url,timeout=8):
    """GET one page from a public address. Returns (status, location, body). Raises OSError on failure."""
    parts=urlsplit(url);host=parts.hostname or ''
    port=443 if parts.scheme=='https' else 80
    if parts.port not in (None,port):raise OSError('custom port')
    addresses={a[4][0] for a in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise OSError('not a public address')
    address=sorted(addresses)[0]
    conn=_Pinned(host,address,timeout) if parts.scheme=='https' else http.client.HTTPConnection(address,80,timeout=timeout)
    try:
        conn.request('GET',(parts.path or '/'),headers={'Host':host,'User-Agent':'Mozilla/5.0 (AgencyOS website check)','Accept':'text/html','Accept-Encoding':'identity'})
        response=conn.getresponse()
        return response.status,response.getheader('Location',''),response.read(600_000)
    finally:conn.close()


def check_site(url,get=None):
    """Look at the homepage like a visitor would. Returns findings; never raises."""
    get=get or _get
    origin=urlsplit(url);host=origin.hostname or ''
    result=dict(url=url,loaded=False,https=False,mobile=False,year=0,title='',findings=[])
    def follow(target):
        for _ in range(4):
            status,location,body=get(target)
            if 300<=status<400 and location:
                target=urljoin(target,location)
                if urlsplit(target).scheme not in ('http','https'):raise OSError('bad redirect')
                continue
            return status,target,body
        raise OSError('too many redirects')
    try:
        status,final,body=follow('https://'+host+'/')
    except (OSError,ssl.SSLError,http.client.HTTPException,ValueError):
        try:status,final,body=follow('http://'+host+'/')
        except (OSError,ssl.SSLError,http.client.HTTPException,ValueError):
            result['findings']=['down'];return result
    if status>=400:result['findings']=['down'];return result
    html=body.decode('utf-8','replace');lower=html.casefold()
    result.update(loaded=True,https=urlsplit(final).scheme=='https',mobile=bool(re.search(r'<meta[^>]+name=["\']?viewport',lower)))
    title=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S)
    result['title']=' '.join(title.group(1).split())[:150] if title else ''
    years=[int(y) for y in re.findall(r'(?:©|&copy;|copyright)\s*(?:\d{4}\s*(?:-|–|&ndash;)\s*)?((?:19|20)\d\d)',lower)]
    result['year']=max(years) if years else 0
    result['seo']=seo_notes(html,lower)
    result['email']=find_email(html,host)
    if result['email']:result['email_page']=final
    else:result['email'],result['email_page'],page_says_no=contact_email(html,final,host,follow);result['no_marketing']=page_says_no
    result['no_marketing']=result.get('no_marketing') or says_no_marketing(lower)
    if result['no_marketing']:result['email']=''  # Spam Act: a published address only counts as consent if the site doesn't refuse marketing emails
    if not result['https']:result['findings'].append('not_secure')
    if not result['mobile']:result['findings'].append('not_mobile')
    if result['year'] and result['year']<=today().year-4:result['findings'].append('old')
    if not result['findings']:result['findings']=['ok']
    return result


CONTACT_LINK=re.compile(r'<a[^>]+href=["\']([^"\'#]*contact[^"\'#]*)["\']',re.I)
ABOUT_LINK=re.compile(r'<a[^>]+href=["\']([^"\'#]*about[^"\'#]*)["\']',re.I)
NO_MARKETING=re.compile(r"\b(?:no|not accept\w*|do not (?:send|want)|don't (?:send|want)|please do not send)\s+(?:any\s+)?"
                      r"(?:unsolicited\b|solicit\w*|(?:marketing|sales|spam|cold|advertising)\s+(?:e-?mails?|messages?|offers?|enquiries|pitch\w*))"
                      r"|\bunsolicited\s+(?:\w+\s+){0,2}(?:e-?mails?|messages?|offers?)\s+(?:\w+\s+){0,2}(?:not|never)\s+(?:be\s+)?(?:accepted|welcome|wanted|read|answered)",re.I)


def says_no_marketing(text):
    """True when a page asks for no unsolicited or marketing emails, e.g. "No unsolicited emails please"."""
    return bool(NO_MARKETING.search(re.sub(r'<[^>]+>',' ',text)))


def contact_email(html,base,host,follow):
    """Most small business sites keep their email on the Contact page, else the About page. Reads at most two pages.
    Returns (email, page it was published on, whether that page refuses marketing emails)."""
    own=(host or '').casefold().removeprefix('www.')
    def same_site(links):
        links=[urljoin(base,h) for h in links]
        return [u for u in links if urlsplit(u).scheme in ('http','https') and (urlsplit(u).hostname or '').casefold().removeprefix('www.')==own]
    contact=same_site(CONTACT_LINK.findall(html))[:1] or [urljoin(base,'/contact'),urljoin(base,'/contact-us')]
    for url in contact+same_site(ABOUT_LINK.findall(html))[:1]:
        try:status,final,body=follow(url)
        except (OSError,ssl.SSLError,http.client.HTTPException,ValueError):continue
        if status<400:
            page=body.decode('utf-8','replace')
            email=find_email(page,host)
            if email:return email,final,says_no_marketing(page)
    return '','',False


EMAIL_IN_PAGE=re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
JUNK_EMAIL=('example.','sentry','wixpress','godaddy','domain.com','yourdomain','email.com','@2x','.png','.jpg','.jpeg','.gif','.webp','.svg')


def find_email(html,host=''):
    """The business's own email from its homepage: a mailto link first, then plain text. Prefers an address on their own domain."""
    found=[unquote(m).split('?')[0] for m in re.findall(r'mailto:([^"\'\s>]+)',html,re.I)]+EMAIL_IN_PAGE.findall(html)
    good=[]
    for e in found:
        e=clean_email(e.strip().strip('.').casefold())
        if e and not any(j in e for j in JUNK_EMAIL) and e not in good:good.append(e)
    own=(host or '').casefold().removeprefix('www.')
    return next((e for e in good if own and e.endswith('@'+own)),good[0] if good else '')


SEO_NOTES={
 'no_description':'no Google description (meta description), so Google makes one up',
 'no_h1':'no main heading on the homepage',
 'no_tap_to_call':'no tap-to-call phone link',
 'no_local_schema':'no "local business" details for Google (schema)',
 'thin_title':'the page title does not say what they do or where',
}


def seo_notes(html,lower):
    """The SEO Checker: simple things Google and phone visitors look for. Keys of SEO_NOTES."""
    notes=[]
    if not re.search(r'<meta[^>]+name=["\']?description["\']?[^>]+content=["\'][^"\']{20,}',lower):notes.append('no_description')
    if '<h1' not in lower:notes.append('no_h1')
    if 'href="tel:' not in lower and "href='tel:" not in lower:notes.append('no_tap_to_call')
    if 'localbusiness' not in lower and '"@type":' not in lower.replace(' ',''):notes.append('no_local_schema')
    title=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S)
    if not title or len(title.group(1).split())<3:notes.append('thin_title')
    return notes


def rescore(conn,prospect_id):
    p=conn.execute('SELECT * FROM prospects WHERE id=?',(prospect_id,)).fetchone()
    reason=p['reason']
    if p['site_check']:
        findings=json.loads(p['site_check'])['findings']
        reason=max(findings,key=lambda f:REASONS[f][0])
    score=REASONS[reason][0]+(5 if p['phone'] else 0)+(5 if p['email'] else 0)
    conn.execute('UPDATE prospects SET reason=?,score=? WHERE id=?',(reason,min(score,100),prospect_id))


def check_websites(conn,owner,limit=15,get=None):
    rows=conn.execute("SELECT id,website,email FROM prospects WHERE owner_id=? AND website!='' AND checked_at='' AND stage='New' ORDER BY id LIMIT ?",(owner,limit)).fetchall()
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda r:check_site(r['website'],get),rows))
    for row,result in zip(rows,results):
        conn.execute('UPDATE prospects SET site_check=?,checked_at=? WHERE id=?',(json.dumps(result),stamp(),row['id']))
        if not row['email'] and result.get('email'):conn.execute('UPDATE prospects SET email=? WHERE id=?',(result['email'],row['id']))  # the Inspector found their email on their own site; site_check keeps the page and date as proof
        if result.get('no_marketing'):conn.execute("UPDATE prospects SET stage='Do not contact',notes=TRIM(notes||' Their website asks for no unsolicited emails.') WHERE id=?",(row['id'],))
        rescore(conn,row['id'])
    conn.commit()
    return len(rows)


# ---------- Drafting messages (rule-based; the owner edits and sends) ----------

def problem_line(p):
    check=json.loads(p['site_check']) if p['site_check'] else {}
    domain=(urlsplit(p['website']).hostname or '').removeprefix('www.') if p['website'] else ''
    lines=[]
    for f in (check.get('findings') or [p['reason']]):
        if f=='not_mobile':lines.append('on my phone it does not resize, so visitors have to pinch and zoom to read it')
        elif f=='not_secure':lines.append('browsers flag it as "Not secure" because it does not use HTTPS')
        elif f=='old':lines.append('it looks like it has not been updated since '+str(check['year']))
        elif f=='down':lines.append('it did not load when I tried it')
    if p['reason']=='facebook':return 'I could only find a Facebook page for '+p['name']+', not a website.'
    if p['reason'] in ('none','unchecked') or not lines:
        return 'I could not find a website for '+p['name']+'.' if not p['website'] else 'I had a look at '+domain+'.'
    return 'I had a look at '+domain+' and '+' and '.join(lines[:2])+'.'


def why_it_matters(p):
    if p['reason'] in ('none','facebook','down'):
        return 'Most people check online before they pick a local business, and a simple site with your services, photos, reviews and a tap-to-call button usually brings in extra customers.'
    return 'Most of your visitors are on their phone, so a site that loads fast, looks sharp and has a tap-to-call button usually turns more of them into calls.'


# First-email subject lines. Each lead gets one in turn; once one clearly wins (see phone.learn),
# most new leads get the winner and the rest keep testing.
SUBJECTS=('Website for {name}?','Quick idea for {name}','Made {name} a free website preview')


def subject_for(p,s):
    pid=p['id'] if 'id' in p.keys() else 0
    best=s.get('best_subject')
    pick=best if best in SUBJECTS and pid%5 else SUBJECTS[pid%len(SUBJECTS)]
    return pick.format(name=p['name'])


def variant_of(subject,name):
    for pattern in SUBJECTS:
        if subject==pattern.format(name=name):return pattern
    return 'Your own subject'


def draft(p,s,kind=None,short=False):
    """Return (subject, body). kind: first, followup1, followup2. short: the owner taught the Writer to keep it brief."""
    kind=kind or ('first','followup1','followup2')[min(p['touches'],2)]
    me=s['name'].split()[0];area=' based in '+s['area'] if s['area'] else ' here in Australia'
    sign='\n\nCheers,\n'+s['name']+'\n'+s['business']+'\n'+s['email']+('\n'+s['phone'] if s['phone'] else '')
    optout='\n\nIf you would rather not hear from me, just reply "no thanks" and I will not contact you again.'
    hello='Hi '+p['name']+' team,'
    if kind=='first' and short:
        return (subject_for(p,s),
          hello+'\n\nI am '+me+', a web designer'+area+'. '+problem_line(p)+'\n\n'
          'Can I make '+p['name']+' a free one-page mock-up? No cost, no obligation. Just reply "yes".'+sign+optout)
    if kind=='first':
        return (subject_for(p,s),
          hello+'\n\nI am '+me+', a web designer'+area+'. '+problem_line(p)+'\n\n'+why_it_matters(p)+'\n\n'
          'I would be happy to put together a free one-page mock-up for '+p['name']+' so you can see what it would look like. No cost and no obligation.\n\n'
          'Worth a look? Just reply "yes" and I will send it over this week.'+sign+optout)
    if kind=='followup1':
        return ('Re: Website for '+p['name']+'?',
          hello+'\n\nJust following up on my note from last week. The offer of a free one-page mock-up for '+p['name']+' still stands, and it only takes me a couple of days.\n\n'
          'Reply "yes" and I will get started.'+sign+optout)
    return ('Re: Website for '+p['name']+'?',
      hello+'\n\nLast note from me, I promise. If a new website is not a priority right now, no worries at all. If it ever is, reply to this email and I will put that free mock-up together.'+sign+optout)


# ---------- Free one-page mock-up ----------
# Generic copy per trade so the mock-up is ready in one tap. Benji edits anything before sending.
MOCKUP={
 'Plumbers':('#0b5fa5',['Blocked drains','Hot water systems','Leaking taps and toilets','Gas fitting','Bathroom and kitchen plumbing','Emergency call-outs']),
 'Electricians':('#c77700',['Power points and lighting','Switchboard upgrades','Safety switches','Ceiling fans and air con','Smoke alarms','Emergency call-outs']),
 'Builders':('#6b4f2a',['Renovations','Extensions','Decks and pergolas','New homes','Bathrooms and kitchens','Repairs and maintenance']),
 'Carpenters':('#7a5230',['Decks and pergolas','Doors and windows','Custom shelving','Framing','Repairs','Renovation carpentry']),
 'Painters':('#2f7d6d',['Interior painting','Exterior painting','Roof painting','Feature walls','Commercial painting','Colour advice']),
 'Roofers':('#8a3b2e',['Roof repairs','Re-roofing','Gutter replacement','Roof restoration','Leak detection','Storm damage']),
 'Gardeners and landscapers':('#3d7a2a',['Garden makeovers','Lawn mowing','Hedging and pruning','Paving and retaining walls','Turf laying','Green waste removal']),
 'Mechanics':('#333d47',['Logbook servicing','Brakes and clutches','Tyres and wheel alignment','Diagnostics','Rego inspections','Air con regas']),
 'Hairdressers and barbers':('#8c4a7a',['Cuts and styling','Colour and foils','Fades and beard trims','Blow-waves','Treatments','Kids cuts']),
 'Beauty salons':('#b0577d',['Facials','Brows and lashes','Waxing','Nails','Spray tans','Skin treatments']),
 'Cafes':('#7b4b2a',['Specialty coffee','All-day breakfast','Lunch menu','Fresh pastries','Takeaway','Catering']),
 'Restaurants':('#9b2f2f',['Dine in','Takeaway','Functions','Set menus','Seasonal specials','Gift vouchers']),
 'Bakeries':('#a8742c',['Fresh bread daily','Pies and sausage rolls','Cakes to order','Pastries','Coffee','Wholesale']),
 'Florists':('#b5527a',['Bouquets','Same-day delivery','Weddings','Sympathy flowers','Events','Plants and gifts']),
 'Dentists':('#1f7a8c',['Check-ups and cleans','Fillings','Teeth whitening','Children\'s dentistry','Emergency dental','Payment plans']),
 'Physios':('#2a6f97',['Sports injuries','Back and neck pain','Post-surgery rehab','Dry needling','Pilates','Health fund rebates']),
 'Vets':('#3a7d44',['Check-ups and vaccinations','Desexing','Dental care','Surgery','Puppy and kitten packs','After-hours advice']),
 'Gyms':('#c0392b',['Memberships','Personal training','Group classes','24/7 access','Strength and conditioning','Free trial']),
 'Tattoo studios':('#222222',['Custom designs','Fine line','Black and grey','Colour work','Cover-ups','Walk-ins']),
}


def mockup(p,s):
    colour,services=MOCKUP.get(p['trade'],('#1d4f91',['Service one','Service two','Service three','Quotes','Local and reliable','Friendly team']))
    trade=p['trade'] if p['trade'] in MOCKUP else 'local business'
    place=p['suburb'] or s['area'] or 'your area'
    return dict(name=p['name'],trade=trade,place=place,colour=colour,services=services,phone=p['phone'],email=p['email'],
      tel=re.sub(r'[^0-9+]','',p['phone']),maker=s['business'],maker_email=s['email'],year=today().year)


def mailto(p,subject,body):
    return 'mailto:'+quote(p['email'])+'?subject='+quote(subject)+'&body='+quote(body)


# ---------- Pipeline ----------

def record(conn,owner,p,action,detail=''):
    conn.execute('INSERT INTO prospect_log(owner_id,prospect_id,on_date,action,detail,created_at) VALUES(?,?,?,?,?,?)',(owner,p['id'],today().isoformat(),action,detail[:500],stamp()))


def expire(conn,owner,on=None):
    """After the second follow-up has had a week, stop chasing."""
    on=(on or today()).isoformat()
    conn.execute("UPDATE prospects SET stage='No reply',next_on='' WHERE owner_id=? AND stage='Contacted' AND replied_at='' AND touches>=3 AND next_on!='' AND next_on<=?",(owner,on))


def daily_target(conn,owner):
    """One daily email number for the whole app: the Deliverability Guard's safe number (warm-up included)."""
    try:
        import team
        return team.safe_daily(conn,owner)
    except Exception:
        return settings(conn,owner)['daily_target']


def counts(conn,owner,on=None):
    on=on or today();iso=on.isoformat();expire(conn,owner,on)
    def n(where,args=()):return conn.execute('SELECT COUNT(*) FROM prospects WHERE owner_id=? AND '+where,(owner,)+args).fetchone()[0]
    return dict(total=n('1'),
      to_review=n("stage='New' AND score>=50 AND email!=''"),
      ready=n("stage='Approved'"),
      follow_ups=n("stage='Contacted' AND replied_at='' AND next_on!='' AND next_on<=?",(iso,)),
      contacted_today=conn.execute("SELECT COUNT(DISTINCT prospect_id) FROM prospect_log WHERE owner_id=? AND on_date=? AND action='sent'",(owner,iso)).fetchone()[0],
      contacted=n("touches>0"),interested=n("stage='Interested'"),customers=n("stage='Customer'"),
      waiting=n("stage='Contacted' AND (next_on='' OR next_on>?)",(iso,)),
      target=daily_target(conn,owner))


def queue(conn,owner,on=None,limit=12):
    """Today's work, most urgent first: follow-ups due, approved drafts to send, then the best new leads."""
    iso=(on or today()).isoformat()
    return conn.execute("""SELECT * FROM prospects WHERE owner_id=? AND (
        (stage='Contacted' AND replied_at!='') OR (stage='Contacted' AND next_on!='' AND next_on<=? AND email!='' AND replied_at='') OR stage IN ('Approved','Interested') OR (stage='New' AND score>=50 AND email!='' AND ceo_status NOT IN ('held','redo') AND (website='' OR checked_at!='')))
      ORDER BY CASE WHEN stage='Interested' OR replied_at!='' THEN 0 WHEN stage='Contacted' THEN 1 WHEN stage='Approved' THEN 2 ELSE 3 END, score DESC, id LIMIT ?""",(owner,iso,limit)).fetchall()


def mark_sent(conn,owner,p,on):
    touches=p['touches']+1;gap=FOLLOW_UP_DAYS[min(touches,3)-1]
    conn.execute("UPDATE prospects SET stage='Contacted',touches=?,last_contact_on=?,next_on=?,subject='',message='',gmail_draft_id='' WHERE id=?",(touches,on.isoformat(),(on+timedelta(days=gap)).isoformat(),p['id']))
    record(conn,owner,p,'sent','message '+str(touches))
    return 'Logged. '+('Follow-up drafted for '+(on+timedelta(days=gap)).strftime('%a %-d %b')+' if they have not replied.' if touches<3 else 'That was the last follow-up. If there is no reply in a week it moves to No reply.')


def sync_gmail(conn,owner,on=None):
    """Mark approved emails as sent once they show up in Gmail's Sent folder. Read-only; never sends."""
    if not gmail_agent.can_draft(conn,owner):return 0
    done=0
    for p in conn.execute("SELECT * FROM prospects WHERE owner_id=? AND stage='Approved' AND gmail_draft_id!='' ORDER BY id LIMIT 25",(owner,)).fetchall():
        if gmail_agent.sent_since(conn,owner,p['email'],p['approved_epoch']-60):
            mark_sent(conn,owner,p,on or today());done+=1
    conn.commit()
    return done


def prospect_for(conn,owner,prospect_id):
    p=conn.execute('SELECT * FROM prospects WHERE id=? AND owner_id=?',(prospect_id,owner)).fetchone()
    if not p:raise WorkflowError('That business is not in your list.')
    return p


def card(p,s):
    import smart_writer,playbook
    subject,body=(p['subject'],p['message']) if p['stage']=='Approved' and p['message'] else (smart_writer.stored(p) or draft(p,s))
    story=playbook.story_for(p['trade'])
    channel='replied' if p['stage']=='Contacted' and p['replied_at'] else 'email' if p['email'] else 'none'
    return dict(p,why=REASONS[p['reason']][1],subject=subject,body=body,channel=channel,
      mailto=mailto(p,subject,body) if p['email'] else '',
      google='https://www.google.com/search?q='+quote(p['name']+' '+p['suburb']),
      followup=p['stage']=='Contacted',step=('First message','Follow-up 1','Follow-up 2')[min(p['touches'],2)],
      story=story['title'] if story else '',mockup_url=url_for('prospects_story' if story else 'prospects_mockup',prospect_id=p['id']),
      ai=p['draft_source']=='ai' and p['stage']!='Approved',grade=_grade(p),preview=_preview(p))


def _grade(p):
    import email_score
    return email_score.grade(p)


def _preview(p):
    from flask import g
    import pitch
    conn=g.get('db')
    if conn is None:return ''
    try:return pitch.preview_url(conn,p['owner_id'],p['id'])
    except Exception:return ''


def register(app,get_db,login_required,insert_lead):
    @app.get('/find-customers',strict_slashes=False)
    @login_required
    def prospects_home():
        conn=get_db();owner=session['user_id'];s=settings(conn,owner)
        try:sync_gmail(conn,owner)
        except WorkflowError:conn.rollback()  # Offline or Gmail signed out: the owner can still tap "I sent it".
        c=counts(conn,owner);conn.commit()
        work=[card(p,s) for p in queue(conn,owner)]
        stage=request.args.get('stage','')
        everyone=conn.execute('SELECT * FROM prospects WHERE owner_id=?'+(' AND stage=?' if stage in STAGES else '')+' ORDER BY score DESC,id DESC LIMIT 200',(owner,stage) if stage in STAGES else (owner,)).fetchall()
        return render_template('prospects.html',gmail=gmail_agent.can_draft(conn,owner),counts=c,work=work,everyone=everyone,trades=TRADES,radii=RADII,stages=STAGES,stage=stage,settings=s,reasons=REASONS,attribution=ATTRIBUTION,
          unchecked=conn.execute("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND website!='' AND checked_at='' AND stage='New'",(owner,)).fetchone()[0])

    @app.post('/find-customers/search')
    @login_required
    def prospects_search():
        conn=get_db();owner=session['user_id']
        result=find(conn,owner,request.form.get('trade',''),request.form.get('town',''),request.form.get('radius',type=int))
        checked=check_websites(conn,owner) if result['added'] else 0
        flash('Found '+str(len(result['added']))+' new businesses near '+result['label'].split(',')[0]+(' ('+str(result['already'])+' already in your list)' if result['already'] else '')+
          ('. Checked '+str(checked)+' of their websites.' if checked else '.')+(' OpenStreetMap does not list every business, so try a bigger distance or another trade if that is low.' if len(result['added'])<5 else ''),'success')
        return redirect(url_for('prospects_home'))

    @app.post('/find-customers/check')
    @login_required
    def prospects_check():
        conn=get_db();n=check_websites(conn,session['user_id'])
        flash('Checked '+str(n)+' websites.' if n else 'No websites left to check.','success');return redirect(url_for('prospects_home'))

    @app.post('/find-customers/gmail')
    @login_required
    def prospects_gmail():
        conn=get_db();n=sync_gmail(conn,session['user_id'])
        flash(('Gmail shows '+str(n)+' approved email'+('s' if n>1 else '')+' sent. Follow-ups are scheduled.') if n else 'Nothing new in your Gmail Sent folder yet.','success')
        return redirect(url_for('prospects_home'))

    @app.post('/find-customers/add')
    @login_required
    def prospects_add():
        conn=get_db();owner=session['user_id'];add_manual(conn,owner,request.form)
        n=check_websites(conn,owner,limit=1);conn.commit()
        flash('Added. '+('Website checked. ' if n else '')+'A first message is drafted below.','success');return redirect(url_for('prospects_home'))

    @app.post('/find-customers/settings')
    @login_required
    def prospects_settings():
        conn=get_db();owner=session['user_id']
        values={k:' '.join(request.form.get(k,'').split()) for k in ('name','business','email','phone','area')}
        target=request.form.get('daily_target',type=int)
        if not values['name'] or not values['business'] or not clean_email(values['email']) or any(len(v)>160 for v in values.values()) or target not in range(1,51):
            raise WorkflowError('Add your name, business name, a working email and a daily target of 1 to 50. The Spam Act requires every email to say who it is from.')
        conn.execute('''INSERT INTO prospect_settings(owner_id,name,business,email,phone,area,daily_target) VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(owner_id) DO UPDATE SET name=excluded.name,business=excluded.business,email=excluded.email,phone=excluded.phone,area=excluded.area,daily_target=excluded.daily_target''',
          (owner,values['name'],values['business'],values['email'],values['phone'],values['area'],target))
        conn.commit();flash('Saved. Your drafts now use these details.','success');return redirect(url_for('prospects_home'))

    @app.get('/find-customers/<int:prospect_id>/mockup')
    @login_required
    def prospects_mockup(prospect_id):
        conn=get_db();owner=session['user_id'];p=prospect_for(conn,owner,prospect_id)
        html=render_template('mockup.html',m=mockup(p,settings(conn,owner)))
        if request.args.get('download'):
            slug=re.sub(r'[^a-z0-9]+','-',p['name'].casefold()).strip('-') or 'mockup'
            return Response(html,mimetype='text/html',headers={'Content-Disposition':'attachment; filename="'+slug+'-mockup.html"'})
        return html

    @app.post('/find-customers/<int:prospect_id>/<action>')
    @login_required
    def prospects_action(prospect_id,action):
        conn=get_db();owner=session['user_id'];p=prospect_for(conn,owner,prospect_id);on=today();message=''
        if action=='approve':
            subject=' '.join(request.form.get('subject','').split());body=request.form.get('body','').strip()
            if not 1<=len(subject)<=200 or not 20<=len(body)<=5000:raise WorkflowError('The message needs a subject and some text.')
            if p['email'] and 'no thanks' not in body.casefold():raise WorkflowError('Keep the "no thanks" opt-out line. The Spam Act requires a way to unsubscribe.')
            import smart_writer,team
            team.feedback(conn,owner,p,'yes',smart_writer.stored(p) or draft(p,settings(conn,owner)),(subject,body))
            conn.execute("UPDATE prospects SET stage='Approved',subject=?,message=?,gmail_draft_id='',approved_epoch=? WHERE id=?",(subject,body,int(time.time()),p['id']));record(conn,owner,p,'approved')
            if p['touches']==0:conn.execute('UPDATE prospects SET variant=? WHERE id=?',(variant_of(subject,p['name']),p['id']))
            conn.commit();message='Approved. Tap "Open in my email", press send, then tap "I sent it".'
            if p['email'] and gmail_agent.can_draft(conn,owner):
                try:
                    draft_id=gmail_agent.create_outreach_draft(conn,owner,p['email'],subject,body)
                    conn.execute('UPDATE prospects SET gmail_draft_id=? WHERE id=?',(draft_id,p['id']))
                    message='Approved and put in your Gmail Drafts. Open Gmail, check it and press Send. AgencyOS notices once it is sent.'
                except WorkflowError as exc:
                    conn.rollback();message='Approved, but Gmail did not take the draft ('+str(exc)+'). Use "Open in my email" instead.'
        elif action=='sent':
            if p['stage'] not in ('Approved','Contacted'):raise WorkflowError('Approve the message first.')
            message=mark_sent(conn,owner,p,on)
        elif action in ('interested','not_interested','do_not_contact','skip'):
            stage={'interested':'Interested','not_interested':'Not interested','do_not_contact':'Do not contact','skip':'Skipped'}[action]
            conn.execute("UPDATE prospects SET stage=?,next_on='' WHERE id=?",(stage,p['id']));record(conn,owner,p,action)
            message={'interested':'Nice one. Send the free mock-up, then tap "Make them a customer".','do_not_contact':'They will never be contacted or re-added.','skip':'Skipped.'}.get(action,'Marked not interested.')
        elif action=='customer':
            if p['lead_id']:raise WorkflowError('They are already a customer.')
            from lead_finder import validate_lead
            row,errors=validate_lead(dict(business_name=p['name'],email=p['email'],website=p['website'],industry=p['trade'],location=p['suburb'],source='Find customers',status='Interested',
              notes=REASONS[p['reason']][1]+('. Phone '+p['phone'] if p['phone'] else '')))
            if errors:row.update(website='',email=p['email'] if clean_email(p['email']) else '')
            insert_lead(conn,row);lead_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute("UPDATE prospects SET stage='Customer',lead_id=?,next_on='' WHERE id=?",(lead_id,p['id']));record(conn,owner,p,'customer')
            log(conn,owner,p['name']+' moved from Find customers to Customers.')
            conn.commit();flash(p['name']+' is now in Customers. Start their quote there.','success');return redirect(url_for('sales_home'))
        elif action=='redo':
            import team
            message=team.send_back(conn,owner,p,request.form.get('reason',''))
        elif action=='reopen':
            conn.execute("UPDATE prospects SET stage='New',next_on='' WHERE id=? AND stage IN ('Skipped','No reply')",(p['id'],));message='Back in the list.'
        else:raise WorkflowError('Unknown action.')
        conn.commit();flash(message,'success')
        if request.form.get('next')=='home':return redirect(url_for('business_home')+'#ready')
        if request.form.get('next')=='phone':return redirect(url_for('phone_queue'))
        return redirect(url_for('prospects_home')+'#p'+str(p['id']))

"""Bounded OSM search. Fail closed until current service policies are reviewed."""
import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request, parse, error
from lead_finder import validate_lead
from phase3_store import WorkflowError, reserve_call, block_service, stamp

NOMINATIM='https://nominatim.openstreetmap.org/search'
OVERPASS='https://overpass-api.de/api/interpreter'
POLICIES=(
 'https://operations.osmfoundation.org/policies/nominatim/',
 'https://overpass-api.de/',
 'https://www.openstreetmap.org/copyright')
INDUSTRIES={'plumbing':('craft','plumber'),'landscaping':('craft','gardener'),
 'electricians':('craft','electrician'),'cafes':('amenity','cafe'),
 'restaurants':('amenity','restaurant'),'dentists':('amenity','dentist'),
 'hairdressers':('shop','hairdresser'),'builders':('craft','builder')}
ATTRIBUTION='© OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright'


def policy():
    """Operator attestation, not an automatic legal/policy verification."""
    path=os.environ.get('AGENCYOS_OSM_POLICY_FILE','')
    try:
        record=json.loads(Path(path).read_text()) if path else {}
        reviewed=datetime.fromisoformat(record['reviewed_at'])
        age=(datetime.now(timezone.utc)-reviewed).total_seconds()
        valid=(record['reviewed'] is True and 0<=age<30*86400 and set(record['policy_urls'])==set(POLICIES)
               and record['endpoints']==[NOMINATIM,OVERPASS]
               and isinstance(record['reviewer'],str) and bool(record['reviewer'].strip())
               and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',record['contact'])
               and 2<=float(record['interval_seconds'])<=60
               and 1<=int(record['daily_limit'])<=20)
        if not valid:raise ValueError()
        return record
    except (OSError,KeyError,ValueError,TypeError,OverflowError):
        raise WorkflowError('Live OSM discovery is disabled: a current operator policy review (less than 30 days old), contact identity and service limits are required. See README and manage.py policy-review.') from None

def policy_fingerprint():
    try:return hashlib.sha256(json.dumps(policy(),sort_keys=True).encode()).hexdigest()
    except WorkflowError:return 'unverified'

def search_payload(location, industry, maximum, keyword='', website='any', tag=''):
    location=location.strip(); keyword=keyword.strip()
    try: maximum=int(maximum)
    except (ValueError,TypeError):raise WorkflowError('Choose 1–20 maximum leads.') from None
    if not location or len(location)>160 or len(keyword)>100 or not 1<=maximum<=20:
        raise WorkflowError('Enter a location up to 160 characters, a keyword up to 100 characters and 1–20 maximum leads.')
    if any(ord(c)<32 for c in location+keyword):raise WorkflowError('Control characters are not allowed.')
    if industry in INDUSTRIES:key,value=INDUSTRIES[industry]
    elif industry=='custom' and re.fullmatch(r'(craft|shop|amenity|office|healthcare)=[a-z0-9_]{1,40}',tag):key,value=tag.split('=')
    else:raise WorkflowError('Choose a supported industry or an explicit documented OSM key=value tag.')
    if website not in ('any','listed','not-listed'):raise WorkflowError('Invalid website targeting option.')
    return dict(location=location,industry=industry,tag=[key,value],maximum=maximum,keyword=keyword,website=website)

def json_request(conn, endpoint, params, service, record):
    reserve_call(conn,service,record['interval_seconds'],record['daily_limit'])
    identity='AgencyOS/3.0 (operator: '+record['contact']+')'
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    data=parse.urlencode(params).encode()
    url=endpoint+'?'+data.decode() if service=='nominatim' else endpoint
    req=request.Request(url, data=None if service=='nominatim' else data,
                        headers={'User-Agent':identity,'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=20) as response:
            body=response.read(2_000_001)
        if len(body)>2_000_000:raise WorkflowError('Discovery provider response exceeded the size limit.')
        return json.loads(body)
    except error.HTTPError as exc:
        if exc.code in (429,503):block_service(conn,service,3600)
        raise WorkflowError(f'Discovery provider returned HTTP {exc.code}. No automatic retry. For 429/503, service calls are paused for one hour.') from None
    except (error.URLError,OSError,ValueError):
        raise WorkflowError('Discovery provider response could not be retrieved or decoded. No results have been invented.') from None

def cached(conn,key,seconds,loader):
    row=conn.execute('SELECT * FROM p3_cache WHERE key=? AND expires_at>?',(key,time.time())).fetchone()
    if row:return json.loads(row['value_json'])
    value=loader()
    conn.execute('INSERT INTO p3_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,expires_at=excluded.expires_at',
                 (key,json.dumps(value),time.time()+seconds));conn.commit()
    return value

def discover(conn,payload):
    record=policy() # Before cache access and before any external request.
    location=payload['location']
    geo=cached(conn,'geo:'+location.casefold(),86400,lambda:json_request(conn,NOMINATIM,
               {'q':location,'format':'jsonv2','limit':1},'nominatim',record))
    if not isinstance(geo,list) or not geo:raise WorkflowError('The location was not found. Try a more specific city, region and country.')
    try:
        lat,lon=float(geo[0]['lat']),float(geo[0]['lon'])
        if not math.isfinite(lat+lon) or not -90<=lat<=90 or not -180<=lon<=180:raise ValueError()
    except (KeyError,TypeError,ValueError):raise WorkflowError('The location service returned invalid coordinates.') from None
    key,value=payload['tag']
    if (key,value) not in INDUSTRIES.values() and not re.fullmatch(r'(craft|shop|amenity|office|healthcare)=[a-z0-9_]{1,40}',key+'='+value):
        raise WorkflowError('Invalid discovery category.')
    # A small, single, bounded query; no arbitrary Overpass query input or bulk crawling.
    query=f'[out:json][timeout:20];nwr["{key}"="{value}"]["name"](around:10000,{lat:.6f},{lon:.6f});out center tags 60;'
    cachekey='osm:'+hashlib.sha256(query.encode()).hexdigest()
    result=cached(conn,cachekey,3600,lambda:{'retrieved_at':stamp(),'response':json_request(conn,OVERPASS,{'data':query},'overpass',record)})
    document=result['response']
    if not isinstance(document,dict) or not isinstance(document.get('elements'),list) or document.get('remark'):
        raise WorkflowError('The discovery service returned an incomplete or invalid result. No partial search has been presented as complete.')
    candidates=[];seen=set()
    for element in document['elements'][:60]:
        try:
            kind=element['type'];identifier=int(element['id']);tags=element['tags']
            if kind not in ('node','way','relation') or identifier<=0 or not isinstance(tags,dict):continue
            if tags.get(key)!=value:continue
            source_id=f'{kind}/{identifier}'
            if source_id in seen:continue
            seen.add(source_id)
            name=tags.get('name','')
            if not isinstance(name,str) or not name.strip():continue
            website=tags.get('website',tags.get('contact:website',''))
            email=tags.get('email',tags.get('contact:email',''))
            if not isinstance(website,str):website=''
            if not isinstance(email,str):email=''
            # Do not repair, guess or invent contact details.
            if validate_lead({'business_name':name,'website':website})[1]:website=''
            if validate_lead({'business_name':name,'email':email})[1]:email=''
            parts=[tags.get('addr:city',''),tags.get('addr:state',''),tags.get('addr:country','')]
            actual_location=', '.join(p for p in parts if isinstance(p,str) and p)
            clean,errors=validate_lead(dict(business_name=name,website=website,email=email,industry=payload['industry'] if payload['industry']!='custom' else key+'='+value,
                                           location=actual_location,source='OpenStreetMap '+source_id))
            if errors:continue
            if payload['keyword'] and payload['keyword'].casefold() not in name.casefold():continue
            if payload['website']=='listed' and not website:continue
            if payload['website']=='not-listed' and website:continue
            candidates.append(dict(source_id=source_id,source_url='https://www.openstreetmap.org/'+source_id,
                                   retrieved_at=result['retrieved_at'],data=clean,attribution=ATTRIBUTION,
                                   search_location=location,resolved_location=str(geo[0].get('display_name','')),search_center=[lat,lon],matched_tag=key+'='+value))
            if len(candidates)>=payload['maximum']:break
        except (KeyError,TypeError,ValueError):continue
    return candidates

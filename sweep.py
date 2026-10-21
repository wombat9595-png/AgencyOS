"""The Scout's big job: sweep ALL of Australia for businesses with no website, starting with Sydney.

Order: Sydney first, then every capital and big city, then regional towns in every state and territory,
then a catch-all per state for everything in between (country towns and rural areas). Free OpenStreetMap
data only (Overpass): the Scout searches a set number of map squares a night, slowly, so the free service is
never hammered. OpenStreetMap does not list every business and "no website listed" is not proof they have
none, so every lead still gets a quick Google check by the owner before anything is sent.
"""
import time
from urllib import parse
from phase3_store import WorkflowError,stamp
from sales_store import log
import lead_engine

STEP=0.05  # degrees: a square about 5 km across
# (key, name, state, south, west, north, east). Sydney first, then capitals and big cities.
CITIES=(
 ('sydney','Sydney','NSW',-34.10,150.60,-33.55,151.35),
 ('melbourne','Melbourne','VIC',-38.15,144.60,-37.55,145.35),
 ('brisbane','Brisbane','QLD',-27.70,152.80,-27.20,153.25),
 ('perth','Perth','WA',-32.30,115.70,-31.65,116.10),
 ('adelaide','Adelaide','SA',-35.20,138.45,-34.65,138.80),
 ('gold-coast','Gold Coast','QLD',-28.20,153.25,-27.80,153.45),
 ('central-coast','Central Coast','NSW',-33.55,151.15,-33.15,151.65),
 ('newcastle','Newcastle','NSW',-33.10,151.45,-32.75,151.85),
 ('canberra','Canberra','ACT',-35.50,148.95,-35.15,149.25),
 ('sunshine-coast','Sunshine Coast','QLD',-26.85,152.95,-26.40,153.15),
 ('wollongong','Wollongong','NSW',-34.65,150.70,-34.20,151.00),
 ('geelong','Geelong','VIC',-38.25,144.25,-38.05,144.45),
 ('hobart','Hobart','TAS',-42.95,147.20,-42.75,147.45),
 ('townsville','Townsville','QLD',-19.40,146.65,-19.15,146.90),
 ('cairns','Cairns','QLD',-17.05,145.65,-16.75,145.80),
 ('darwin','Darwin','NT',-12.55,130.80,-12.35,131.05),
 ('toowoomba','Toowoomba','QLD',-27.65,151.85,-27.50,152.00),
 ('ballarat','Ballarat','VIC',-37.65,143.75,-37.50,143.95),
 ('bendigo','Bendigo','VIC',-36.85,144.20,-36.70,144.35),
 ('launceston','Launceston','TAS',-41.50,147.05,-41.35,147.20),
)
# Regional towns in every state and territory: (name, state, latitude, longitude) of the town centre.
TOWNS=(
 ('Maitland','NSW',-32.73,151.56),('Port Macquarie','NSW',-31.43,152.91),('Coffs Harbour','NSW',-30.30,153.11),('Tweed Heads','NSW',-28.18,153.54),
 ('Wagga Wagga','NSW',-35.11,147.37),('Albury','NSW',-36.08,146.92),('Tamworth','NSW',-31.09,150.93),('Orange','NSW',-33.28,149.10),
 ('Dubbo','NSW',-32.25,148.60),('Bathurst','NSW',-33.42,149.58),('Lismore','NSW',-28.81,153.28),('Nowra','NSW',-34.88,150.60),
 ('Armidale','NSW',-30.51,151.67),('Goulburn','NSW',-34.75,149.72),('Ballina','NSW',-28.87,153.56),('Griffith','NSW',-34.29,146.05),
 ('Grafton','NSW',-29.69,152.93),('Katoomba','NSW',-33.71,150.31),('Bowral','NSW',-34.48,150.42),('Byron Bay','NSW',-28.64,153.61),
 ('Cessnock','NSW',-32.83,151.36),('Forster','NSW',-32.18,152.51),('Taree','NSW',-31.90,152.46),('Nelson Bay','NSW',-32.72,152.14),
 ('Batemans Bay','NSW',-35.71,150.18),('Broken Hill','NSW',-31.95,141.45),
 ('Shepparton','VIC',-36.38,145.40),('Mildura','VIC',-34.19,142.16),('Warrnambool','VIC',-38.38,142.48),('Traralgon','VIC',-38.20,146.54),
 ('Wodonga','VIC',-36.12,146.89),('Wangaratta','VIC',-36.36,146.31),('Horsham','VIC',-36.71,142.20),('Sale','VIC',-38.11,147.07),
 ('Bairnsdale','VIC',-37.83,147.61),('Warragul','VIC',-38.16,145.93),('Mornington Peninsula','VIC',-38.37,145.03),('Torquay','VIC',-38.33,144.32),
 ('Echuca','VIC',-36.13,144.75),
 ('Mackay','QLD',-21.14,149.19),('Rockhampton','QLD',-23.38,150.51),('Bundaberg','QLD',-24.87,152.35),('Hervey Bay','QLD',-25.29,152.84),
 ('Gladstone','QLD',-23.85,151.26),('Ipswich','QLD',-27.61,152.76),('Caboolture','QLD',-27.08,152.95),('Gympie','QLD',-26.19,152.67),
 ('Maryborough','QLD',-25.54,152.70),('Mount Isa','QLD',-20.73,139.49),('Warwick','QLD',-28.22,152.03),('Emerald','QLD',-23.53,148.16),
 ('Mount Gambier','SA',-37.83,140.78),('Whyalla','SA',-33.03,137.58),('Murray Bridge','SA',-35.12,139.27),('Port Augusta','SA',-32.49,137.77),
 ('Port Pirie','SA',-33.19,138.02),('Port Lincoln','SA',-34.73,135.86),('Victor Harbor','SA',-35.55,138.62),('Gawler','SA',-34.60,138.75),
 ('Mandurah','WA',-32.53,115.72),('Bunbury','WA',-33.33,115.64),('Geraldton','WA',-28.77,114.61),('Kalgoorlie','WA',-30.75,121.47),
 ('Albany','WA',-35.02,117.88),('Busselton','WA',-33.65,115.35),('Broome','WA',-17.96,122.24),('Karratha','WA',-20.74,116.85),
 ('Port Hedland','WA',-20.31,118.58),
 ('Devonport','TAS',-41.18,146.35),('Burnie','TAS',-41.05,145.91),('Ulverstone','TAS',-41.16,146.17),
 ('Alice Springs','NT',-23.70,133.88),('Katherine','NT',-14.47,132.26),
)
STATES=('NSW','VIC','QLD','WA','SA','TAS','ACT','NT')


def _town_region(name,state,lat,lon):
    key=name.casefold().replace(' ','-')
    return (key,name,state,round(lat-0.06,4),round(lon-0.07,4),round(lat+0.06,4),round(lon+0.07,4))


# Every area the Scout works through, in order: grids of map squares, then one catch-all per state.
REGIONS=CITIES+tuple(_town_region(*t) for t in TOWNS)
CATCH_ALL=tuple(('state-'+s.casefold(),'Rest of '+s,s) for s in STATES)
NO_SITE='[!"website"][!"contact:website"][!"url"]'


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS sweep_tiles (
      owner_id INTEGER NOT NULL, region TEXT NOT NULL, idx INTEGER NOT NULL, done_at TEXT NOT NULL, found INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(owner_id,region,idx));
    ''')


def tiles(region):
    """The map squares of one city or town, west to east then south to north."""
    _,_,_,south,west,north,east=region
    rows=round((north-south)/STEP+0.4999);cols=round((east-west)/STEP+0.4999)
    return [(round(south+r*STEP,4),round(west+c*STEP,4),round(min(north,south+(r+1)*STEP),4),round(min(east,west+(c+1)*STEP),4))
            for r in range(rows) for c in range(cols)]


def _trade_of(tags):
    for trade,pairs in lead_engine.TRADES.items():
        if any(tags.get(k)==v for k,v in pairs):return trade
    return ''


def tile_query(box):
    s,w,n,e=box;bbox=f'({s},{w},{n},{e})'
    by_key={}
    for pairs in lead_engine.TRADES.values():
        for k,v in pairs:by_key.setdefault(k,[]).append(v)
    parts=''.join(f'nwr["{k}"~"^({"|".join(sorted(set(v)))})$"]["name"]{NO_SITE}{bbox};' for k,v in sorted(by_key.items()))
    return f'[out:json][timeout:60];({parts});out center tags 500;'


def state_query(state,trade):
    """Catch-all for one state: every business of one trade with no website, anywhere in the state."""
    pairs=''.join(f'nwr["{k}"="{v}"]["name"]{NO_SITE}(area.s);' for k,v in lead_engine.TRADES[trade])
    return f'[out:json][timeout:120];area["ISO3166-2"="AU-{state}"]->.s;({pairs});out center tags 3000;'


def jobs(region):
    """One Overpass query per job: a map square for a city or town, a trade for a state catch-all."""
    if len(region)==3:return [('trade',t) for t in lead_engine.TRADES]
    return [('box',b) for b in tiles(region)]


def plan(all_australia=True):
    return (REGIONS+CATCH_ALL) if all_australia else REGIONS[:1]


def progress(conn,owner,all_australia=True):
    """How far the Scout has got, per area and per state: squares done and businesses found."""
    done={}
    for r in conn.execute('SELECT region,COUNT(*) n,SUM(found) f FROM sweep_tiles WHERE owner_id=? GROUP BY region',(owner,)):done[r['region']]=(r['n'],r['f'] or 0)
    out=[]
    for region in plan(all_australia):
        total=len(jobs(region));n,f=done.get(region[0],(0,0))
        out.append(dict(key=region[0],name=region[1],state=region[2],total=total,done=n,found=f,pct=round(100*n/total) if total else 100))
    return out


def by_state(conn,owner,all_australia=True):
    """Progress rolled up per state, Sydney shown on its own first."""
    rows=progress(conn,owner,all_australia);out=[]
    if rows:out.append(dict(rows[0],name='Sydney (first)'))
    for st in STATES if all_australia else ():
        part=[r for r in rows[1:] if r['state']==st]
        total=sum(r['total'] for r in part);done=sum(r['done'] for r in part)
        out.append(dict(name=st,total=total,done=done,found=sum(r['found'] for r in part),pct=round(100*done/total) if total else 100))
    return out


def next_tiles(conn,owner,count,all_australia=True):
    """The next jobs to search, finishing one area before starting the next."""
    taken={(r['region'],r['idx']) for r in conn.execute('SELECT region,idx FROM sweep_tiles WHERE owner_id=?',(owner,))}
    out=[]
    for region in plan(all_australia):
        for i,job in enumerate(jobs(region)):
            if (region[0],i) not in taken:
                out.append((region,i,job))
                if len(out)>=count:return out
    return out


def run(conn,owner,count,all_australia=True,pause=2.0,sleep=time.sleep,budget=180,clock=time.monotonic):
    """Search the next few squares. Returns (found, squares searched, notes). Stops early if the map service is busy."""
    contact=lead_engine.settings(conn,owner)['email'];found=0;searched=0;notes=[];start=clock()
    for region,i,(kind,job) in next_tiles(conn,owner,count,all_australia):
        if searched and clock()-start>budget:break  # never hold up reply checks for long; the rest waits for the next shift
        if searched:sleep(pause)
        query=tile_query(job) if kind=='box' else state_query(region[2],job)
        try:data=lead_engine.http_json(lead_engine.OVERPASS,parse.urlencode({'data':query}).encode(),contact)
        except WorkflowError as exc:
            conn.rollback()
            if kind=='trade' and 'too much data' in str(exc):data={'elements':[]};notes.append(job+' in '+region[2]+' was too big for one search; the city and town sweeps cover most of it.')
            else:notes.append('Map search paused in '+region[1]+': '+str(exc));break
        elements=data.get('elements') if isinstance(data,dict) else None
        if not isinstance(elements,list):notes.append('The map service sent back something unexpected.');break
        rows=[]
        for element in elements:
            trade=_trade_of(element.get('tags') or {})
            if trade:rows.append(lead_engine.from_osm(element,trade))
        added,_=lead_engine.add_rows(conn,owner,rows,region[1] if kind=='box' else region[2])
        conn.execute('INSERT OR REPLACE INTO sweep_tiles(owner_id,region,idx,done_at,found) VALUES(?,?,?,?,?)',(owner,region[0],i,stamp(),len(added)))
        conn.commit();found+=len(added);searched+=1
    if searched:log(conn,owner,'Scout swept '+str(searched)+' map squares and found '+str(found)+' businesses with no website listed. Nothing was sent.')
    conn.commit()
    return found,searched,notes

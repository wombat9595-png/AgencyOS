"""The Scout's big job: sweep whole cities for businesses with no website, Sydney first, then the rest of Australia.

Free OpenStreetMap data only (Overpass). Each city is cut into small map squares and the Scout searches a
handful a night, slowly, so the free service is never hammered. OpenStreetMap does not list every business
and "no website listed" is not proof they have none, so every lead still gets a quick Google check by the owner.
"""
import time
from urllib import parse
from phase3_store import WorkflowError,stamp
from sales_store import log
import lead_engine

STEP=0.05  # degrees: a square about 5 km across
# (key, name, south, west, north, east). Sydney first, then the other big cities and regional centres.
REGIONS=(
 ('sydney','Sydney',-34.10,150.60,-33.55,151.35),
 ('central-coast','Central Coast',-33.55,151.15,-33.15,151.65),
 ('newcastle','Newcastle',-33.10,151.45,-32.75,151.85),
 ('wollongong','Wollongong',-34.65,150.70,-34.20,151.00),
 ('canberra','Canberra',-35.50,148.95,-35.15,149.25),
 ('melbourne','Melbourne',-38.15,144.60,-37.55,145.35),
 ('geelong','Geelong',-38.25,144.25,-38.05,144.45),
 ('brisbane','Brisbane',-27.70,152.80,-27.20,153.25),
 ('gold-coast','Gold Coast',-28.20,153.25,-27.80,153.45),
 ('sunshine-coast','Sunshine Coast',-26.85,152.95,-26.40,153.15),
 ('perth','Perth',-32.30,115.70,-31.65,116.10),
 ('adelaide','Adelaide',-35.20,138.45,-34.65,138.80),
 ('hobart','Hobart',-42.95,147.20,-42.75,147.45),
 ('darwin','Darwin',-12.55,130.80,-12.35,131.05),
 ('townsville','Townsville',-19.40,146.65,-19.15,146.90),
 ('cairns','Cairns',-17.05,145.65,-16.75,145.80),
 ('toowoomba','Toowoomba',-27.65,151.85,-27.50,152.00),
 ('ballarat','Ballarat',-37.65,143.75,-37.50,143.95),
 ('bendigo','Bendigo',-36.85,144.20,-36.70,144.35),
 ('launceston','Launceston',-41.50,147.05,-41.35,147.20),
)
NO_SITE='[!"website"][!"contact:website"][!"url"]'


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS sweep_tiles (
      owner_id INTEGER NOT NULL, region TEXT NOT NULL, idx INTEGER NOT NULL, done_at TEXT NOT NULL, found INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(owner_id,region,idx));
    ''')


def tiles(region):
    """The map squares of one city, west to east then south to north."""
    _,_,south,west,north,east=region
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


def progress(conn,owner,all_australia=True):
    """How far the Scout has got: per city squares done and businesses found."""
    done={}
    for r in conn.execute('SELECT region,COUNT(*) n,SUM(found) f FROM sweep_tiles WHERE owner_id=? GROUP BY region',(owner,)):done[r['region']]=(r['n'],r['f'] or 0)
    out=[]
    for region in REGIONS if all_australia else REGIONS[:1]:
        total=len(tiles(region));n,f=done.get(region[0],(0,0))
        out.append(dict(key=region[0],name=region[1],total=total,done=n,found=f,pct=round(100*n/total) if total else 100))
    return out


def next_tiles(conn,owner,count,all_australia=True):
    """The next squares to search, finishing one city before starting the next."""
    taken={(r['region'],r['idx']) for r in conn.execute('SELECT region,idx FROM sweep_tiles WHERE owner_id=?',(owner,))}
    out=[]
    for region in REGIONS if all_australia else REGIONS[:1]:
        for i,box in enumerate(tiles(region)):
            if (region[0],i) not in taken:
                out.append((region,i,box))
                if len(out)>=count:return out
    return out


def run(conn,owner,count,all_australia=True,pause=2.0,sleep=time.sleep):
    """Search the next few squares. Returns (found, squares searched, notes). Stops early if the map service is busy."""
    contact=lead_engine.settings(conn,owner)['email'];found=0;searched=0;notes=[]
    for region,i,box in next_tiles(conn,owner,count,all_australia):
        if searched:sleep(pause)
        try:data=lead_engine.http_json(lead_engine.OVERPASS,parse.urlencode({'data':tile_query(box)}).encode(),contact)
        except WorkflowError as exc:
            conn.rollback();notes.append('Map search paused in '+region[1]+': '+str(exc));break
        elements=data.get('elements') if isinstance(data,dict) else None
        if not isinstance(elements,list):notes.append('The map service sent back something unexpected.');break
        rows=[]
        for element in elements:
            trade=_trade_of(element.get('tags') or {})
            if trade:rows.append(lead_engine.from_osm(element,trade))
        added,_=lead_engine.add_rows(conn,owner,rows,region[1])
        conn.execute('INSERT OR REPLACE INTO sweep_tiles(owner_id,region,idx,done_at,found) VALUES(?,?,?,?,?)',(owner,region[0],i,stamp(),len(added)))
        conn.commit();found+=len(added);searched+=1
    if searched:log(conn,owner,'Scout swept '+str(searched)+' map squares and found '+str(found)+' businesses with no website listed. Nothing was sent.')
    conn.commit()
    return found,searched,notes

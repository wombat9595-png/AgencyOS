"""Email outreach scoreboard: lead grades A/B/C, today's emails against the target, a streak and
"what's working" by trade and subject line. Email only: AgencyOS never makes or plans cold calls,
and a phone number is just lead data. Rule-based and local; nothing is sent from here.
"""
from datetime import timedelta
from flask import session
import lead_engine

# Trades by what a website is usually worth to them: big jobs first.
TRADE_VALUE={
 'Builders':20,'Roofers':20,'Gardeners and landscapers':18,'Electricians':16,'Plumbers':16,'Carpenters':15,'Painters':14,
 'Dentists':15,'Physios':13,'Beauty salons':13,'Hairdressers and barbers':12,'Mechanics':11,'Vets':11,'Tattoo studios':10,
 'Gyms':10,'Florists':8,'Restaurants':7,'Cafes':5,'Bakeries':5,
}


def grade(p):
    """A, B or C: how likely this business is to pay for a website, from what we know. No email means C: we can't reach them."""
    if not p['email'] and p['stage'] not in ('Interested','Customer'):return 'C'
    points=lead_engine.REASONS.get(p['reason'],(50,''))[0]*0.6+TRADE_VALUE.get(p['trade'],9)+12
    if p['stage']=='Interested':points+=30
    return 'A' if points>=72 else 'B' if points>=58 else 'C'


def scoreboard(conn,owner,on=None):
    on=on or lead_engine.today();iso=on.isoformat()
    def sent_on(d):
        return conn.execute("SELECT COUNT(*) FROM prospect_log WHERE owner_id=? AND on_date=? AND action='sent'",(owner,d)).fetchone()[0]
    sent=sent_on(iso);target=lead_engine.settings(conn,owner)['daily_target']
    streak=0;d=on if sent>=target else on-timedelta(days=1)
    for _ in range(120):
        if d.weekday()>=5:d-=timedelta(days=1);continue
        if sent_on(d.isoformat())>=target:streak+=1;d-=timedelta(days=1)
        else:break
    week=(on-timedelta(days=on.weekday())).isoformat()
    def n(sql,args):return conn.execute(sql,args).fetchone()[0]
    replies=n("SELECT COUNT(*) FROM prospects WHERE owner_id=? AND replied_at>=?",(owner,week))
    yeses=n("SELECT COUNT(*) FROM prospect_log WHERE owner_id=? AND on_date>=? AND action='interested'",(owner,week))
    deals=n("SELECT COUNT(*) FROM prospect_log WHERE owner_id=? AND on_date>=? AND action='customer'",(owner,week))
    return dict(sent=sent,email_target=target,streak=streak,replies_week=replies,interested_week=yeses,deals_week=deals,done=sent>=target)


def learn(conn,owner):
    """What is working: yeses by trade and by first-email subject line."""
    rows=conn.execute("SELECT * FROM prospects WHERE owner_id=? AND touches>0",(owner,)).fetchall()
    def bucket(key):
        out={}
        for p in rows:
            k=key(p)
            if not k:continue
            b=out.setdefault(k,dict(name=k,tried=0,yes=0))
            b['tried']+=1;b['yes']+=1 if p['stage'] in ('Interested','Customer') else 0
        return sorted([dict(b,rate=round(100*b['yes']/b['tried'])) for b in out.values()],key=lambda b:(-b['rate'],-b['tried']))
    return dict(trades=bucket(lambda p:p['trade'] or 'Other'),subjects=bucket(lambda p:p['variant'] or ''))


def register(app,get_db,login_required):
    @app.context_processor
    def _scoreboard_helper():
        def home_scoreboard():
            if not session.get('user_id'):return None
            try:return scoreboard(get_db(),session['user_id'])
            except Exception:return None
        return dict(home_scoreboard=home_scoreboard)


def migrate(conn):
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospect_settings)')}
    if 'call_target' not in columns:  # kept so older databases and backups still load; never used
        conn.execute('ALTER TABLE prospect_settings ADD COLUMN call_target INTEGER NOT NULL DEFAULT 5')
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospects)')}
    if 'variant' not in columns:
        conn.execute("ALTER TABLE prospects ADD COLUMN variant TEXT NOT NULL DEFAULT ''")
    if 'replied_at' not in columns:
        conn.execute("ALTER TABLE prospects ADD COLUMN replied_at TEXT NOT NULL DEFAULT ''")
    if 'referred_by' not in columns:
        conn.execute('ALTER TABLE prospects ADD COLUMN referred_by INTEGER')

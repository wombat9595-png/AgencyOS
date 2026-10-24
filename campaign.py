"""The 30-day plan from the Client One Playbook, as rules (A$0):
small batches (one trade in one area, 50 or fewer), today's 3 video follow-ups, the extras each email carries,
and what is working by trade and subject line."""
import lead_engine

BATCH_SIZE=50     # Hunter 2025: campaigns to 50 people or fewer got 5.8% replies, vs 2.1% for 1,000+
VIDEOS_A_DAY=3
JUDGE_AFTER=300   # emails before reply rates mean anything


def _key(p):return (p['trade'],p['suburb'])


def sent_in(conn,owner,trade,suburb):
    """First emails already sent to this trade in this area."""
    return conn.execute("""SELECT COUNT(DISTINCT l.prospect_id) FROM prospect_log l JOIN prospects p ON p.id=l.prospect_id
      WHERE l.owner_id=? AND l.action='sent' AND l.detail='message 1' AND p.trade=? AND p.suburb=?""",(owner,trade,suburb)).fetchone()[0]


def last_batch(conn,owner):
    row=conn.execute("""SELECT p.trade,p.suburb FROM prospect_log l JOIN prospects p ON p.id=l.prospect_id
      WHERE l.owner_id=? AND l.action='sent' AND l.detail='message 1' ORDER BY l.id DESC LIMIT 1""",(owner,)).fetchone()
    return (row['trade'],row['suburb']) if row else None


def order(conn,owner,rows):
    """New leads in batch order: finish the trade and area being emailed now (up to 50), then the best lead of the same trade
    elsewhere, then everything else by score. Keeps each batch small and about one kind of business."""
    rows=list(rows)
    if not rows:return rows
    last=last_batch(conn,owner)
    full=bool(last) and sent_in(conn,owner,*last)>=BATCH_SIZE
    if last and not full and any(_key(p)==last for p in rows):focus=last
    else:
        pool=[p for p in rows if not (full and _key(p)==last)] or rows
        same=[p for p in pool if last and p['trade']==last[0]]
        focus=_key(max(same or pool,key=lambda p:(p['score'],-p['id'])))
    return sorted(rows,key=lambda p:(_key(p)!=focus,p['trade']!=focus[0],-p['score'],p['id']))


def batch_now(conn,owner):
    """The batch being emailed right now, for the CEO live page."""
    last=last_batch(conn,owner)
    if not last:return None
    return dict(trade=last[0] or 'Local businesses',suburb=last[1] or 'their area',sent=sent_in(conn,owner,*last),size=BATCH_SIZE)


def extras(conn,owner,p,kind):
    """What a draft carries besides the rules text: a client quote in first emails (once there is one),
    and the online preview link in the first follow-up (never in email one: links from a new sender look like spam)."""
    import pitch
    out=dict(preview='',proof='')
    if kind=='followup1':out['preview']=pitch.preview_url(conn,owner,p['id'])
    if kind=='first':
        quotes=pitch.testimonials(conn,owner)
        if quotes:out['proof']='"'+quotes[0]['testimonial'].strip().strip('"')+'" ('+quotes[0]['client_name']+')'
    return out


def videos_today(conn,owner,on=None):
    """The best leads whose first follow-up is due by tomorrow. Benji records a 60-second phone screen recording of their site
    and sends it as that follow-up. Once the follow-up is sent they drop off the list."""
    from datetime import timedelta
    by=((on or lead_engine.today())+timedelta(days=1)).isoformat()
    return conn.execute("""SELECT * FROM prospects WHERE owner_id=? AND stage='Contacted' AND touches=1 AND replied_at='' AND email!=''
      AND next_on!='' AND next_on<=? ORDER BY score DESC,id LIMIT ?""",(owner,by,VIDEOS_A_DAY)).fetchall()


REPLIED="(replied_at!='' OR stage IN ('Interested','Customer','Not interested'))"


def results(conn,owner):
    """Reply rates by trade and by first-email subject line, for businesses that got at least one email."""
    def rows(column):
        out=[]
        for r in conn.execute('SELECT '+column+' k,COUNT(*) n,SUM('+REPLIED+') replied,SUM(stage IN (\'Interested\',\'Customer\')) yes FROM prospects '
                              "WHERE owner_id=? AND touches>0 GROUP BY "+column+' ORDER BY n DESC',(owner,)):
            out.append(dict(name=r['k'] or 'Other',sent=r['n'],replied=r['replied'] or 0,yes=r['yes'] or 0,rate=round(100*(r['replied'] or 0)/r['n'],1)))
        return out
    trades=rows('trade')
    subjects=[dict(s,name=s['name'].replace('{name}','(business)')) for s in rows('variant') if s['name']!='Other']
    total=sum(t['sent'] for t in trades)
    fair=[t for t in trades if t['sent']>=BATCH_SIZE]
    best=max(fair,key=lambda t:t['rate']) if len(fair)>=2 and max(t['rate'] for t in fair)>0 else None
    return dict(trades=trades,subjects=subjects,total=total,ready=total>=JUDGE_AFTER,judge_after=JUDGE_AFTER,best=best)

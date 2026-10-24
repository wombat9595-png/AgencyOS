"""CEO report card: how the CEO and auto-send did over the last 14 days, from local records only, with a plain verdict.

Counts come from the lead log (what was sent, who wrote back, bounced or said no thanks) and the leads themselves
(what the CEO is holding back and why, which websites are still unchecked). It only reads; nothing is sent or changed.
"""
from collections import Counter
from datetime import timedelta
from flask import render_template,session
import lead_engine

DAYS=14
AVERAGE_REPLY=0.041  # Hunter, State of Cold Email 2025: the average cold email reply rate
BOUNCE_WARN,BOUNCE_BAD=0.03,0.05  # the same lines auto-send uses to hold the cap and to switch itself off
ACTIONS=('auto_sent','sent','replied','bounced','opted_out')


def reasons(note):
    """One held lead's reasons, without the 'Held back:' style prefix."""
    note=(note or '').strip()
    for prefix in ('Held back:','Not auto-sent:'):
        if note.startswith(prefix):note=note[len(prefix):]
    return [r.strip().rstrip('.') for r in note.split(';') if r.strip()] or ['No reason saved']


def report(conn,owner,on=None,days=DAYS):
    on=on or lead_engine.today();start=on-timedelta(days=days-1)
    rows=conn.execute('SELECT on_date,action,COUNT(DISTINCT prospect_id) n FROM prospect_log WHERE owner_id=? AND on_date BETWEEN ? AND ? AND action IN (%s) GROUP BY on_date,action'%','.join('?'*len(ACTIONS)),
      (owner,start.isoformat(),on.isoformat())+ACTIONS).fetchall()
    by={(r['on_date'],r['action']):r['n'] for r in rows}
    daily=[]
    for i in range(days):
        d=(start+timedelta(days=i)).isoformat()
        daily.append(dict(day=d,ceo=by.get((d,'auto_sent'),0),you=by.get((d,'sent'),0),replied=by.get((d,'replied'),0),
          bounced=by.get((d,'bounced'),0),opted_out=by.get((d,'opted_out'),0)))
    t={k:sum(x[k] for x in daily) for k in ('ceo','you','replied','bounced','opted_out')}
    t['sent']=t['ceo']+t['you']
    t['reply_rate']=t['replied']/t['sent'] if t['sent'] else 0
    t['bounce_rate']=t['bounced']/t['sent'] if t['sent'] else 0
    t['optout_rate']=t['opted_out']/t['sent'] if t['sent'] else 0
    t['per_day']=round(t['sent']/days,1)
    t['active_days']=sum(1 for x in daily if x['ceo'] or x['you'])
    held=Counter()
    for r in conn.execute("SELECT ceo_note FROM prospects WHERE owner_id=? AND ceo_status='held' AND stage='New'",(owner,)):
        held.update(reasons(r['ceo_note']))
    def n(where,args=()):return conn.execute('SELECT COUNT(*) FROM prospects WHERE owner_id=? AND '+where,(owner,)+args).fetchone()[0]
    leads=dict(total=n('1'),with_site=n("website!=''"),checked=n("website!='' AND checked_at!=''"),unchecked=n("website!='' AND checked_at=''"),
      checked_recent=n("website!='' AND checked_at>=?",(start.isoformat(),)),no_site=n("website='' AND email=''"),with_email=n("email!=''"),
      held=n("ceo_status='held' AND stage='New'"),ready=n("ceo_status='ready' AND stage='New' AND draft_body!=''"))
    return dict(start=start,end=on,days=days,daily=daily,totals=t,held=held.most_common(8),leads=leads,verdict=verdict(t,leads))


def verdict(t,leads):
    """A plain-English verdict and a colour: good, watch or bad."""
    if not t['sent']:
        return 'bad','Not performing: no emails went out in the last 14 days. Check that auto-send is on and Gmail is connected.'
    parts=['Sent '+str(t['sent'])+' emails in 14 days ('+str(t['per_day'])+' a day, on '+str(t['active_days'])+' days).']
    rr=round(t['reply_rate']*100,1)
    parts.append(str(t['replied'])+' wrote back ('+str(rr)+'%), '+('at or above' if t['reply_rate']>=AVERAGE_REPLY else 'below')+' the 4.1% cold email average.')
    br=round(t['bounce_rate']*100,1)
    parts.append(str(t['bounced'])+' bounced ('+str(br)+'%)'+(': too high, sending is being held back.' if t['bounce_rate']>BOUNCE_WARN else ', which is safe.'))
    if leads['with_email']<leads['total']*0.05:
        parts.append('The real limit is leads: only '+format(leads['with_email'],',')+' of '+format(leads['total'],',')+' have an email address.')
    level='bad' if t['bounce_rate']>BOUNCE_BAD else 'watch' if t['bounce_rate']>BOUNCE_WARN or t['reply_rate']<AVERAGE_REPLY/2 else 'good'
    head={'good':'Performing well.','watch':'Working, but watch it.','bad':'Not performing.'}[level]
    return level,head+' '+' '.join(parts)


def register(app,get_db,login_required):
    @app.get('/ceo/report',strict_slashes=False)
    @login_required
    def ceo_report():
        conn=get_db();owner=session['user_id']
        return render_template('ceo_report.html',r=report(conn,owner))

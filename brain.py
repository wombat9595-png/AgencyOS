"""One shared picture of the agency that every agent, the CEO chat and the Office read from.

Rule-based and local: it only counts the owner's own records, never calls an AI model,
never invents activity and never sends anything. Each sector has two agents and each
agent has one state: off (agency paused), asleep (its tool is not connected), idle,
working, waiting (something needs the owner) or cheering (money arrived).
"""
from datetime import datetime,timedelta,timezone
from phase4_store import paused
import client_plans
import lead_engine

RECENT=timedelta(minutes=30)
SECTORS=(
 ('find','Find customers','prospects_home',('Scout','Checker')),
 ('outreach','Outreach','prospects_home',('Writer','Follow-up')),
 ('websites','Websites','projects',('Designer','Builder')),
 ('inbox','Inbox','gmail_home',('Sorter','Replier')),
 ('money','Money','invoices',('Bookkeeper','Collector')),
 ('clients','Monthly clients','plan_clients',('Carer','Fixer')),
)


def _n(conn,sql,args=()):
    return conn.execute(sql,args).fetchone()[0]


def _agent(name,state,items=0,why=''):
    return dict(name=name,state=state,items=max(0,min(int(items),5)),why=why)


def snapshot(conn,owner,now=None,worker=True):
    """Everything the agents know right now, from local records only."""
    now=now or datetime.now(timezone.utc)
    since=(now-RECENT).isoformat()
    month=now.date().replace(day=1).isoformat()
    is_paused=paused(conn)
    p=lead_engine.counts(conn,owner)
    found_recent=_n(conn,'SELECT COUNT(*) FROM prospects WHERE owner_id=? AND created_at>=?',(owner,since))
    checked_recent=_n(conn,'SELECT COUNT(*) FROM prospects WHERE owner_id=? AND checked_at>=?',(owner,since))
    unchecked=_n(conn,"SELECT COUNT(*) FROM prospects WHERE owner_id=? AND website!='' AND checked_at='' AND stage='New'",(owner,))
    plans=client_plans.summary(conn,owner)
    gmail=conn.execute('SELECT email FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
    drafts=_n(conn,"SELECT COUNT(*) FROM gmail_drafts WHERE owner_id=? AND status='Needs review'",(owner,))
    incoming_recent=_n(conn,"SELECT COUNT(*) FROM gmail_mail WHERE owner_id=? AND direction='incoming' AND received_at>=?",(owner,since)) if gmail else 0
    projects=_n(conn,"SELECT COUNT(*) FROM projects WHERE status IN ('Planning','In progress','Review')")
    money_month=(_n(conn,'SELECT COALESCE(SUM(amount_cents),0) FROM first_sale_receipts WHERE owner_id=? AND received_on>=?',(owner,month))
      +_n(conn,'SELECT COALESCE(SUM(amount_cents),0) FROM plan_payments WHERE owner_id=? AND received_on>=?',(owner,month)))
    money_recent=(_n(conn,'SELECT COUNT(*) FROM first_sale_receipts WHERE owner_id=? AND recorded_at>=?',(owner,since))
      +_n(conn,'SELECT COUNT(*) FROM plan_payments WHERE owner_id=? AND recorded_at>=?',(owner,since)))
    to_send=p['ready']+p['follow_ups']+min(p['to_review'],max(0,p['target']-p['contacted_today']))

    a=_agent
    sectors=dict(
     find=[a('Scout','working' if found_recent else ('waiting' if not p['total'] else 'idle'),found_recent,
             'just found '+str(found_recent)+' businesses' if found_recent else ('needs you to pick a trade and suburb' if not p['total'] else 'resting until the next search')),
           a('Checker','working' if unchecked or checked_recent else 'idle',unchecked or checked_recent,
             str(unchecked)+' websites to check' if unchecked else ('checked '+str(checked_recent)+' websites' if checked_recent else 'nothing to check'))],
     outreach=[a('Writer','waiting' if to_send else 'idle',to_send,
             str(to_send)+' messages drafted for you to send' if to_send else 'no drafts waiting'),
           a('Follow-up','working' if p['waiting'] else 'idle',p['waiting'],
             'watching '+str(p['waiting'])+' businesses for replies' if p['waiting'] else 'no one to follow up')],
     websites=[a('Designer','waiting' if p['interested'] else 'idle',p['interested'],
             str(p['interested'])+' interested: send the mock-up' if p['interested'] else 'no mock-ups asked for'),
           a('Builder','working' if projects else 'idle',projects,str(projects)+' website projects' if projects else 'no projects yet')],
     inbox=[a('Sorter',('working' if incoming_recent else 'idle') if gmail else 'asleep',incoming_recent,
             'Gmail not connected' if not gmail else ('sorting '+str(incoming_recent)+' new emails' if incoming_recent else 'inbox quiet')),
           a('Replier',('waiting' if drafts else 'idle') if gmail else 'asleep',drafts,
             'Gmail not connected' if not gmail else (str(drafts)+' replies drafted for you' if drafts else 'no replies to draft'))],
     money=[a('Bookkeeper','cheering' if money_recent else ('working' if money_month else 'idle'),min(5,money_month//10000),
             'money just arrived' if money_recent else ('A$'+format(money_month/100,',.0f')+' this month' if money_month else 'no money recorded this month')),
           a('Collector','waiting' if plans['overdue'] else 'idle',plans['overdue'],
             str(plans['overdue'])+' payments overdue' if plans['overdue'] else 'nothing overdue')],
     clients=[a('Carer','working' if plans['clients'] else 'idle',plans['clients'],
             'looking after '+str(plans['clients'])+' monthly clients' if plans['clients'] else 'no monthly clients yet'),
           a('Fixer','waiting' if plans['requests'] else 'idle',plans['requests'],
             str(plans['requests'])+' change requests' if plans['requests'] else 'no change requests')],
    )
    if is_paused:
        for agents in sectors.values():
            for agent in agents:agent.update(state='off',why='the agency is paused')
    active=any(ag['state'] in ('working','waiting','cheering') for ags in sectors.values() for ag in ags)
    return dict(paused=is_paused,worker=bool(worker),active=active,gmail=bool(gmail),
                sectors=[dict(key=k,label=label,endpoint=endpoint,agents=sectors[k]) for k,label,endpoint,_ in SECTORS])


def sample():
    """A made-up busy day for the Office preview. Never mixed with real records."""
    a=_agent
    agents=dict(find=[a('Scout','working',3),a('Checker','working',4)],outreach=[a('Writer','waiting',5),a('Follow-up','working',2)],
      websites=[a('Designer','waiting',1),a('Builder','working',2)],inbox=[a('Sorter','working',2),a('Replier','waiting',1)],
      money=[a('Bookkeeper','cheering',3),a('Collector','idle')],clients=[a('Carer','working',2),a('Fixer','waiting',1)])
    return dict(paused=False,worker=True,active=True,gmail=True,sample=True,
                sectors=[dict(key=k,label=label,endpoint=endpoint,agents=agents[k]) for k,label,endpoint,_ in SECTORS])


def describe(snap):
    """One plain sentence per sector, for the CEO chat."""
    if snap['paused']:return 'The agency is paused, so every agent is resting. Press Start on Home to wake them.'
    parts=[]
    for s in snap['sectors']:
        busy=[ag['name']+' '+ag['why'] for ag in s['agents'] if ag['state'] in ('working','waiting','cheering','asleep')]
        if busy:parts.append(s['label']+': '+'; '.join(busy))
    return ('. '.join(parts)+'.') if parts else 'Every agent is idle: nothing is happening and nothing needs you.'

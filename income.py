"""Money in: what clients actually paid each month, from payments recorded in AgencyOS only.

Three places hold real payments: invoices marked Paid on Get paid, monthly plan payments, and first-sale receipts.
A plan payment or receipt with the same bank reference as a paid invoice is the same money, so it counts once.
Nothing is estimated: a month with no recorded payment shows A$0.
"""
from flask import render_template,session
import client_plans

MONTHS=12


def month_key(day):
    return day.strftime('%Y-%m')


def back(day,months):
    y,m=divmod(day.year*12+day.month-1-months,12)
    return day.replace(year=y,month=m+1,day=1)


def payments(conn,owner):
    """Every recorded payment as (month, source, cents), each piece of money once."""
    out=[];refs=set()
    for r in conn.execute("SELECT paid_on,total_cents,paid_reference FROM bills WHERE owner_id=? AND status='Paid' AND paid_on!=''",(owner,)):
        out.append((r['paid_on'][:7],'Invoices paid',r['total_cents']));refs.add(r['paid_reference'])
    for table,label in (('plan_payments','Monthly plan payments'),('first_sale_receipts','First-sale receipts')):
        for r in conn.execute('SELECT received_on,amount_cents,bank_reference FROM '+table+' WHERE owner_id=?',(owner,)):
            if r['bank_reference'] not in refs:out.append((r['received_on'][:7],label,r['amount_cents']))
    return out


def summary(conn,owner,on=None):
    on=on or client_plans.today()
    keys=[month_key(back(on,i)) for i in range(MONTHS-1,-1,-1)]
    totals={k:0 for k in keys};sources={}
    for month,label,cents in payments(conn,owner):
        if month in totals:
            totals[month]+=cents;sources.setdefault(month,{}).setdefault(label,0);sources[month][label]+=cents
    last=month_key(back(on,1));this=month_key(on)
    top=max(totals.values()) or 1
    months=[dict(key=k,label=back(on,MONTHS-1-i).strftime('%B %Y'),cents=totals[k],width=round(totals[k]/top*100),sources=sorted(sources.get(k,{}).items())) for i,k in enumerate(keys)]
    return dict(last=dict(label=back(on,1).strftime('%B %Y'),cents=totals[last]),this=dict(label=on.strftime('%B %Y'),cents=totals[this]),
      year=sum(totals.values()),months=months[::-1],any=any(totals.values()))


def register(app,get_db,login_required):
    @app.get('/income',strict_slashes=False)
    @login_required
    def income():
        import getpaid
        conn=get_db();owner=session['user_id']
        return render_template('income.html',s=summary(conn,owner),money=getpaid.money)

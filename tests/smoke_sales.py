"""Real localhost sales workflow + separate concurrent workers, fictional data only."""
from contextlib import closing
import hashlib
import hmac
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib import request,parse

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='agencyos-sales-smoke-') as temporary:
    database=str(Path(temporary)/'fictional-sales.db')
    event_secret=secrets.token_hex(32)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    environment=dict(os.environ,AGENCYOS_DB=database,AGENCYOS_SECRET_KEY=secrets.token_hex(32),
                     AGENCYOS_EMAIL_EVENT_SECRET=event_secret,AGENCYOS_AI_PROVIDER='',
                     AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE='',PORT=str(port),PYTHONDONTWRITEBYTECODE='1')
    with open(Path(temporary)/'server.log','w+') as log:
        process=subprocess.Popen([sys.executable,'app.py'],cwd=root,env=environment,stdout=log,stderr=log)
        try:
            base='http://127.0.0.1:'+str(port)
            opener=request.build_opener(request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            def get(path):
                with opener.open(base+path,timeout=10) as response:
                    assert response.status==200
                    return response.read().decode()
            for attempt in range(100):
                try:get('/setup');break
                except OSError:
                    if process.poll() is not None:raise RuntimeError('Server exited')
                    time.sleep(.1)
            else:raise RuntimeError('Server startup timeout')
            def post(path,fields,form='/sales'):
                page=get(form)
                fields=dict(fields,csrf_token=re.search(r'name="csrf_token" value="([^"]+)"',page)[1])
                with opener.open(base+path,data=parse.urlencode(fields,doseq=True).encode(),timeout=10) as response:
                    assert response.status==200
                    return response.read().decode()
            def row(sql):
                with closing(sqlite3.connect(database)) as conn:
                    conn.row_factory=sqlite3.Row
                    return conn.execute(sql).fetchone()
            def work(concurrent=1):
                workers=[subprocess.Popen([sys.executable,'manage.py','worker','--phase5'],cwd=root,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(concurrent)]
                output=[]
                for worker in workers:
                    out,err=worker.communicate(timeout=20)
                    assert worker.returncode==0,(out,err)
                    output.append(out)
                return output
            post('/setup',dict(username='fictional-owner',password='fictional-smoke-password'),'/setup')
            post('/login',dict(username='fictional-owner',password='fictional-smoke-password'),'/login')
            post('/sales/settings',dict(sender='owner@example.com',provider='mock',gst_mode='registered_10',daily_cents='0',daily_requests='0',input_rate='0',output_rate='0',pricing_model=''))
            post('/sales/packages',dict(name='Synthetic one-page',category='one-page',price='100.05',cycle='one-off',scope='Fictional one-page scope',exclusions='No hosting or publication'))
            for number in (1,2):
                post('/leads',dict(business_name='Fictional HTTP Studio '+str(number),industry='Design',website='https://studio'+str(number)+'.example/',email='prospect'+str(number)+'@example.com'),'/leads')
                post('/sales/new',dict(lead_id=str(number),package_ids=['1'],research_reference='new',tone='professional',mode='local',approve_lead='yes',synthetic='yes'))
            work(2)
            assert row("SELECT COUNT(*) n FROM p5_jobs WHERE kind='research' AND status='Needs review'")['n']==2
            post('/sales/jobs/1/decision',dict(decision='Approve research'))
            work()
            draft=row("SELECT * FROM p5_drafts WHERE flow_id=1 AND kind='outreach'")
            post('/sales/drafts/'+str(draft['id'])+'/approve',dict(recipient='prospect1@example.com',confirm='yes'))
            post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes'))
            work()
            message=row('SELECT * FROM p5_messages WHERE id=1')
            assert message['status']=='Mock accepted'
            post('/sales/messages/1/followup',dict(hours='24',confirm='yes'))
            event=dict(timestamp=int(time.time()),event_id='http-fictional-reply',provider_id=message['provider_id'],type='reply',text='Fictional test: what does the scope include?')
            raw=json.dumps(event).encode()
            signature=hmac.new(event_secret.encode(),raw,hashlib.sha256).hexdigest()
            for _ in range(2):
                req=request.Request(base+'/sales/events/mock',data=raw,headers={'Content-Type':'application/json','X-AgencyOS-Signature':signature})
                with opener.open(req,timeout=10) as response:assert response.status==200
            assert row('SELECT COUNT(*) n FROM p5_events')['n']==1
            assert row('SELECT status FROM p5_followups')['status']=='Stopped'
            work()
            classification=row("SELECT * FROM p5_jobs WHERE kind='classify'")
            assert json.loads(classification['result_json'])['classification']=='question'
            post('/sales/jobs/'+str(classification['id'])+'/decision',dict(decision='Prepare reply'))
            work()
            assert row("SELECT COUNT(*) n FROM p5_drafts WHERE kind='reply'")['n']==1
            post('/sales/1/proposal',dict(requirements='Synthetic customer requested one page',requirements_source='Fictional test correspondence only',branding='Fixture blue',confirm='yes',mode='local'))
            work()
            proposal=row("SELECT * FROM p5_drafts WHERE kind='proposal'")
            post('/sales/drafts/'+str(proposal['id'])+'/approve',dict(confirm='yes'))
            work()
            quote=row('SELECT * FROM p5_quotes')
            assert json.loads(quote['content_json'])['totals']['one-off']['total_cents']==11006
            post('/sales/quotes/'+str(quote['id'])+'/approve',dict(confirm='yes',recipient='prospect1@example.com'))
            post('/sales/quotes/'+str(quote['id'])+'/accept',dict(customer_name='Fictional Customer',evidence='Synthetic acceptance of this version for testing',evidence_source='Fictional fixture, not a real customer',quote_hash=quote['content_hash'],confirm='yes',confirm_project='yes'))
            assert row('SELECT COUNT(*) n FROM p5_project_briefs')['n']==1
            assert row('SELECT status FROM quotes')['status']=='Draft'
            assert 'Project #1 brief' in get('/sales/1')
            # Pause an independent flow between worker processes.
            post('/sales/jobs/2/decision',dict(decision='Approve research'))
            post('/agency/pause',dict(paused='1'))
            assert 'No queued task' in work()[0]
            post('/agency/pause',dict(paused='0'))
            work()
            assert row("SELECT COUNT(*) n FROM p5_drafts WHERE flow_id=2 AND kind='outreach'")['n']==1
            assert row('SELECT COUNT(*) n FROM p5_ai_usage')['n']==0
            assert row('SELECT COUNT(*) n FROM invoices')['n']==0
            print('PASS: real HTTP sales flow, two independent concurrent worker processes, approved research/outreach, mock dispatch, signed reply/replay, follow-up stop, reply handoff, proposal, precise GST quote and owner-attested acceptance/project brief')
            print('PASS: separate synthetic database, pause/resume across worker restarts, legacy quote remains Draft, no AI requests, real email, invoices, payments or publication')
        finally:
            process.terminate();process.wait(timeout=10)

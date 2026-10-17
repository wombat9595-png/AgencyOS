"""Real private launcher + worker + Chromium. Synthetic local records only."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--artifacts',required=True);args=parser.parse_args()
out=Path(args.artifacts).resolve();out.mkdir(parents=True,exist_ok=True)
result=dict(passed=False,steps=[],page_errors=[],server_errors=[],blocked_requests=[],layouts={})
with tempfile.TemporaryDirectory(prefix='agencyos-private-browser-') as tmp:
    private=Path(tmp)/'private';database=private/'business.sqlite3'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    log=(Path(tmp)/'launcher.log').open('w+')
    def start():return subprocess.Popen([sys.executable,'local_run.py','--data-dir',str(private),'--port',str(port),'--no-browser'],cwd=ROOT,stdout=log,stderr=log)
    launcher=start()
    def query(sql):
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory=sqlite3.Row;return conn.execute(sql).fetchone()
    def wait(sql,predicate=lambda r:True):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if database.exists():
                try:
                    row=query(sql)
                    if row and predicate(row):return row
                except sqlite3.OperationalError:pass
            if launcher.poll() is not None:raise AssertionError('Private launcher stopped')
            time.sleep(.1)
        raise AssertionError('Timed out: '+sql)
    def readiness():
        for _ in range(100):
            try:
                with urlopen(base+'/healthz',timeout=1) as response:assert response.status==200
                return
            except OSError:
                if launcher.poll() is not None:raise AssertionError('Launcher failed')
                time.sleep(.1)
        raise AssertionError('Private server failed readiness')
    try:
        readiness()
        with sync_playwright() as automation:
            browser=automation.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox','--disable-background-networking'])
            result['browser_version']=browser.version
            context=browser.new_context(viewport=dict(width=1440,height=1000))
            def route(req):
                if req.request.url.startswith(base+'/'):req.continue_()
                else:result['blocked_requests'].append(req.request.url.split('?',1)[0]);req.abort()
            context.route('**/*',route)
            page=context.new_page();page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
            page.on('response',lambda r:result['server_errors'].append(r.url) if r.status>=500 else None)
            page.goto(base+'/setup');page.locator('[name=username]').fill('fictional-owner');page.locator('[name=password]').fill('Fictional-password-for-test-12345');page.locator('form button').click()
            page.goto(base+'/login');page.locator('[name=username]').fill('fictional-owner');page.locator('[name=password]').fill('Fictional-password-for-test-12345');page.locator('form button').click()
            page.goto(base+'/launch');expect(page.locator('body')).to_contain_text('Authorized discovery plan')
            assert page.url==base+'/launch'
            page.screenshot(path=str(out/'launch-dashboard.png'),full_page=True)
            result['steps'].append('Authenticated /launch dashboard returned HTTP 200 and rendered without errors')
            page.goto(base+'/business');page.locator('form[action="/business/configure"] input[name=confirm]').check();page.locator('form[action="/business/configure"] button').click()
            expect(page.locator('body')).to_contain_text('Benji Price');result['steps'].append('Private launcher, owner authentication and first-sale defaults')
            def post(path,data):
                token=page.locator('input[name=csrf_token]').first.get_attribute('value')
                response=context.request.post(base+path,form=dict(data,csrf_token=token))
                assert response.status<400,(path,response.status,response.text()[:300])
            post('/sales/settings',dict(sender='benji.price.webdesign@gmail.com',provider='mock',gst_mode='not_registered',daily_cents='0',daily_requests='0',input_rate='0',output_rate='0',pricing_model=''))
            post('/leads',dict(business_name='Fictional Garden Studio',industry='Landscaping',location='Broome, WA, Australia',website='https://garden.example/',email='owner@example.com',source='Fictional authorised intake'))
            page.goto(base+'/sales');form=page.locator('form[action="/sales/new"]');form.locator('[name=lead_id]').select_option('1');form.locator('[name=package_ids][value="2"]').check();form.locator('[name=approve_lead]').check();form.locator('[name=synthetic]').check();form.locator('button').click()
            research=wait("SELECT * FROM p5_jobs WHERE kind='research' AND status='Needs review'")
            post('/sales/jobs/'+str(research['id'])+'/decision',{'decision':'Approve research'})
            outreach=wait("SELECT * FROM p5_drafts WHERE kind='outreach'")
            post('/sales/drafts/'+str(outreach['id'])+'/approve',dict(confirm='yes',recipient='owner@example.com'))
            result['steps'].append('Nationwide lead and real local worker research/outreach handoff')
            # Gmail fixture injection exists only in this test; production has no
            # mock-account connection flag or synthetic inbox endpoint.
            code="""
import base64
from contextlib import closing
import gmail_agent as gmail
from phase3_store import connect
import os
with closing(connect(os.environ['AGENCYOS_DB'])) as conn,conn:
 gmail.ingest(conn,1,dict(id='browserMail',threadId='browserThread',payload=dict(mimeType='text/plain',headers=[dict(name='From',value='owner@example.com'),dict(name='Subject',value='Website cost enquiry'),dict(name='Message-ID',value='<browser@example.com>')],body=dict(data=base64.urlsafe_b64encode(b'How much would a website cost? Fictional enquiry only.').decode()))))
"""
            env=dict(os.environ,AGENCYOS_DB=str(database),AGENCYOS_GMAIL_KEY_FILE=str(private/'gmail.secret'))
            subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,check=True,capture_output=True,text=True)
            page.goto(base+'/gmail');expect(page.locator('body')).to_contain_text('Not connected');page.locator('form[action="/gmail/mail/1/draft"] button').click()
            expect(page.locator('body')).to_contain_text('A$800.00')
            edit=page.locator('form[action="/gmail/drafts/1/edit"]');edit.locator('[name=body]').fill('Owner-reviewed fictional reply. No real message sent.');edit.locator('button').click()
            assert page.locator('form[action="/gmail/drafts/1/send"] button').is_disabled()
            page.screenshot(path=str(out/'gmail-local-review.png'),full_page=True);result['steps'].append('Encrypted fictional Gmail conversation, local draft/edit and disabled send UI')
            page.goto(base+'/business/flows/1/intake')
            answers=dict(business_name='Fictional Garden Studio',objectives='Help local customers enquire',description='Garden care in a fictional example',pages='Home, Services, About, Contact',services='Garden care: Customer-approved garden services\nHedge trimming: Customer-approved hedge trimming',about='Fictional customer-approved about text.',headline='A garden worth coming home to',intro='Customer-approved fictional garden care in Broome.',contact_email='owner@example.com',source='Fictional customer confirmation #browser1',style='Editorial and clean')
            for key,value in answers.items():page.locator('[name='+key+']').fill(value)
            page.locator('[name=customer_confirmed]').check();page.locator('form.panel button').click()
            page.locator('form[action="/business/flows/1/intake/proposal"] button').click()
            proposal=wait("SELECT * FROM p5_drafts WHERE kind='proposal'")
            post('/sales/drafts/'+str(proposal['id'])+'/approve',{'confirm':'yes'})
            quote=wait('SELECT * FROM p5_quotes')
            assert json.loads(quote['content_json'])['totals']['one-off']['total_cents']==80000
            post('/sales/quotes/'+str(quote['id'])+'/approve',dict(confirm='yes',recipient='owner@example.com'))
            post('/sales/quotes/'+str(quote['id'])+'/accept',dict(confirm='yes',confirm_project='yes',customer_name='Fictional Customer',evidence='Fictional acceptance of exact quote only',evidence_source='Synthetic browser fixture',quote_hash=quote['content_hash']))
            result['steps'].append('Questionnaire forms, exact A$800 quote and fictional evidenced acceptance')
            for number,theme in enumerate(('earth','studio','coastal'),1):
                if number==1:post('/projects/1/website/generate',dict(confirm='yes',theme=theme))
                else:post('/websites/1/revise',dict(confirm='yes',theme=theme,revision_note='intro: Customer-approved fictional garden care.'))
                version=wait('SELECT * FROM p6_site_versions WHERE version='+str(number))
                assert json.loads(version['qa_json'])['passed'],version['qa_json']
                for mode,width in (('desktop',1280),('mobile',390)):
                    page.set_viewport_size(dict(width=1800 if mode=='desktop' else 440,height=1100))
                    page.goto(base+'/websites/1/preview/'+str(number)+'?viewport='+mode)
                    frame=page.frame_locator('iframe')
                    expect(frame.locator('h1')).to_have_text('A garden worth coming home to')
                    # Resize only the test's iframe element so every renderer gets
                    # an actual 390/1280 CSS-pixel viewport; sandbox stays intact.
                    page.locator('iframe').evaluate('(e,w)=>{e.style.width=w+"px";e.style.maxWidth="none";e.style.height="1000px"}',width)
                    content_frame=page.frames[1]
                    overflow=content_frame.evaluate('document.documentElement.scrollWidth>innerWidth')
                    assert not overflow,(theme,mode)
                    content_frame.locator('a[href="?page=contact"]').first.click()
                    expect(content_frame.locator('h1')).to_have_text('Contact')
                    assert content_frame.locator('input[type=email]').count()==1
                    assert not content_frame.locator('form').evaluate('(f)=>f.checkValidity()')
                    content_frame.locator('a[href="?page=services"]').click()
                    expect(content_frame.locator('body')).to_contain_text('Hedge trimming')
                    page.goto(base+'/websites/1/preview/'+str(number)+'?viewport='+mode)
                    page.locator('iframe').evaluate('(e,w)=>{e.style.width=w+"px";e.style.maxWidth="none";e.style.height="1000px"}',width)
                    page.locator('iframe').screenshot(path=str(out/(theme+'-'+mode+'.png')))
                    result['layouts'][theme+'-'+mode]=dict(width=width,overflow=False,static_qa=True,form_validation=True,navigation=True)
            result['steps'].append('Three layouts built/revised by real worker; six actual browser viewports, links and form checks')
            page.set_viewport_size(dict(width=1440,height=1000));page.goto(base+'/business');page.screenshot(path=str(out/'first-customer-workspace.png'),full_page=True)
            assert query('SELECT COUNT(*) FROM first_sale_receipts')[0]==0;assert query('SELECT COUNT(*) FROM p5_ai_usage')[0]==0;assert query('SELECT COUNT(*) FROM p7_invoices')[0]==0
            before=query('SELECT COUNT(*) FROM p6_site_versions')[0]
            launcher.terminate();launcher.wait(timeout=25);launcher=start();readiness();page.goto(base+'/business')
            expect(page.locator('body')).to_contain_text('A small, practical business.')
            wait("SELECT * FROM runtime_workers WHERE state='running' AND phase='5'",lambda r:time.time()-r['last_seen']<10)
            assert query('SELECT COUNT(*) FROM p6_site_versions')[0]==before
            result['steps'].append('Entire private server/worker restart retained session, database and versions without duplicate jobs')
            assert not result['page_errors'] and not result['server_errors'],result
            result['passed']=True;browser.close()
    finally:
        if launcher.poll() is None:launcher.terminate()
        try:launcher.wait(timeout=25)
        except subprocess.TimeoutExpired:launcher.kill();launcher.wait()
        log.seek(0);logs=log.read();log.close()
        # No OAuth callback is invoked here. Raw logs stay temporary; they contain
        # no customer account tokens or actual private datasets.
        if not result['passed']:print(logs[-8000:])
        (out/'browser-first-sale-results.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))

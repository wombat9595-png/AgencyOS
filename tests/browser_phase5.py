"""Actual Chromium UI validation against isolated Flask + watch workers. No external requests."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

parser=argparse.ArgumentParser()
parser.add_argument('--artifacts',required=True)
parser.add_argument('--chromium',default=shutil.which('chromium'))
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
artifacts=Path(args.artifacts).resolve();artifacts.mkdir(parents=True,exist_ok=True)
result=dict(steps=[],page_errors=[],server_errors=[],blocked_external_requests=[],browser='Chromium',passed=False)
workers=[]

with tempfile.TemporaryDirectory(prefix='agencyos-browser-validation-') as temporary:
    database=str(Path(temporary)/'fictional browser.db')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    env=dict(os.environ,AGENCYOS_DB=database,AGENCYOS_SECRET_KEY=secrets.token_hex(32),AGENCYOS_AI_PROVIDER='',
             AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE='',PORT=str(port),PYTHONDONTWRITEBYTECODE='1')
    log=open(Path(temporary)/'server.log','w+')
    server=subprocess.Popen([sys.executable,'app.py'],cwd=root,env=env,stdout=log,stderr=log)

    def query(sql):
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory=sqlite3.Row
            return conn.execute(sql).fetchone()

    def wait_query(sql,predicate,timeout=12):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            row=query(sql)
            if row and predicate(row):return row
            time.sleep(.05)
        raise AssertionError('Database state timeout: '+sql)

    def worker(phase):
        output=open(Path(temporary)/('worker-'+phase+'.log'),'w+')
        proc=subprocess.Popen([sys.executable,'manage.py','worker','--phase'+phase,'--watch'],cwd=root,env=env,stdout=output,stderr=output)
        workers.append((proc,output))
        wait_query("SELECT * FROM runtime_workers WHERE phase='"+phase+"' AND state='running'",lambda row:True)
        return proc

    try:
        for _ in range(100):
            try:
                with urlopen(base+'/setup',timeout=1) as response:assert response.status==200
                break
            except OSError:
                if server.poll() is not None:raise AssertionError('Flask startup failed')
                time.sleep(.1)
        else:raise AssertionError('Server readiness timeout')
        with sync_playwright() as automation:
            launch_options=dict(headless=True,args=['--no-sandbox','--disable-background-networking','--disable-component-update'])
            if args.chromium: launch_options['executable_path']=args.chromium
            browser=automation.chromium.launch(**launch_options)
            result['browser_version']=browser.version
            context=browser.new_context(viewport=dict(width=1440,height=1000))
            def network(route):
                if route.request.url.startswith(base+'/'):route.continue_()
                else:
                    result['blocked_external_requests'].append(urlsplit(route.request.url).netloc)
                    route.abort()
            context.route('**/*',network)
            page=context.new_page()
            page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
            page.on('response',lambda response:result['server_errors'].append(dict(path=urlsplit(response.url).path,status=response.status)) if response.status>=500 else None)

            def step(name):
                result['steps'].append(name);print('PASS: '+name,flush=True)

            def go(path):
                response=page.goto(base+path,wait_until='domcontentloaded')
                assert response.status==200,(path,response.status)

            def submit(form,button,expected=302):
                action=form.get_attribute('action') or urlsplit(page.url).path
                with page.expect_response(lambda response:response.request.method=='POST' and urlsplit(response.url).path==action) as captured:
                    form.get_by_role('button',name=button,exact=True).click()
                assert captured.value.status==expected,(action,captured.value.status)
                page.wait_for_load_state('domcontentloaded')

            def fill(form,**fields):
                for name,value in fields.items():form.locator('[name="'+name+'"]').fill(value)

            go('/setup');form=page.locator('form[method=post]')
            fill(form,username='fictional-browser-owner',password='fictional-browser-password')
            submit(form,'Create account')
            form=page.locator('form[method=post]');fill(form,username='fictional-browser-owner',password='fictional-browser-password');submit(form,'Sign in')
            step('Owner setup and login through real Chromium forms')

            for path,heading in [('/leads','Leads & clients'),('/sales','Sales team'),('/agency','Agency Manager'),('/agents','Agent Control Center')]:
                go(path);expect(page.get_by_role('heading',name=heading,exact=True)).to_be_visible()
            step('Leads, Sales Team, Agency Manager and Agent Control Center navigation')

            go('/leads')
            for number in (1,2):
                form=page.locator('form[method=post]').filter(has=page.locator('[name=business_name]'))
                fill(form,business_name='Fictional Browser Studio '+str(number),email='prospect'+str(number)+'@example.com',website='https://browser'+str(number)+'.example/',industry='Design',location='Sydney')
                submit(form,'Save lead')
            step('Multiple fictional lead creation')

            worker('5')
            go('/agency');form=page.locator('form[action="/agency/queue"]')
            form.locator('[name=lead_id]').select_option('2');form.locator('[name=kind]').select_option('research');submit(form,'Prepare task')
            assert query('SELECT attempts FROM p4_jobs WHERE id=1')['attempts']==0
            go('/agency');page.locator('#worker-status > summary').click()
            expect(page.locator('#worker-status')).to_contain_text('No recent matching worker')
            worker('4')
            wait_query('SELECT * FROM p4_jobs WHERE id=1',lambda row:row['status']=='Awaiting review')
            go('/agency/jobs/1');form=page.locator('form[action="/agency/jobs/1/decision"]').filter(has=page.get_by_role('button',name='Approve result',exact=True));submit(form,'Approve result')
            step('Wrong-phase Attempts 0 reproduced; matching Phase 4 watch worker drains research and UI review succeeds')

            go('/sales');form=page.locator('form[action="/sales/packages"]')
            fill(form,name='Fictional browser one-page',price='100.05',scope='One responsive fictional service page',exclusions='Hosting and publication')
            submit(form,'Save immutable package version')
            form=page.locator('form[action="/sales/new"]');form.locator('[name=lead_id]').select_option('1');form.locator('[name=package_ids][value="1"]').check();form.locator('[name=approve_lead]').check();form.locator('[name=synthetic]').check();submit(form,'Start sales workflow')
            wait_query('SELECT * FROM p5_jobs WHERE id=1',lambda row:row['status']=='Needs review')
            go('/sales/1');form=page.locator('form[action="/sales/jobs/1/decision"]').filter(has=page.get_by_role('button',name='Approve research and queue outreach',exact=True));submit(form,'Approve research and queue outreach')
            wait_query('SELECT COUNT(*) n FROM p5_drafts',lambda row:row['n']==1)
            step('Phase 5 watch worker claims local research and approved handoff produces personalised outreach')

            go('/sales/1');form=page.locator('form[action="/sales/drafts/1/approve"]');fill(form,recipient='prospect1@example.com');form.locator('[name=confirm]').check();submit(form,'Approve draft and prepare correspondence',expected=400)
            expect(page.get_by_role('link',name='Configure sender and quote settings')).to_be_visible()
            page.get_by_role('link',name='Configure sender and quote settings').click()
            form=page.locator('form[action="/sales/settings"]');fill(form,sender='owner@example.com');form.locator('[name=gst_mode]').select_option('registered_10');submit(form,'Save controls')
            page.locator('#existing-opportunities a[href="/sales/1"]').click()
            form=page.locator('form[action="/sales/drafts/1/approve"]');fill(form,recipient='prospect1@example.com');form.locator('[name=confirm]').check();submit(form,'Approve draft and prepare correspondence')
            step('Missing sender error is actionable; configure metadata and resume preserved draft in existing opportunity')

            form=page.locator('form[action="/sales/messages/1/approve"]');form.locator('[name=confirm]').check();form.locator('[name=mock_authorisation]').check();submit(form,'Queue mock dispatch (no email)')
            wait_query('SELECT * FROM p5_messages WHERE id=1',lambda row:row['status']=='Mock accepted')
            go('/sales/1');form=page.locator('form[action="/sales/messages/1/followup"]');fill(form,hours='1');form.locator('[name=confirm]').check();submit(form,'Schedule internal review')
            details=page.locator('details').filter(has=page.locator('form[action="/sales/messages/1/record"]'));details.locator('summary').click()
            form=page.locator('form[action="/sales/messages/1/record"]');fill(form,text='Fictional browser reply: what does the page include?');form.locator('[name=confirm]').check();submit(form,'Record event and stop stale follow-ups')
            classification=wait_query("SELECT * FROM p5_jobs WHERE kind='classify'",lambda row:row['status']=='Needs review')
            assert query('SELECT status FROM p5_followups')['status']=='Stopped'
            go('/sales/1');form=page.locator('form[action="/sales/jobs/'+str(classification['id'])+'/decision"]').filter(has=page.get_by_role('button',name='Review interpretation and prepare local reply',exact=True));submit(form,'Review interpretation and prepare local reply')
            wait_query("SELECT COUNT(*) n FROM p5_drafts WHERE kind='reply'",lambda row:row['n']==1)
            step('Mock dispatch, owner-recorded original reply, stopped follow-up and reviewed reply-agent handoff')

            go('/sales/1');form=page.locator('form[action="/sales/1/proposal"]')
            fill(form,requirements='Fictional customer requests one service page',requirements_source='Fictional browser test fixture only',branding='Fictional blue branding');form.locator('[name=confirm]').check();submit(form,'Queue proposal')
            proposal=wait_query("SELECT * FROM p5_drafts WHERE kind='proposal'",lambda row:True)
            go('/sales/1');form=page.locator('form[action="/sales/drafts/'+str(proposal['id'])+'/approve"]');form.locator('[name=confirm]').check();submit(form,'Approve proposal and queue quote')
            quote=wait_query('SELECT * FROM p5_quotes',lambda row:True)
            assert json.loads(quote['content_json'])['totals']['one-off']['total_cents']==11006
            go('/sales/1');form=page.locator('form[action="/sales/quotes/'+str(quote['id'])+'/approve"]');fill(form,recipient='prospect1@example.com');form.locator('[name=confirm]').check();submit(form,'Approve quote version')
            details=page.locator('details').filter(has=page.locator('form[action="/sales/quotes/'+str(quote['id'])+'/accept"]'));details.locator('summary').click()
            form=page.locator('form[action="/sales/quotes/'+str(quote['id'])+'/accept"]');fill(form,customer_name='Fictional browser customer',evidence='Explicit fictional acceptance for automated UI validation',evidence_source='Synthetic browser fixture');form.locator('[name=confirm]').check();form.locator('[name=confirm_project]').check();submit(form,'Record acceptance and create project brief')
            brief=json.loads(query('SELECT brief_json FROM p5_project_briefs')['brief_json'])
            assert brief['acceptance']['evidence']=='Explicit fictional acceptance for automated UI validation'
            assert brief['branding_references']=='Fictional blue branding' and not brief['website_generation_authorised'] and not brief['publication_authorised']
            assert query('SELECT COUNT(*) n FROM projects')['n']==1
            expect(page.get_by_role('button',name='Queue proposal',exact=True)).to_have_count(0)
            page.get_by_role('heading',name='Project #1 brief',exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts/'sales-project-brief.png'))
            step('Proposal review, exact GST quote approval and one owner-attested project brief with complete acceptance evidence')

            go('/projects');page.get_by_role('link',name='Build and preview website ↗').click();page.wait_for_load_state('domcontentloaded')
            expect(page.get_by_role('heading',name='Website project from Phase 5 quote #1',exact=True)).to_be_visible()
            form=page.locator('form[action="/projects/1/website/generate"]');form.locator('[name=confirm]').check();submit(form,'Queue website build')
            wait_query('SELECT * FROM p6_site_versions WHERE site_id=1',lambda row:row['status']=='Needs review')
            go('/projects/1/website');expect(page.get_by_role('heading',name='Website QA · Passed',exact=True)).to_be_visible()
            page.get_by_role('link',name='Desktop preview').click();page.wait_for_load_state('domcontentloaded')
            expect(page.locator('iframe')).to_have_count(1)
            frame=page.frame_locator('iframe');expect(frame.locator('nav[aria-label="Main navigation"] a')).to_have_count(3)
            expect(frame.locator('input[required]')).to_have_count(2)
            full_height=frame.locator('html').evaluate('(el) => el.scrollHeight')
            page.locator('iframe').evaluate('(el,height) => el.style.height = height + "px"',full_height)
            page.locator('iframe').screenshot(path=str(artifacts/'website-desktop.png'))
            page.get_by_role('link',name='Back to build').click();page.wait_for_load_state('domcontentloaded')
            form=page.locator('form[action="/websites/1/revise"]');fill(form,revision_note='headline: A clearer browser website headline');submit(form,'Queue revision')
            wait_query('SELECT * FROM p6_site_versions WHERE site_id=1 AND version=2',lambda row:row['status']=='Needs review')
            go('/projects/1/website')
            expect(page.get_by_role('heading',name='Latest version · v2',exact=True)).to_be_visible()
            page.get_by_role('link',name='Mobile preview').click();page.wait_for_load_state('domcontentloaded')
            page.set_viewport_size(dict(width=390,height=844));frame=page.frame_locator('iframe')
            full_height=frame.locator('html').evaluate('(el) => el.scrollHeight')
            page.locator('iframe').evaluate('(el,height) => el.style.height = height + "px"',full_height)
            page.locator('iframe').screenshot(path=str(artifacts/'website-mobile.png'))
            page.get_by_role('link',name='Back to build').click();page.wait_for_load_state('domcontentloaded')
            form=page.locator('form[action="/websites/1/approve/2"]');form.locator('[name=confirm]').check();submit(form,'Approve website version')
            assert query('SELECT status FROM p6_site_versions WHERE site_id=1 AND version=2')['status']=='Approved'
            step('Phase 6 local worker build, QA review, isolated desktop/mobile previews, revision and version approval')

            go('/agency');form=page.locator('form[action="/agency/pause"]');submit(form,'Emergency pause')
            expect(page.get_by_role('heading',name='Emergency pause active',exact=True)).to_be_visible()
            form=page.locator('form[action="/agency/pause"]');submit(form,'Resume approved work')
            go('/sales');page.locator('#worker-status > summary').click();expect(page.locator('#worker-status')).to_contain_text('Recent matching worker connected')
            page.screenshot(path=str(artifacts/'sales-worker-status.png'),full_page=True)
            step('Emergency pause/resume and matching database/worker diagnostics')
            # Narrow-screen navigation check; not a complete accessibility/visual audit.
            page.set_viewport_size(dict(width=390,height=844));go('/sales')
            expect(page.get_by_role('heading',name='Sales team',exact=True)).to_be_visible()
            result['mobile_horizontal_overflow']=page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(artifacts/'sales-mobile.png'),full_page=True)
            assert query('SELECT COUNT(*) n FROM p5_ai_usage')['n']==0
            assert query('SELECT COUNT(*) n FROM invoices')['n']==0
            assert not result['page_errors'] and not result['server_errors'],result
            result['passed']=True
            context.close();browser.close()
    except Exception as error:
        result['failure']=str(error)
        raise
    finally:
        for proc,output in workers:
            if proc.poll() is None:proc.terminate()
            proc.wait(timeout=10);output.close()
        server.terminate();server.wait(timeout=10);log.close()
        result['blocked_external_requests']=sorted(set(result['blocked_external_requests']))
        (artifacts/'browser-results.json').write_text(json.dumps(result,indent=2))

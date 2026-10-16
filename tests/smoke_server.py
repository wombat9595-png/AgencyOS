"""Launch the real server with an isolated synthetic database and exercise HTTP."""
import http.cookiejar
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib import request, parse

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(dir=root, prefix='.smoke-') as temporary:
    environment = dict(os.environ, AGENCYOS_DB=str(Path(temporary) / 'synthetic.db'),
                       AGENCYOS_SECRET_KEY='smoke-test-only', PORT='5057')
    with open(Path(temporary) / 'server.log', 'w+') as log:
        process = subprocess.Popen([sys.executable, 'app.py'], cwd=root, env=environment, stdout=log, stderr=log)
        try:
            opener = request.build_opener(request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            base = 'http://127.0.0.1:5057'
            for attempt in range(50):
                try:
                    with opener.open(base + '/setup', timeout=1) as response:
                        page = response.read().decode()
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError('Server exited during startup')
                    time.sleep(.1)
            else:
                raise RuntimeError('Server did not become ready')
            def post(path, fields):
                with opener.open(base + path) as response:
                    page = response.read().decode()
                fields['csrf_token'] = re.search(r'name="csrf_token" value="([^"]+)"',page)[1]
                with opener.open(base + path, data=parse.urlencode(fields).encode()) as response:
                    assert response.status == 200
                    return response.read().decode()
            post('/setup', {'username':'synthetic-owner','password':'synthetic-smoke-password'})
            page = post('/login', {'username':'synthetic-owner','password':'synthetic-smoke-password'})
            assert 'Build better websites' in page
            post('/leads', {'business_name':'HTTP Synthetic Studio','location':'Sydney'})
            for path in ('/', '/leads','/outreach','/quotes','/invoices','/projects','/settings','/lead-finder','/agents','/agents/tasks/new','/operations','/workflows','/discovery','/research?lead_id=1','/outreach/history','/static/style.css'):
                with opener.open(base + path) as response:
                    assert response.status == 200, path
            with opener.open(base + '/') as response:
                assert b'HTTP Synthetic Studio' in response.read()
            page = post('/agents/tasks/new', {'agent_id':'lead-research','lead_id':'1',
                        'title':'HTTP agent smoke','mode':'local','instructions':'Review enquiry options'})
            assert 'Queued' in page
            def task_post(path, fields):
                with opener.open(base + '/agents/tasks/1') as response:
                    page = response.read().decode()
                fields['csrf_token'] = re.search(r'name="csrf_token" value="([^"]+)"',page)[1]
                with opener.open(base + path, data=parse.urlencode(fields).encode()) as response:
                    assert response.status == 200
                    return response.read().decode()
            page = task_post('/agents/tasks/1/run', {})
            assert 'Awaiting review' in page and 'No website was fetched or inspected' in page
            page = task_post('/agents/tasks/1/review', {'decision':'Approved'})
            assert 'Future action proposal' in page
            page = task_post('/agents/tasks/1/action-requests', {'action_type':'email','description':'Synthetic proposal only'})
            assert 'Pending' in page
            page = task_post('/agents/approvals/1/decide', {'decision':'Rejected'})
            assert 'Rejected' in page and 'not executed' in page
            page=post('/research?lead_id=1',{'lead_id':'1','mode':'local'})
            assert 'Queued' in page
            subprocess.run([sys.executable,'manage.py','worker'],cwd=root,env=environment,check=True,capture_output=True)
            page=task_post('/workflows/1/decision',{'decision':'Approved'})
            assert 'Unverified opportunities' in page
            post('/outreach/history',{'research_id':'1','mode':'local'})
            subprocess.run([sys.executable,'manage.py','worker'],cwd=root,env=environment,check=True,capture_output=True)
            page=task_post('/outreach/history/1/review',{'status':'Approved','follow_up_date':'2027-01-15'})
            assert 'Draft #1' in page and 'Nothing sent' in page
            # Phase 4: real HTTP assignment, process restart, schedule handoff and pause.
            for path in ('/agency','/discovery/licensed'):
                with opener.open(base+path) as response:
                    assert response.status==200
            def manager_post(path,fields):
                with opener.open(base+'/agency') as response:
                    fields['csrf_token']=re.search(r'name="csrf_token" value="([^"]+)"',response.read().decode())[1]
                with opener.open(base+path,data=parse.urlencode(fields).encode()) as response:
                    assert response.status==200
                    return response.read().decode()
            page=manager_post('/agency/queue',{'lead_id':'1','kind':'qualification','handoff':'yes'})
            assert 'Queued' in page
            for _ in range(2):
                subprocess.run([sys.executable,'manage.py','worker','--phase4'],cwd=root,env=environment,check=True,capture_output=True)
            with opener.open(base+'/agency/jobs/1') as response:
                assert b'Awaiting review' in response.read()
            with opener.open(base+'/agency/jobs/2') as response:
                assert b'Deterministic local research' in response.read()
            manager_post('/agency/schedules',{'lead_id':'1','hours':'24','confirm':'yes'})
            subprocess.run([sys.executable,'manage.py','worker','--phase4'],cwd=root,env=environment,check=True,capture_output=True)
            manager_post('/agency/pause',{'paused':'1'})
            stopped=subprocess.run([sys.executable,'manage.py','worker','--phase4'],cwd=root,env=environment,check=True,capture_output=True,text=True)
            assert 'No queued task' in stopped.stdout
            manager_post('/agency/pause',{'paused':'0'})
            subprocess.run([sys.executable,'manage.py','worker','--phase4'],cwd=root,env=environment,check=True,capture_output=True)
            print('PASS: Phase 4 HTTP assignment, immutable qualification, local research handoff, persistent schedules, separate worker restarts and emergency pause')
            print('PASS: Phase 3 real HTTP queue, separate worker process, local research, approved-research drafting and saved review history')
            print('PASS: local agent task assignment, run, result review and separate action rejection; no external requests')
            print('PASS: real HTTP server, owner setup, login, lead creation, dashboard, all workspace pages and stylesheet')
        finally:
            process.terminate()
            process.wait(timeout=10)

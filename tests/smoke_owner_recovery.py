"""Real HTTP login recovery for an existing fictional CEO; no new owner record."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import build_opener,HTTPCookieProcessor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from owner_recovery import reset_owner

with tempfile.TemporaryDirectory(prefix='agencyos-owner-recovery-') as tmp:
    home=Path(tmp);database=home/'existing.db'
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    env=dict(os.environ,AGENCYOS_DB=str(database),PORT=str(port),AGENCYOS_SECRET_KEY=secrets.token_hex(32),AGENCYOS_SECRET_KEY_FILE='',AGENCYOS_ENV='development',AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE='')
    log=(home/'server.log').open('w+')
    server=subprocess.Popen([sys.executable,'app.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
    client=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()));base='http://127.0.0.1:'+str(port)
    def get(path):
        with client.open(base+path,timeout=5) as response:return response.status,response.read().decode(),response.url
    def post(path,data):
        _,body,_=get('/login');token=re.search('name="csrf_token" value="([^"]+)"',body).group(1)
        with client.open(base+path,data=urlencode(dict(data,csrf_token=token)).encode(),timeout=5) as response:return response.read().decode()
    try:
        for _ in range(100):
            try:get('/healthz');break
            except OSError:
                if server.poll() is not None:raise AssertionError('Server failed before recovery test')
                time.sleep(.1)
        else:raise AssertionError('Server did not start')
        post('/setup',dict(username='CEO',password='Fictional-original-password-12345'))
        post('/login',dict(username='CEO',password='Fictional-original-password-12345'))
        assert get('/launch')[2].endswith('/launch')
        with closing(sqlite3.connect(database)) as conn,conn:
            conn.execute("INSERT INTO leads(business_name,status,created_at) VALUES('Fictional preserved business','New','fixture')")
        result=reset_owner(database,'Fictional-new-owner-password-67890',home/'private-backups',(1,'CEO'))
        assert get('/launch')[2].endswith('/login') or '/login?' in get('/launch')[2]
        assert 'Invalid username or password' in post('/login',dict(username='CEO',password='Fictional-original-password-12345'))
        post('/login',dict(username='CEO',password='Fictional-new-owner-password-67890'))
        status,body,url=get('/launch');assert status==200 and url.endswith('/launch')
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute('SELECT id,username FROM users').fetchall()==[(1,'CEO')]
            assert conn.execute('SELECT business_name FROM leads').fetchone()[0]=='Fictional preserved business'
        assert Path(result['backup']).is_file()
        print(json.dumps(dict(passed=True,existing_owner='CEO',new_accounts_created=0,business_records_preserved=True,old_password_rejected=True,old_session_revoked=True,recovered_login_http_status=200,external_requests=0)))
    except Exception:
        log.seek(0);print(log.read()[-3000:]);raise
    finally:
        server.terminate()
        try:server.wait(timeout=15)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        log.close()

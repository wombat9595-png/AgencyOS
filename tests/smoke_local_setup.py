"""Exercise the private launcher using only the zero-cost pinned runtime."""
from contextlib import closing
import http.cookiejar
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import build_opener,HTTPCookieProcessor

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='agencyos-clean-local-') as tmp:
    private=Path(tmp)/'Private business data'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base='http://127.0.0.1:'+str(port);database=private/'business.sqlite3'
    with (Path(tmp)/'launcher.log').open('w+') as log:
        proc=subprocess.Popen([sys.executable,'local_run.py','--data-dir',str(private),'--port',str(port),'--no-browser'],cwd=ROOT,stdout=log,stderr=log)
        client=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def get(path):
            with client.open(base+path,timeout=5) as response:
                assert response.status==200
                return response.read().decode()
        def post(path,fields):
            body=get('/login' if path in ('/setup','/login') else '/business')
            token=re.search('name="csrf_token" value="([^"]+)"',body).group(1)
            with client.open(base+path,data=urlencode(dict(fields,csrf_token=token)).encode(),timeout=5) as response:assert response.status==200
        try:
            for _ in range(100):
                try:get('/healthz');break
                except OSError:
                    if proc.poll() is not None:raise AssertionError('Private launcher exited')
                    time.sleep(.1)
            else:raise AssertionError('Private readiness timeout')
            post('/setup',dict(username='fictional-owner',password='Fictional-clean-runtime-password-123'))
            post('/login',dict(username='fictional-owner',password='Fictional-clean-runtime-password-123'))
            assert 'Authorized discovery plan' in get('/launch')
            assert 'What matters now' in get('/business') and 'A small, practical business.' in get('/business/details')
            assert 'Not connected' in get('/gmail')
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                with closing(sqlite3.connect(database)) as conn:
                    workers=conn.execute("SELECT COUNT(*) FROM runtime_workers WHERE state='running'").fetchone()[0]
                    if workers==3:break
                time.sleep(.1)
            else:raise AssertionError('Private coordinator missing heartbeats')
            for name in ('session.secret','gmail.secret','bank.secret','backup.secret','business.sqlite3'):
                assert (private/name).stat().st_mode&0o777==0o600
            print(json.dumps(dict(passed=True,python=sys.version.split()[0],dashboard_http_status=200,dashboard_path='/launch',
                local_workers_verified=3,private_file_modes='0600',gmail_connected=False,live_sending=False,external_provider_calls=0)))
        except Exception:
            log.seek(0);print(log.read()[-4000:]);raise
        finally:
            if proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=25)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()

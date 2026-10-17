"""Actual Gunicorn process with strict configuration, isolated provisioning and encrypted restore."""
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from cryptography.fernet import Fernet

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='agencyos-production-smoke-') as tmp:
    temp=Path(tmp);database=temp/'agencyos.sqlite3';password=temp/'owner.secret';password.write_text('Fictional-only-password-12345')
    key=temp/'session.key';key.write_text(secrets.token_hex(32));backupkey=temp/'backup.key';backupkey.write_bytes(Fernet.generate_key())
    env=dict(os.environ,AGENCYOS_ENV='development',AGENCYOS_DB=str(database),AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE='')
    def command(*args):
        result=subprocess.run([sys.executable,*args],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr)
        return result
    command('production.py','migrate','--database',str(database))
    command('production.py','create-owner','--database',str(database),'--username','fictional-owner','--password-file',str(password))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env.update(AGENCYOS_ENV='production',AGENCYOS_TRUSTED_HOSTS='127.0.0.1',AGENCYOS_SECRET_KEY_FILE=str(key))
    server=subprocess.Popen([sys.executable,'-m','gunicorn','--bind',f'127.0.0.1:{port}','--workers','1','--threads','2','wsgi:app'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                with urlopen(base+'/readyz',timeout=1) as response:assert response.status==200
                break
            except (URLError,OSError):
                if server.poll() is not None:raise AssertionError(server.stderr.read().decode())
                time.sleep(.1)
        else:raise AssertionError('Gunicorn readiness timeout')
        for path,status in (('/setup',403),('/healthz',200)):
            try:response=urlopen(base+path);actual=response.status
            except HTTPError as exc:actual=exc.code
            assert actual==status,(path,actual)
        try:urlopen(Request(base+'/healthz',headers={'Host':'attacker.example'}));raise AssertionError('Untrusted host accepted')
        except HTTPError as exc:assert exc.code==400
        with urlopen(base+'/login') as response:
            body=response.read().decode();cookie=response.headers['Set-Cookie'].split(';')[0]
            assert '__Host-agencyos=' in cookie and 'Secure' in response.headers['Set-Cookie']
        csrf=re.search('name="csrf_token" value="([^"]+)"',body).group(1)
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        request=Request(base+'/login',data=urlencode(dict(username='fictional-owner',password=password.read_text(),csrf_token=csrf)).encode(),headers={'Cookie':cookie})
        try:build_opener(NoRedirect()).open(request);raise AssertionError('Login did not redirect')
        except HTTPError as exc:assert exc.code==302
        backup=temp/'backup.enc';restore=temp/'restored'
        command('production.py','backup','--database',str(database),'--output',str(backup),'--key-file',str(backupkey))
        command('production.py','restore','--database',str(database),'--input',str(backup),'--destination',str(restore),'--key-file',str(backupkey))
        import hashlib
        original=hashlib.sha256(database.read_bytes()).hexdigest()
        command('production.py','migrate','--database',str(restore/'database.sqlite3'),'--upgrade-copy')
        refused=subprocess.run([sys.executable,'production.py','migrate','--database',str(database)],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert refused.returncode!=0,'Existing database migration must require the explicit copy flag'
        assert hashlib.sha256(database.read_bytes()).hexdigest()==original,'Copy migration changed source database'
        command('production.py','check','--database',str(database))
        print('PASS: Gunicorn strict startup, health/readiness, bootstrap disabled, trusted-host rejection, secure session cookie, real login, encrypted CLI backup/restore, isolated copy migration/source preservation and operational check')
    finally:
        server.terminate()
        try:server.wait(timeout=10)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        server.stderr.close()

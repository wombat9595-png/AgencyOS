"""Actual launcher: occupied default, verified URL and duplicate-open recovery."""
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='agencyos-startup-recovery-') as tmp:
    home=Path(tmp)/'private';log=(Path(tmp)/'startup.log').open('w+')
    blocker=socket.socket()
    try:blocker.bind(('127.0.0.1',5000))
    except OSError:blocker.close() # Already occupied; never stop the existing app.
    command=[sys.executable,'local_run.py','--data-dir',str(home),'--no-browser']
    proc=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log)
    try:
        for _ in range(100):
            if proc.poll() is not None:raise AssertionError('Launcher stopped before opening the dashboard')
            try:
                record=json.loads((home/'launcher.json').read_text());url=record['url']
                with urlopen(url.rsplit('/',1)[0]+'/healthz',timeout=1) as response:assert response.status==200
                break
            except (OSError,ValueError):time.sleep(.1)
        else:raise AssertionError('Private dashboard startup timeout')
        assert ':5000/' not in url,url
        again=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
        assert again.returncode==0,again.stderr
        assert 'already running' in again.stdout and url in again.stdout
        assert json.loads((home/'launcher.json').read_text())['pid']==proc.pid
        print(json.dumps(dict(passed=True,occupied_default_recovered=True,verified_local_health=True,duplicate_launcher_reopened=True,other_apps_stopped=False)))
    except Exception:
        log.seek(0);print(log.read()[-4000:]);raise
    finally:
        if proc.poll() is None:proc.terminate()
        try:proc.wait(timeout=25)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close();blocker.close()
    assert not (home/'launcher.json').exists(),'Stale dashboard metadata retained after normal shutdown'

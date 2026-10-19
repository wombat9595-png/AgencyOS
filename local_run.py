"""Private, zero-subscription launcher and local worker supervisor.

Only explicit --import-database copies an existing database. The source is opened
read-only and never migrated. No public listeners, tunnel or login item is made.
"""
import argparse
from contextlib import closing
import fcntl
import json
import socket
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import subprocess
import sys
import time
import webbrowser

ROOT=Path(__file__).resolve().parent


def prepare(home,source=None):
    home=Path(home).expanduser()
    if home.is_symlink():raise ValueError('Private data directory cannot be a symbolic link')
    home=home.resolve();home.mkdir(mode=0o700,parents=True,exist_ok=True)
    if home.is_symlink():raise ValueError('Private data directory cannot be a symbolic link')
    home.chmod(0o700)
    from cryptography.fernet import Fernet
    if (home/'business.sqlite3').is_symlink():raise ValueError('The private database cannot be a symbolic link')
    if (home/'business.sqlite3').exists():
        required=('session.secret','gmail.secret','bank.secret','backup.secret')
        if any(not (home/name).is_file() for name in required):raise ValueError('Existing workspace is missing private keys. Restore its original keys; no replacements were generated.')
    for name,value in (('session.secret',secrets.token_hex(32).encode()),('gmail.secret',Fernet.generate_key()),('bank.secret',Fernet.generate_key()),('backup.secret',Fernet.generate_key())):
        path=home/name
        if path.is_symlink():raise ValueError('Private key cannot be a symbolic link')
        if not path.exists():
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as handle:handle.write(value)
        path.chmod(0o600)
    target=home/'business.sqlite3'
    if source:
        source=Path(source).expanduser().resolve()
        if target.exists():raise ValueError('A business database already exists; never overwrite it. Select a new --data-dir to import.')
        if not source.is_file() or source==target:raise ValueError('Choose an existing source database to copy')
        # Destination publication is atomic; a failed copy cannot become the app DB.
        temp=home/'importing.sqlite3'
        if temp.exists():raise ValueError('An interrupted import exists; inspect it before retrying')
        try:
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(temp)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Source copy failed integrity check')
            temp.chmod(0o600);temp.rename(target)
        except Exception:
            temp.unlink(missing_ok=True);raise
    # Inherited paid credentials cannot bypass the first-sale runtime policy.
    env=dict(os.environ,AGENCYOS_ENV='local',AGENCYOS_LOCAL_PRIVATE='1',AGENCYOS_ZERO_COST='1',AGENCYOS_DB=str(target),
      AGENCYOS_SECRET_KEY_FILE=str(home/'session.secret'),AGENCYOS_GMAIL_KEY_FILE=str(home/'gmail.secret'),
      AGENCYOS_GMAIL_CLIENT_FILE=str(home/'google-client.secret'),AGENCYOS_ANTHROPIC_KEY_FILE=str(home/'anthropic.secret'),AGENCYOS_BANK_ENCRYPTION_KEY_FILE=str(home/'bank.secret'),
      AGENCYOS_BACKUP_KEY_FILE=str(home/'backup.secret'),AGENCYOS_PRIVATE_DATA=str(home),AGENCYOS_STAGING_ROOT=str(home/'staging'),
      AGENCYOS_AI_PROVIDER='',AGENCYOS_OSM_POLICY_FILE='',AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_GMAIL_SEND_ENABLED='0',
      AGENCYOS_PAYMENT_PROVIDER='mock',AGENCYOS_STRIPE_TEST_SECRET_KEY='')
    return home,env


def worker_tick(path,private_data):
    import runtime_status,phase4,sales_engine,p8_ops,gmail_agent,first_sale,production_ops
    from phase3_store import connect
    from phase4_store import paused
    for phase in ('4','5','8'):runtime_status.heartbeat(path,'private-'+str(os.getpid())+'-'+phase,phase)
    # Independent queues share the exact canonical database selected by the app.
    worked=False
    for executor in (phase4.worker_once,sales_engine.worker_once,p8_ops.worker_tick,gmail_agent.poll_once):
        worked=bool(executor(path)) or worked
    with closing(connect(path)) as conn:
        if paused(conn):return worked
        first_sale.daily_report(conn)
        last=conn.execute('SELECT MAX(created_at) FROM ops_backups WHERE verified=1').fetchone()[0]
    import night_shift
    worked=night_shift.worker_tick(path) or worked
    if not last or time.time()-last>86400:
        from production_security import secret
        destination=Path(private_data)/'backups'/('business-'+time.strftime('%Y%m%dT%H%M%S',time.gmtime())+'-'+secrets.token_hex(3)+'.enc')
        production_ops.backup(path,destination,secret('AGENCYOS_BACKUP_KEY').encode(),Path(private_data)/'staging')
    return worked


def worker_main():
    import app,runtime_status
    running=True
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while running:
            try:
                worked=worker_tick(app.DB_PATH,os.environ['AGENCYOS_PRIVATE_DATA'])
            except Exception:
                # Never log provider/token bodies or customer text.
                print('Local worker error; review job history and private configuration. Retrying scheduler safely.',flush=True)
                time.sleep(30)
                worked=False
            if not worked:time.sleep(1)
    finally:
        for phase in ('4','5','8'):runtime_status.heartbeat(app.DB_PATH,'private-'+str(os.getpid())+'-'+phase,phase,'stopped')


def select_port(preferred=None):
    """Choose a loopback port without disturbing another app (e.g. AirPlay)."""
    candidates=[preferred] if preferred is not None else [5000,*range(5050,5060)]
    for candidate in candidates:
        if not 1024<=candidate<=65535:raise ValueError('Choose a local port from 1024 to 65535.')
        try:
            with socket.socket() as probe:probe.bind(('127.0.0.1',candidate))
            return candidate
        except OSError:
            if preferred is not None:raise ValueError('Local port '+str(candidate)+' is busy. Close the other launcher or omit --port for automatic selection.') from None
    raise ValueError('No local dashboard port is available. Close the other AgencyOS launcher and try again.')


def existing_dashboard(home):
    """Use only bounded private metadata and verify a local AgencyOS health reply."""
    from urllib.request import urlopen
    import re
    try:
        path=home/'launcher.json'
        if path.is_symlink() or path.stat().st_size>1024:return None
        url=json.loads(path.read_text()).get('url','')
        match=re.fullmatch(r'http://127\.0\.0\.1:([0-9]{4,5})/business',url)
        if not match or not 1024<=int(match[1])<=65535:return None
        with urlopen(url.rsplit('/',1)[0]+'/healthz',timeout=2) as response:
            if response.status==200 and json.loads(response.read(1000)).get('status')=='alive':return url
    except (OSError,ValueError,TypeError,AttributeError):pass
    return None


def main():
    parser=argparse.ArgumentParser(description='Private AgencyOS; no paid providers, live sending or public hosting.')
    parser.add_argument('--data-dir',default=str(Path.home()/'Library'/'Application Support'/'AgencyOS'))
    parser.add_argument('--import-database',help='Copy an existing database into a NEW private data directory; never modify source')
    parser.add_argument('--port',type=int,help='Optional fixed port; otherwise use 5000 or an available 5050–5059 port')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--server',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:worker_main();return
    if args.server:
        from app import app
        from werkzeug.serving import make_server
        from production_security import PrivateRequestHandler
        server=make_server('127.0.0.1',args.port or 5000,app,threaded=True,request_handler=PrivateRequestHandler)
        server.serve_forever();return
    os.umask(0o077)
    home=Path(args.data_dir).expanduser()
    if home.is_symlink():parser.error('Private data directory cannot be a symbolic link')
    home.mkdir(mode=0o700,parents=True,exist_ok=True)
    if (home/'launcher.lock').is_symlink():parser.error('Launcher lock cannot be a symbolic link')
    lock=(home/'launcher.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        url=existing_dashboard(home)
        if url:
            print('AgencyOS is already running. Dashboard: '+url,flush=True)
            if not args.no_browser:webbrowser.open(url)
            return
        parser.error('AgencyOS is already starting or running. Keep its launcher window open; retry opening this launcher in a moment.')
    args.port=select_port(args.port)
    home,env=prepare(home,args.import_database)
    # Make a verified, encrypted pre-migration snapshot of an existing workspace.
    if (home/'business.sqlite3').exists():
        from cryptography.fernet import Fernet
        backups=home/'backups';backups.mkdir(mode=0o700,exist_ok=True)
        with closing(sqlite3.connect(home/'business.sqlite3')) as src,closing(sqlite3.connect(':memory:')) as dst:
            src.backup(dst);raw=dst.serialize()
        backup_cipher=Fernet((home/'backup.secret').read_bytes())
        blob=backup_cipher.encrypt(raw)
        if backup_cipher.decrypt(blob)!=raw:raise ValueError('Pre-upgrade encryption verification failed')
        out=backups/('pre-upgrade-'+str(time.time_ns())+'.sqlite3.enc')
        out.write_bytes(blob);out.chmod(0o600)
    os.environ.update(env)
    import app
    app.init_db();Path(app.DB_PATH).chmod(0o600)
    children=[]
    def stop(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,stop)
    try:
        children.append(subprocess.Popen([sys.executable,str(ROOT/'local_run.py'),'--server','--port',str(args.port)],cwd=ROOT,env=env))
        from urllib.request import urlopen
        for _ in range(50):
            if children[0].poll() is not None:raise RuntimeError('Private server stopped before readiness')
            try:
                with urlopen('http://127.0.0.1:'+str(args.port)+'/healthz',timeout=1) as r:
                    if r.status==200:break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Private server readiness timeout')
        children.append(subprocess.Popen([sys.executable,str(ROOT/'local_run.py'),'--worker'],cwd=ROOT,env=env))
        dashboard_url='http://127.0.0.1:'+str(args.port)+'/business'
        metadata=home/'launcher.json'
        if metadata.is_symlink():raise ValueError('Private launcher metadata cannot be a symbolic link')
        metadata.write_text(json.dumps(dict(url=dashboard_url,pid=os.getpid())))
        metadata.chmod(0o600)
        print('Dashboard: '+dashboard_url+'\nLaunch dashboard: '+dashboard_url.rsplit('/',1)[0]+'/launch',flush=True)
        print('AgencyOS private workspace ready. Live sending and paid APIs disabled. Close this launcher to stop. Data: '+str(home),flush=True)
        if not args.no_browser:webbrowser.open(dashboard_url)
        while True:
            if any(p.poll() is not None for p in children):raise RuntimeError('A local process stopped; restart the launcher. Durable jobs and approvals remain saved.')
            time.sleep(1)
    except KeyboardInterrupt:pass
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        metadata=home/'launcher.json'
        if metadata.is_file() and not metadata.is_symlink():
            try:
                if json.loads(metadata.read_text()).get('pid')==os.getpid():metadata.unlink()
            except (OSError,ValueError):pass
        lock.close()


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError) as exc:
        print('AgencyOS could not start: '+str(exc),file=sys.stderr)
        sys.exit(1)

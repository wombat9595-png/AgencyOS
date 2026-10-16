"""Local operational metadata, encrypted backup/restore and actionable alerts."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path
from cryptography.fernet import Fernet
from phase3_store import connect

MAX_BACKUP=128*1024*1024


def migrate(conn):
    conn.executescript('''CREATE TABLE IF NOT EXISTS ops_backups (
      id INTEGER PRIMARY KEY, file_hash TEXT NOT NULL, created_at REAL NOT NULL, verified INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS ops_alerts (
      id INTEGER PRIMARY KEY, category TEXT NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL,
      created_at REAL NOT NULL, last_seen REAL NOT NULL, resolved_at REAL);
    CREATE UNIQUE INDEX IF NOT EXISTS ops_one_open_alert ON ops_alerts(category,subject) WHERE resolved_at IS NULL;
    ''')


def backup(database,output,key,staging_root=None):
    """SQLite online backup + inert artifacts, authenticated encryption; no overwrite."""
    if not Path(database).is_file():raise ValueError('Source database does not exist')
    with tempfile.TemporaryDirectory() as tmp:
        snapshot=Path(tmp)/'database.sqlite3'
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Source integrity check failed')
        files={'database.sqlite3':snapshot.read_bytes()}
        if staging_root and Path(staging_root).exists():
            for path in Path(staging_root).rglob('*'):
                if path.is_symlink():raise ValueError('Backup refuses artifact symlinks')
                if path.is_file():
                    if path.stat().st_size>MAX_BACKUP:raise ValueError('Artifact exceeds backup limit')
                    files['staging/'+path.relative_to(staging_root).as_posix()]=path.read_bytes()
        if sum(len(v) for v in files.values())>MAX_BACKUP:raise ValueError('Backup exceeds 128 MiB local safety limit')
        manifest={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in files.items():archive.writestr(name,raw)
            archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        encrypted=Fernet(key).encrypt(stream.getvalue())
        output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
        descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as handle:handle.write(encrypted)
        if Fernet(key).decrypt(output.read_bytes())!=stream.getvalue():raise ValueError('Encrypted backup verification failed')
        digest=hashlib.sha256(encrypted).hexdigest()
        with closing(connect(database)) as conn,conn:
            conn.execute('INSERT INTO ops_backups(file_hash,created_at,verified) VALUES(?,?,1)',(digest,time.time()))
        return dict(file_hash=digest,files=len(files),bytes=len(encrypted))


def restore(source,destination,key):
    """Restore only into a new isolated directory. Never replaces a database."""
    destination=Path(destination)
    if destination.exists():raise ValueError('Restore destination must not exist')
    if Path(source).stat().st_size>MAX_BACKUP*2:raise ValueError('Encrypted input is oversized')
    plain=Fernet(key).decrypt(Path(source).read_bytes())
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or 'manifest.json' not in names:raise ValueError('Invalid backup archive')
        if sum(item.file_size for item in archive.infolist())>MAX_BACKUP:raise ValueError('Archive exceeds restore limit')
        manifest=json.loads(archive.read('manifest.json'))
        if set(manifest)|{'manifest.json'}!=set(names):raise ValueError('Unexpected backup members')
        files={}
        for name,expected in manifest.items():
            if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name or not (name=='database.sqlite3' or name.startswith('staging/')):
                raise ValueError('Unsafe restore member')
            raw=archive.read(name)
            if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Backup member hash mismatch')
            files[name]=raw
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        root=Path(tmp)/'restore';root.mkdir(mode=0o700)
        for name,raw in files.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);target.chmod(0o600)
        with closing(sqlite3.connect(root/'database.sqlite3')) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Restored database integrity failed')
        root.rename(destination)
    return dict(files=len(files),integrity='ok',destination=str(destination))


def collect_alerts(database,now=None):
    now=now or time.time();active=[]
    with closing(connect(database)) as conn,conn:
        for table in ('p3_jobs','p4_jobs','p5_jobs','agent_tasks'):
            failed=conn.execute("SELECT COUNT(*) FROM "+table+" WHERE status IN ('Failed','Interrupted')").fetchone()[0]
            if failed:active.append(('failed_jobs',table,str(failed)+' failed/interrupted jobs require review.'))
        for phase,table in (('3','p3_jobs'),('4','p4_jobs'),('5','p5_jobs'),('8','agent_tasks')):
            queued=conn.execute("SELECT COUNT(*) FROM "+table+" WHERE status='Queued'").fetchone()[0]
            recent=conn.execute("SELECT 1 FROM runtime_workers WHERE phase=? AND state='running' AND last_seen>?",(phase,now-120)).fetchone()
            if queued and not recent:active.append(('worker_stale',phase,'Queued work has no recent matching worker heartbeat.'))
        last=conn.execute('SELECT MAX(created_at) FROM ops_backups WHERE verified=1').fetchone()[0]
        if not last or now-last>26*3600:active.append(('backup','daily','No recent verified encrypted backup; investigate backup job.'))
        config=conn.execute('SELECT daily_cents FROM p5_control WHERE id=1').fetchone()
        used=conn.execute('SELECT COALESCE(SUM(reserved_cents),0) FROM p5_ai_usage WHERE day=?',(__import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat(),)).fetchone()[0]
        if config[0] and used>=config[0]*.8:active.append(('spending','AI','At least 80% of the daily AI reservation ceiling is used.'))
        keys={(category,subject) for category,subject,_ in active}
        for row in conn.execute('SELECT * FROM ops_alerts WHERE resolved_at IS NULL').fetchall():
            if (row['category'],row['subject']) not in keys:conn.execute('UPDATE ops_alerts SET resolved_at=? WHERE id=?',(now,row['id']))
        for category,subject,message in active:
            row=conn.execute('SELECT id FROM ops_alerts WHERE category=? AND subject=? AND resolved_at IS NULL',(category,subject)).fetchone()
            if row:conn.execute('UPDATE ops_alerts SET last_seen=?,message=? WHERE id=?',(now,message,row['id']))
            else:conn.execute('INSERT INTO ops_alerts(category,subject,message,created_at,last_seen) VALUES(?,?,?,?,?)',(category,subject,message,now,now))
    return len(active)


def register(app,get_db):
    @app.get('/healthz')
    def healthz():return {'status':'alive'}

    @app.get('/readyz')
    def readyz():
        try:
            get_db().execute('SELECT id FROM ops_backups LIMIT 1').fetchone()
            ok=get_db().execute('PRAGMA quick_check').fetchone()[0]=='ok'
        except sqlite3.Error:ok=False
        return ({'status':'ready' if ok else 'unavailable'},200 if ok else 503)

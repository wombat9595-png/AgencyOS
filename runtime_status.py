"""Canonical SQLite locations and observable worker connections, never queue execution."""
from pathlib import Path
from contextlib import closing
import os
import time
import uuid
import shlex
from phase3_store import connect

ROOT=Path(__file__).resolve().parent
PHASES={'3':'p3_jobs','4':'p4_jobs','5':'p5_jobs'}


def database_path(value=None):
    path=Path(value or ROOT/'.development'/'agencyos-phase5.db').expanduser()
    if not path.is_absolute():
        path=ROOT/path
    return str(path.resolve())


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS runtime_database(id INTEGER PRIMARY KEY CHECK(id=1),identity TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runtime_workers(
      id TEXT PRIMARY KEY, phase TEXT NOT NULL, database_path TEXT NOT NULL,
      pid INTEGER NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL,last_seen REAL NOT NULL);
    ''')
    conn.execute('INSERT OR IGNORE INTO runtime_database(id,identity) VALUES(1,?)',(uuid.uuid4().hex,))


def status(conn,path,phase='5'):
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    queues={}
    for key,table in PHASES.items():
        queues[key]={row[0]:row[1] for row in conn.execute('SELECT status,COUNT(*) FROM '+table+' GROUP BY status')} if table in tables else {}
    identity=conn.execute('SELECT identity FROM runtime_database WHERE id=1').fetchone()[0] if 'runtime_database' in tables else 'Not migrated'
    canonical=database_path(path)
    workers=[]
    if 'runtime_workers' in tables:
        workers=[dict(zip(('id','phase','pid','state','age_seconds'),row)) for row in conn.execute(
            "SELECT id,phase,pid,state,?-last_seen FROM runtime_workers WHERE database_path=? AND state='running' AND last_seen BETWEEN ? AND ? ORDER BY phase,id",
            (time.time(),canonical,time.time()-60,time.time()+1)).fetchall()]
    return dict(database_path=canonical,database_identity=identity,selected_phase=phase,queues=queues,workers=workers,
                command='AGENCYOS_DB='+shlex.quote(canonical)+' python manage.py worker'+(' --phase'+phase if phase!='3' else '')+' --watch',
                selected_worker_connected=any(w['phase']==phase for w in workers),
                paused=bool(conn.execute('SELECT paused FROM p4_control WHERE id=1').fetchone()[0]) if 'p4_control' in tables else False)


def heartbeat(path,worker_id,phase,state='running'):
    with closing(connect(path)) as conn,conn:
        conn.execute('''INSERT INTO runtime_workers(id,phase,database_path,pid,state,started_at,last_seen)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,last_seen=excluded.last_seen''',
          (worker_id,phase,database_path(path),os.getpid(),state,time.time(),time.time()))
        conn.execute("DELETE FROM runtime_workers WHERE last_seen<?",(time.time()-7*86400,))

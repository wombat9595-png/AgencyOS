"""Durable, bounded, at-most-once work claims. Interrupted external calls never auto-retry."""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone

class WorkflowError(Exception):
    pass

def stamp():
    return datetime.now(timezone.utc).isoformat()

def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p3_jobs (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      kind TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
      payload_json TEXT NOT NULL, approved_hash TEXT NOT NULL DEFAULT '',
      result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      not_before REAL NOT NULL DEFAULT 0, lease_until REAL, run_token TEXT,
      attempts INTEGER NOT NULL DEFAULT 0, progress INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS p3_jobs_queue ON p3_jobs(status,not_before,id);
    CREATE TABLE IF NOT EXISTS p3_events (
      id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES p3_jobs(id),
      message TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p3_candidates (
      id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES p3_jobs(id),
      source_id TEXT NOT NULL, source_url TEXT NOT NULL, retrieved_at TEXT NOT NULL,
      data_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending',
      lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
      UNIQUE(job_id,source_id));
    CREATE TABLE IF NOT EXISTS p3_evidence (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
      job_id INTEGER REFERENCES p3_jobs(id), source_url TEXT NOT NULL,
      observed_at TEXT NOT NULL, origin TEXT NOT NULL, facts_json TEXT NOT NULL,
      content_hash TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS p3_drafts (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      job_id INTEGER NOT NULL UNIQUE REFERENCES p3_jobs(id),
      lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
      research_id INTEGER NOT NULL REFERENCES p3_jobs(id),
      body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Needs review',
      follow_up_date TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p3_draft_events (
      id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES p3_drafts(id),
      message TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p3_cache (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, expires_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS p3_usage (service TEXT PRIMARY KEY, day TEXT NOT NULL,
      calls INTEGER NOT NULL, last_call REAL NOT NULL, blocked_until REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS p3_migrations (name TEXT PRIMARY KEY);
    ''')
    if not conn.execute("SELECT 1 FROM p3_migrations WHERE name='discovery-outreach-v1'").fetchone():
        for slug, description in (('lead-discovery','OSM discovery with source attribution, policy gate and candidate approval.'),
                                  ('outreach','Saved draft history from approved research. No sending.')):
            conn.execute("UPDATE agents SET availability='available',enabled=1,description=? WHERE id=? AND availability='planned'", (description,slug))
        conn.execute("INSERT INTO p3_migrations VALUES('discovery-outreach-v1')")

def event(conn, job_id, message):
    conn.execute('INSERT INTO p3_events(job_id,message,created_at) VALUES(?,?,?)',(job_id,message,stamp()))

def create_job(conn, user_id, kind, mode, payload, needs_approval):
    serialised=json.dumps(payload,sort_keys=True)
    if len(serialised)>24000:
        raise WorkflowError('Task input exceeds 24,000 characters. Select fewer evidence items or a shorter brief before approving an AI request.')
    conn.execute('BEGIN IMMEDIATE')
    pending = conn.execute("SELECT COUNT(*) FROM p3_jobs WHERE user_id=? AND status IN ('Queued','Running','Awaiting approval')",(user_id,)).fetchone()[0]
    if pending >= 20:
        conn.rollback()
        raise WorkflowError('You already have 20 pending jobs. Finish or cancel some before creating more.')
    cursor = conn.execute('INSERT INTO p3_jobs(user_id,kind,mode,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                          (user_id,kind,mode,'Awaiting approval' if needs_approval else 'Queued',serialised,stamp(),stamp()))
    event(conn,cursor.lastrowid,'Task created with an immutable input snapshot. No external call made.')
    return cursor.lastrowid

def reserve_call(conn, service, interval=2, maximum=20):
    """Cross-worker reservations: failed requests also count; no automatic retries."""
    conn.execute('BEGIN IMMEDIATE')
    row=conn.execute('SELECT * FROM p3_usage WHERE service=?',(service,)).fetchone()
    current=time.time(); day=stamp()[:10]
    if row:
        if row['blocked_until'] > current or current-row['last_call'] < interval:
            conn.rollback();raise WorkflowError('Provider rate limit/backoff active. Wait before creating another request.')
        count=row['calls'] if row['day']==day else 0
        if count>=maximum:
            conn.rollback();raise WorkflowError('Daily provider request limit reached. Try again tomorrow (UTC).')
    else: count=0
    conn.execute('INSERT INTO p3_usage VALUES(?,?,?,?,0) ON CONFLICT(service) DO UPDATE SET day=excluded.day,calls=excluded.calls,last_call=excluded.last_call',
                 (service,day,count+1,current))
    conn.commit()

def block_service(conn, service, seconds):
    conn.execute('UPDATE p3_usage SET blocked_until=? WHERE service=?',(time.time()+seconds,service));conn.commit()

def claim(conn):
    conn.execute('BEGIN IMMEDIATE')
    from phase4_store import paused
    if paused(conn):
        conn.commit()
        return None
    # At-most-once is preferable to silently repeating a charged request after a crash.
    expired=conn.execute("SELECT id FROM p3_jobs WHERE status='Running' AND lease_until<?",(time.time(),)).fetchall()
    for row in expired:
        conn.execute("UPDATE p3_jobs SET status='Interrupted',error=?,updated_at=? WHERE id=?",('Worker interrupted. Check provider usage before explicitly creating a replacement task.',stamp(),row['id']))
        event(conn,row['id'],'Lease expired. Interrupted, not requeued; external requests may have completed.')
    row=conn.execute("SELECT * FROM p3_jobs WHERE status='Queued' AND not_before<=? ORDER BY id LIMIT 1",(time.time(),)).fetchone()
    if row:
        token=uuid.uuid4().hex
        conn.execute("UPDATE p3_jobs SET status='Running',run_token=?,lease_until=?,attempts=attempts+1,progress=20,updated_at=? WHERE id=? AND status='Queued'",(token,time.time()+300,stamp(),row['id']))
        event(conn,row['id'],'Worker claimed the job. Processing the approved snapshot.')
        conn.commit()
        return conn.execute('SELECT * FROM p3_jobs WHERE id=?',(row['id'],)).fetchone()
    conn.commit()
    return None

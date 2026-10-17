"""Phase 4 coordination. Local jobs are repeatable; external jobs never auto-retry."""
import hashlib
import json
import sqlite3
import time
import uuid
from phase3_store import WorkflowError, stamp, connect

KINDS = ('qualification', 'research', 'audit', 'discovery')


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p4_control (
      id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 0,
      daily_budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(daily_budget_cents>=0));
    INSERT OR IGNORE INTO p4_control(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS p4_jobs (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL, kind TEXT NOT NULL,
      payload_json TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '',
      error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      not_before REAL NOT NULL DEFAULT 0, lease_until REAL, token TEXT,
      attempts INTEGER NOT NULL DEFAULT 0, parent_id INTEGER REFERENCES p4_jobs(id),
      handoff INTEGER NOT NULL DEFAULT 0, approval_hash TEXT NOT NULL DEFAULT '',
      approval_expires REAL NOT NULL DEFAULT 0, approval_context TEXT NOT NULL DEFAULT '',
      UNIQUE(parent_id,kind));
    CREATE INDEX IF NOT EXISTS p4_queue ON p4_jobs(status,not_before);
    CREATE TABLE IF NOT EXISTS p4_activity (
      id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
      job_id INTEGER REFERENCES p4_jobs(id), message TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p4_schedules (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
      interval_seconds INTEGER NOT NULL CHECK(interval_seconds>=3600),
      next_run REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p4_budget (
      job_id INTEGER PRIMARY KEY REFERENCES p4_jobs(id), day TEXT NOT NULL,
      reserved_cents INTEGER NOT NULL CHECK(reserved_cents>=0),
      actual_cents INTEGER CHECK(actual_cents>=0));
    CREATE TABLE IF NOT EXISTS p4_search_schedules (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      state TEXT NOT NULL, city TEXT NOT NULL, industry TEXT NOT NULL,
      interval_seconds INTEGER NOT NULL, maximum INTEGER NOT NULL,
      next_run REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
    ''')
    # One-time catalogue upgrade; later owner enable/disable choices are retained.
    if not conn.execute("SELECT 1 FROM p3_migrations WHERE name='phase4-audit-v1'").fetchone():
        conn.execute("UPDATE agents SET availability='available',enabled=1,description='Authorised, bounded HTTPS/HTML audits with source evidence and review.' WHERE id='website-audit'")
        conn.execute("INSERT INTO p3_migrations VALUES('phase4-audit-v1')")


def log(conn, user_id, message, job_id=None):
    conn.execute('INSERT INTO p4_activity(user_id,job_id,message,created_at) VALUES(?,?,?,?)',
                 (user_id, job_id, message, stamp()))


def paused(conn):
    # Also works when called on a legacy database before the Phase 4 migration.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='p4_control'").fetchone():
        return False
    return bool(conn.execute('SELECT paused FROM p4_control WHERE id=1').fetchone()[0])


def enqueue(conn, user_id, lead_id, kind, payload, handoff=False, parent_id=None):
    if kind not in KINDS:
        raise WorkflowError('Unsupported Phase 4 task. No arbitrary tools or paid actions are available.')
    if conn.execute("SELECT COUNT(*) FROM p4_jobs WHERE user_id=? AND status IN ('Queued','Running','Awaiting approval')", (user_id,)).fetchone()[0] >= 100:
        raise WorkflowError('Phase 4 pending task limit (100) reached.')
    serialised = json.dumps(payload, sort_keys=True)
    if len(serialised) > 24000:
        raise WorkflowError('Phase 4 task snapshot exceeds 24,000 characters.')
    cursor = conn.execute('''INSERT INTO p4_jobs
      (user_id,lead_id,kind,payload_json,status,created_at,updated_at,handoff,parent_id)
      VALUES(?,?,?,?,?,?,?,?,?)''', (user_id, lead_id, kind, serialised,
      'Awaiting approval' if kind == 'audit' else 'Queued', stamp(), stamp(), int(handoff), parent_id))
    log(conn, user_id, 'Created immutable '+kind+' task.', cursor.lastrowid)
    return cursor.lastrowid


def fingerprint(job, context):
    return hashlib.sha256((job['kind']+'\n'+job['payload_json']+'\n'+context).encode()).hexdigest()


def reserve_budget(conn, job_id, maximum_cents):
    """Caller holds an IMMEDIATE transaction. Unknown/negative costs are rejected.

    Reservations survive interruption; they are not released merely because a call failed.
    No paid executor ships in milestones 1–3. Currency is AUD cents throughout.
    """
    if type(maximum_cents) is not int or maximum_cents < 0:
        raise WorkflowError('A non-negative integer AUD-cent ceiling is required.')
    existing = conn.execute('SELECT * FROM p4_budget WHERE job_id=?', (job_id,)).fetchone()
    if existing:
        if existing['reserved_cents'] != maximum_cents:
            raise WorkflowError('An existing reservation cannot be changed.')
        return
    cap = conn.execute('SELECT daily_budget_cents FROM p4_control WHERE id=1').fetchone()[0]
    day = stamp()[:10]
    used = conn.execute('SELECT COALESCE(SUM(COALESCE(actual_cents,reserved_cents)),0) FROM p4_budget WHERE day=?', (day,)).fetchone()[0]
    if used + maximum_cents > cap:
        raise WorkflowError('Daily AUD spending ceiling exceeded. No external action started.')
    conn.execute('INSERT INTO p4_budget(job_id,day,reserved_cents) VALUES(?,?,?)', (job_id, day, maximum_cents))


def claim(conn):
    conn.execute('BEGIN IMMEDIATE')
    if paused(conn):
        conn.commit()
        return None
    for row in conn.execute("SELECT * FROM p4_jobs WHERE status='Running' AND lease_until<?", (time.time(),)).fetchall():
        retry = row['kind'] in ('qualification', 'research', 'discovery') and row['attempts'] < 3
        conn.execute('UPDATE p4_jobs SET status=?,not_before=?,token=NULL,lease_until=NULL,error=?,updated_at=? WHERE id=?',
                     ('Queued' if retry else 'Interrupted', time.time()+60, 'Worker lease expired; '+('safe local retry scheduled.' if retry else 'external work is never automatically repeated.'), stamp(), row['id']))
        log(conn, row['user_id'], 'Expired lease: '+('local retry after 60s.' if retry else 'manual review required.'), row['id'])
    row = conn.execute("SELECT * FROM p4_jobs WHERE status='Queued' AND not_before<=? ORDER BY id LIMIT 1", (time.time(),)).fetchone()
    if row:
        token = uuid.uuid4().hex
        conn.execute("UPDATE p4_jobs SET status='Running',token=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?", (token, time.time()+300, stamp(), row['id']))
        reserve_budget(conn, row['id'], 0)
        log(conn, row['user_id'], 'Worker claimed task; reserved AUD 0.00 (no paid executor).', row['id'])
        conn.commit()
        return conn.execute('SELECT * FROM p4_jobs WHERE id=?', (row['id'],)).fetchone()
    conn.commit()
    return None


def schedule_tick(conn, snapshot):
    """Only local qualification→research schedules; never schedules network access."""
    conn.execute('BEGIN IMMEDIATE')
    if paused(conn):
        conn.commit()
        return 0
    count = 0
    for row in conn.execute('SELECT * FROM p4_schedules WHERE enabled=1 AND next_run<=? ORDER BY id LIMIT 20', (time.time(),)).fetchall():
        pending = conn.execute("SELECT 1 FROM p4_jobs WHERE user_id=? AND lead_id=? AND status IN ('Queued','Running','Awaiting approval')", (row['user_id'], row['lead_id'])).fetchone()
        if not pending:
            lead = conn.execute('SELECT * FROM leads WHERE id=?', (row['lead_id'],)).fetchone()
            try:
                enqueue(conn, row['user_id'], row['lead_id'], 'qualification', snapshot(conn, lead), True)
                count += 1
            except WorkflowError:
                log(conn, row['user_id'], 'Schedule deferred: queue limit reached.')
                continue
        # Skip missed slots rather than create a restart catch-up storm.
        conn.execute('UPDATE p4_schedules SET next_run=? WHERE id=?', (time.time()+row['interval_seconds'], row['id']))
    conn.commit()
    return count

"""Durable sales records. No email, financial or model side effects in this module."""
import hashlib
import json
import time
import uuid
from phase3_store import WorkflowError, stamp
from phase4_store import paused


def dumps(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p5_control (
      id INTEGER PRIMARY KEY CHECK(id=1), daily_cents INTEGER NOT NULL DEFAULT 0,
      daily_requests INTEGER NOT NULL DEFAULT 0, input_rate INTEGER NOT NULL DEFAULT 0,
      output_rate INTEGER NOT NULL DEFAULT 0, pricing_model TEXT NOT NULL DEFAULT '',
      pricing_expires REAL NOT NULL DEFAULT 0,
      sender TEXT NOT NULL DEFAULT '', provider TEXT NOT NULL DEFAULT 'mock',
      gst_mode TEXT NOT NULL DEFAULT 'unset');
    INSERT OR IGNORE INTO p5_control(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS p5_packages (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      name TEXT NOT NULL, version INTEGER NOT NULL, category TEXT NOT NULL,
      price_cents INTEGER NOT NULL CHECK(price_cents>=0), cycle TEXT NOT NULL,
      scope TEXT NOT NULL, exclusions TEXT NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(user_id,name,version));
    CREATE TABLE IF NOT EXISTS p5_flows (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL, snapshot_json TEXT NOT NULL,
      package_json TEXT NOT NULL, state TEXT NOT NULL, tone TEXT NOT NULL,
      synthetic INTEGER NOT NULL DEFAULT 0, requirements TEXT NOT NULL DEFAULT '',
      requirements_source TEXT NOT NULL DEFAULT '', branding TEXT NOT NULL DEFAULT '',
      follow_state TEXT NOT NULL DEFAULT 'No correspondence', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p5_jobs (
      id INTEGER PRIMARY KEY, flow_id INTEGER NOT NULL REFERENCES p5_flows(id),
      kind TEXT NOT NULL, mode TEXT NOT NULL, payload_json TEXT NOT NULL,
      status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
      approval_hash TEXT NOT NULL DEFAULT '', approval_expires REAL NOT NULL DEFAULT 0,
      approval_context TEXT NOT NULL DEFAULT '',
      not_before REAL NOT NULL DEFAULT 0, token TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
      dedupe_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS p5_one_running_flow ON p5_jobs(flow_id) WHERE status='Running';
    CREATE TABLE IF NOT EXISTS p5_activity (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      flow_id INTEGER REFERENCES p5_flows(id), job_id INTEGER REFERENCES p5_jobs(id),
      message TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p5_drafts (
      id INTEGER PRIMARY KEY, flow_id INTEGER NOT NULL REFERENCES p5_flows(id),
      job_id INTEGER NOT NULL UNIQUE REFERENCES p5_jobs(id), kind TEXT NOT NULL,
      version INTEGER NOT NULL, content_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Needs review', created_at TEXT NOT NULL,
      UNIQUE(flow_id,kind,version));
    CREATE TABLE IF NOT EXISTS p5_messages (
      id INTEGER PRIMARY KEY, flow_id INTEGER NOT NULL REFERENCES p5_flows(id),
      draft_id INTEGER UNIQUE REFERENCES p5_drafts(id), quote_id INTEGER REFERENCES p5_quotes(id),
      recipient TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Draft', approval_hash TEXT NOT NULL DEFAULT '',
      approval_expires REAL NOT NULL DEFAULT 0, provider_id TEXT UNIQUE,
      created_at TEXT NOT NULL, dispatched_at TEXT);
    CREATE TABLE IF NOT EXISTS p5_events (
      id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES p5_messages(id),
      provider TEXT NOT NULL, external_id TEXT NOT NULL, kind TEXT NOT NULL,
      original_json TEXT NOT NULL, payload_hash TEXT NOT NULL, received_at TEXT NOT NULL,
      UNIQUE(provider,external_id));
    CREATE TABLE IF NOT EXISTS p5_suppressions (
      user_id INTEGER NOT NULL REFERENCES users(id), email TEXT NOT NULL,
      reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,email));
    CREATE TABLE IF NOT EXISTS p5_followups (
      id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE REFERENCES p5_messages(id),
      due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'Scheduled');
    CREATE TABLE IF NOT EXISTS p5_quotes (
      id INTEGER PRIMARY KEY, flow_id INTEGER NOT NULL REFERENCES p5_flows(id),
      version INTEGER NOT NULL, content_json TEXT NOT NULL, content_hash TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Draft', legacy_quote_id INTEGER REFERENCES quotes(id),
      created_at TEXT NOT NULL, UNIQUE(flow_id,version));
    CREATE TABLE IF NOT EXISTS p5_acceptances (
      id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL UNIQUE REFERENCES p5_quotes(id),
      quote_hash TEXT NOT NULL, customer_name TEXT NOT NULL, evidence TEXT NOT NULL,
      evidence_source TEXT NOT NULL, recorded_at TEXT NOT NULL,
      provenance TEXT NOT NULL DEFAULT 'Owner-attested customer acceptance; not independently verified');
    CREATE TABLE IF NOT EXISTS p5_project_briefs (
      id INTEGER PRIMARY KEY, acceptance_id INTEGER NOT NULL UNIQUE REFERENCES p5_acceptances(id),
      project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id), brief_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p5_ai_usage (
      job_id INTEGER PRIMARY KEY REFERENCES p5_jobs(id), day TEXT NOT NULL,
      reserved_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Reserved');
    ''')
    for identifier,name,description in (
        ('sales-replies','Reply and Follow-Up Agent','Local/optional approved AI reply interpretation, reviewed drafts and internal follow-up reviews.'),
        ('sales-proposals','Proposal and Quote Agent','Reviewed proposals, exact AUD calculations and owner-attested acceptance/project briefs.'),
        ('website-builder','Website Builder Agent','Creates safe, versioned static websites from accepted project briefs.'),
        ('website-qa','Website QA Agent','Checks generated pages, navigation, forms, accessibility, SEO, claims and scope.')):
        conn.execute("INSERT OR IGNORE INTO agents(id,name,description,availability,enabled) VALUES(?,?,?,'available',1)",(identifier,name,description))


def log(conn,user_id,message,flow_id=None,job_id=None):
    conn.execute('INSERT INTO p5_activity(user_id,flow_id,job_id,message,created_at) VALUES(?,?,?,?,?)',
                 (user_id,flow_id,job_id,message,stamp()))


def enqueue(conn,flow_id,kind,payload,mode='local',key=None):
    if kind not in ('research','outreach','classify','reply','proposal','quote','dispatch','followup','website') or mode not in ('local','ai'):
        raise WorkflowError('Unsupported sales task or execution mode.')
    if mode=='ai' and kind not in ('outreach','reply','proposal','classify','website'):
        raise WorkflowError('This task has no AI executor.')
    if len(dumps(payload))>50000:
        raise WorkflowError('Sales task snapshot exceeds 50,000 characters.')
    if conn.execute("SELECT COUNT(*) FROM p5_jobs WHERE status IN ('Queued','Running','Awaiting approval')").fetchone()[0]>=100:
        raise WorkflowError('Sales queue ceiling (100 pending jobs) reached.')
    key=key or uuid.uuid4().hex
    cursor=conn.execute('''INSERT OR IGNORE INTO p5_jobs(flow_id,kind,mode,payload_json,status,dedupe_key,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?)''',(flow_id,kind,mode,dumps(payload),'Awaiting approval' if mode=='ai' else 'Queued',key,stamp(),stamp()))
    if cursor.rowcount:
        owner=conn.execute('SELECT user_id FROM p5_flows WHERE id=?',(flow_id,)).fetchone()[0]
        log(conn,owner,'Queued '+kind+' ('+mode+').',flow_id,cursor.lastrowid)
        return cursor.lastrowid
    return conn.execute('SELECT id FROM p5_jobs WHERE dedupe_key=?',(key,)).fetchone()[0]


def claim(conn):
    conn.execute('BEGIN IMMEDIATE')
    if paused(conn):
        conn.commit()
        return None
    for row in conn.execute("SELECT j.*,f.user_id FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE j.status='Running' AND j.lease_until<?",(time.time(),)).fetchall():
        safe=row['mode']=='local' and row['kind']!='dispatch' and row['attempts']<3
        conn.execute('UPDATE p5_jobs SET status=?,error=?,token=NULL,lease_until=NULL,not_before=?,updated_at=? WHERE id=?',
                     ('Queued' if safe else 'Interrupted','Expired lease: '+('safe local retry' if safe else 'review uncertain execution; no automatic retry'),time.time()+30,stamp(),row['id']))
        if row['kind']=='dispatch':
            message_id=json.loads(row['payload_json'])['message_id']
            conn.execute("UPDATE p5_messages SET status='Outcome unknown' WHERE id=? AND status='Dispatching'",(message_id,))
        log(conn,row['user_id'],'Expired worker lease; '+('local retry scheduled.' if safe else 'manual recovery required.'),row['flow_id'],row['id'])
    row=conn.execute('''SELECT j.*,f.user_id FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id
      WHERE j.status='Queued' AND j.not_before<=? AND f.state!='Cancelled'
      AND NOT EXISTS(SELECT 1 FROM p5_jobs r WHERE r.flow_id=j.flow_id AND r.status='Running')
      ORDER BY j.id LIMIT 1''',(time.time(),)).fetchone()
    if row:
        conn.execute("UPDATE p5_jobs SET status='Running',attempts=attempts+1,token=?,lease_until=?,updated_at=? WHERE id=?",(uuid.uuid4().hex,time.time()+300,stamp(),row['id']))
        log(conn,row['user_id'],'Worker claimed '+row['kind']+'.',row['flow_id'],row['id'])
        conn.commit()
        return conn.execute('SELECT j.*,f.user_id FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE j.id=?',(row['id'],)).fetchone()
    conn.commit()
    return None

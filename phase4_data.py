"""Offline licensed-data intake. No discovery provider or website calls occur here."""
import csv
import io
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from lead_finder import validate_lead, duplicate_reasons
from phase3_store import WorkflowError, stamp
from phase4_store import log

STATES = ('ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA')
FIELDS = ('source_id', 'source_url', 'observed_at', 'business_name', 'state', 'city',
          'industry', 'website', 'email', 'contact_name')


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p4_sources (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL,
      licence_url TEXT NOT NULL, permitted_use TEXT NOT NULL, attribution TEXT NOT NULL,
      reviewer TEXT NOT NULL, reviewed_at TEXT NOT NULL, expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p4_candidates (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      source_id INTEGER NOT NULL REFERENCES p4_sources(id), external_id TEXT NOT NULL,
      source_url TEXT NOT NULL, observed_at TEXT NOT NULL, imported_at TEXT NOT NULL,
      state TEXT NOT NULL, city TEXT NOT NULL, data_json TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Pending', lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS p4_source_identity ON p4_candidates(source_id,external_id);
    ''')


def public_source_url(value):
    try:
        parts = urlsplit(value)
        if len(value)>2048 or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in (None,443) or any(c.isspace() for c in value):
            raise ValueError()
    except ValueError:
        raise WorkflowError('Source and licence links must be HTTPS URLs without credentials or custom ports.') from None
    return value


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
            raise ValueError()
        return parsed.isoformat()
    except (ValueError, TypeError):
        raise WorkflowError('Research timestamps must be real, timezone-aware ISO dates, not future dates.') from None


def source_current(row):
    try:
        return datetime.fromisoformat(row['expires_at']) > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def parse_dataset(data):
    try:
        reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')), strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not set(('source_id','source_url','observed_at','business_name','state','city','industry')) <= set(reader.fieldnames) or not set(reader.fieldnames) <= set(FIELDS):
            raise WorkflowError('Use the documented licensed-data CSV columns, including source identity, URL, timestamp, state, city and industry.')
        rows = []
        seen = set()
        for number, values in enumerate(reader, 1):
            if number>1000:
                raise WorkflowError('Import at most 1,000 source records per batch.')
            if None in values or any(v is None for v in values.values()):
                raise WorkflowError('CSV row has an incorrect column count.')
            values = {k:v.strip() for k,v in values.items()}
            identity = values['source_id']
            if not identity or len(identity)>254 or any(ord(c)<32 for c in identity) or identity in seen:
                raise WorkflowError('Each batch needs distinct nonempty source IDs of at most 254 characters.')
            seen.add(identity)
            if values['state'] not in STATES or not values['city'] or len(values['city'])>100:
                raise WorkflowError('Choose an Australian state/territory code and a city of 1–100 characters.')
            clean, errors = validate_lead(dict(values, location=values['city']+', '+values['state']+', Australia'))
            if errors:
                raise WorkflowError('CSV row '+str(number)+': '+', '.join(errors))
            rows.append(dict(external_id=identity, source_url=public_source_url(values['source_url']),
                             observed_at=timestamp(values['observed_at']), state=values['state'], city=values['city'], data=clean))
        if not rows:
            raise WorkflowError('CSV contains no records.')
        return rows
    except (UnicodeDecodeError, csv.Error):
        raise WorkflowError('Use a well-formed UTF-8 CSV.') from None


def duplicate(conn, candidate):
    data = json.loads(candidate['data_json'])
    reasons = []
    for lead in conn.execute('SELECT * FROM leads').fetchall():
        hints = duplicate_reasons(data, lead)
        if hints:
            reasons.append('Lead #'+str(lead['id'])+': '+', '.join(hints))
    # Strong source identity across separately registered imports; names/domains
    # flag conservative matches, never silently merge franchises or branches.
    source = conn.execute('SELECT name,licence_url FROM p4_sources WHERE id=?', (candidate['source_id'],)).fetchone()
    for other in conn.execute('''SELECT c.*,s.name,s.licence_url FROM p4_candidates c
        JOIN p4_sources s ON s.id=c.source_id WHERE c.id!=? AND c.status='Imported' ''', (candidate['id'],)).fetchall():
        identity_match = other['external_id']==candidate['external_id'] and other['name']==source['name'] and other['licence_url']==source['licence_url']
        if identity_match or duplicate_reasons(data, json.loads(other['data_json'])):
            reasons.append('Previously imported source candidate #'+str(other['id']))
    return reasons


def snapshot(conn, lead):
    evidence = [dict(row) for row in conn.execute('''SELECT c.source_url,c.observed_at,c.state,c.city,
      s.name,s.attribution,s.licence_url,s.expires_at FROM p4_candidates c JOIN p4_sources s ON s.id=c.source_id
      WHERE c.lead_id=? AND c.status='Imported' ORDER BY c.id DESC LIMIT 10''', (lead['id'],)).fetchall()]
    audits = []
    for row in conn.execute("SELECT payload_json,result_json,updated_at FROM p4_jobs WHERE lead_id=? AND kind='audit' AND status='Approved' ORDER BY id DESC LIMIT 1", (lead['id'],)).fetchall():
        payload = json.loads(row['payload_json'])
        # An audit of a previous website must not qualify a changed lead URL.
        if payload['lead']['website'] == lead['website'] and (datetime.now(timezone.utc)-datetime.fromisoformat(row['updated_at'])).total_seconds()<30*86400:
            audits.append(json.loads(row['result_json']))
    return dict(lead={key:lead[key] for key in ('id','business_name','industry','location','website')},
                sources=evidence, audits=audits, captured_at=stamp())


def qualify(payload):
    lead = payload['lead']
    reasons = []
    score = 0
    for present, points, label in ((bool(lead['industry']),20,'Industry recorded'),
                                  (bool(payload['sources']),30,'Source provenance recorded'),
                                  (any(source_current(s) for s in payload['sources']),20,'Owner source review current')):
        if present:
            score += points
            reasons.append(dict(points=points, reason=label))
    findings = sum(len(a.get('findings', [])) for a in payload['audits'])
    if findings:
        score += 30
        reasons.append(dict(points=30, reason='Owner-approved technical findings within 30 days'))
    return dict(score=score, maximum=100, reasons=reasons, source_count=len(payload['sources']),
                website_status='URL recorded; not proof of ownership or quality' if lead['website'] else 'Unknown: no URL recorded; this does not prove no website exists',
                limitations='Rule-based prioritisation, not an AI prediction, consent record or proof of buying intent.',
                snapshot=payload)


def search_snapshot(conn, user_id, state, city, industry, maximum):
    """Bounded search over licensed imports, not a public endpoint scraper.

    IDs and facts are frozen into the job. Duplicates remain visible as flags;
    explicit CRM import still rechecks identity inside its transaction.
    """
    rows = conn.execute('''SELECT c.*,s.name,s.licence_url,s.attribution,s.expires_at
      FROM p4_candidates c JOIN p4_sources s ON s.id=c.source_id
      WHERE c.user_id=? AND c.status='Pending' AND c.state=?
      AND (?='' OR lower(c.city)=lower(?)) ORDER BY c.id DESC LIMIT 1000''',
      (user_id,state,city,city)).fetchall()
    matches=[]
    identities=set()
    for row in rows:
        details=json.loads(row['data_json'])
        if not source_current(row) or (industry and industry.casefold() not in details['industry'].casefold()):
            continue
        identity=(row['name'],row['licence_url'],row['external_id'])
        if identity in identities:
            continue
        identities.add(identity)
        matches.append(dict(candidate_id=row['id'],source_url=row['source_url'],observed_at=row['observed_at'],
                            licence_url=row['licence_url'],attribution=row['attribution'],expires_at=row['expires_at'],
                            data=details,duplicate_flags=duplicate(conn,row)))
        if len(matches)>=maximum:
            break
    return dict(state=state,city=city,industry=industry,maximum=maximum,candidates=matches,captured_at=stamp(),
                scope='Offline search of up to 1,000 staged records. Not exhaustive nationwide discovery; no external request or automatic CRM import.')


def search_tick(conn):
    from phase4_store import paused, enqueue
    import time
    conn.execute('BEGIN IMMEDIATE')
    if paused(conn):
        conn.commit()
        return
    for row in conn.execute('SELECT * FROM p4_search_schedules WHERE enabled=1 AND next_run<=? ORDER BY id LIMIT 20',(time.time(),)).fetchall():
        try:
            payload=search_snapshot(conn,row['user_id'],row['state'],row['city'],row['industry'],row['maximum'])
            enqueue(conn,row['user_id'],None,'discovery',payload)
        except WorkflowError:
            log(conn,row['user_id'],'Offline location search deferred: queue or snapshot ceiling reached.')
        conn.execute('UPDATE p4_search_schedules SET next_run=? WHERE id=?',(time.time()+row['interval_seconds'],row['id']))
    conn.commit()

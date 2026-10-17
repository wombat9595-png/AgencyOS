"""Local-only staging, artifact checks and recorded rollback for approved static sites."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from flask import abort, redirect, request, session, url_for
from phase3_store import WorkflowError, stamp
import sales_store as store
from static_safety import static_errors

SLUG = re.compile(r'^[a-z0-9-]{1,40}$')
MAX_PAGE_BYTES = 1_000_000
MAX_SITE_BYTES = 4_000_000


class DeploymentAdapter(Protocol):
    def deploy(self, artifact_path: str, destination: dict) -> dict: ...


class PublicDeploymentUnavailableAdapter:
    """Explicit fail-closed placeholder; no hosting provider is configured."""
    def deploy(self, artifact_path, destination):
        raise WorkflowError('Public deployment is unavailable. No provider adapter, account or publication approval is configured.')


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p10_releases (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
      site_id INTEGER NOT NULL REFERENCES p6_sites(id), version INTEGER NOT NULL,
      target TEXT NOT NULL DEFAULT 'local-staging', artifact_path TEXT NOT NULL,
      manifest_json TEXT NOT NULL, status TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(site_id,version));
    CREATE TABLE IF NOT EXISTS p10_checks (
      id INTEGER PRIMARY KEY, release_id INTEGER NOT NULL REFERENCES p10_releases(id),
      result TEXT NOT NULL, details_json TEXT NOT NULL, checked_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p10_alerts (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
      release_id INTEGER REFERENCES p10_releases(id), severity TEXT NOT NULL,
      message TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
    CREATE TABLE IF NOT EXISTS p10_events (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
      site_id INTEGER NOT NULL REFERENCES p6_sites(id), release_id INTEGER REFERENCES p10_releases(id),
      kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')


class LocalStagingAdapter:
    """Writes inert static files to a private local folder; never contacts a host."""
    def __init__(self, root):
        self.root = Path(root).resolve()

    def stage(self, site_id, version, pages):
        if not isinstance(pages, dict) or not pages or len(pages) > 10:
            raise WorkflowError('Staging requires 1–10 generated static pages.')
        normalized = {}
        total = 0
        for slug, html in pages.items():
            if not isinstance(slug, str) or not SLUG.fullmatch(slug) or not isinstance(html, str):
                raise WorkflowError('Generated page names or content are invalid.')
            if static_errors(html):raise WorkflowError('Active markup or unapproved resource detected; staging stopped.')
            for page in pages:
                html=html.replace('?page='+page+'"',page+'.html"').replace("?page="+page+"'",page+".html'")
            raw = html.encode('utf-8')
            if not raw or len(raw) > MAX_PAGE_BYTES or re.search(rb'<\s*script\b', raw, re.I):
                raise WorkflowError('Page size limit exceeded or active script found; staging stopped.')
            total += len(raw)
            normalized[slug] = raw
        if total > MAX_SITE_BYTES or 'index' not in normalized:
            raise WorkflowError('Site exceeds the staging size ceiling or has no index page.')
        target = self.root / f'site-{int(site_id)}' / f'v{int(version)}'
        if target.exists():
            raise WorkflowError('This version already has a staging directory; existing artifacts are preserved.')
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent=target.parent.resolve()
        if self.root not in resolved_parent.parents:
            raise WorkflowError('Staging target escaped the local staging root.')
        target=resolved_parent/target.name
        tmp = Path(tempfile.mkdtemp(prefix='.stage-', dir=target.parent))
        try:
            files = {}
            for slug, raw in sorted(normalized.items()):
                filename = 'index.html' if slug == 'index' else slug + '.html'
                (tmp / filename).write_bytes(raw)
                files[filename] = hashlib.sha256(raw).hexdigest()
            manifest = dict(schema_version=1, site_id=int(site_id), version=int(version),
                            created_at=stamp(), files=files,
                            note='Local private staging only. No public origin, domain or TLS endpoint.')
            manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
            (tmp / 'manifest.json').write_bytes(manifest_raw)
            os.replace(tmp, target)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return target, manifest


def _safe_artifact(root, relative):
    base = Path(root).resolve()
    candidate = (base / relative).resolve()
    if candidate == base or base not in candidate.parents:
        raise WorkflowError('Stored artifact path escaped the local staging root.')
    return candidate


def health_check(conn, release, root):
    details = dict(files=[], errors=[])
    try:
        artifact = _safe_artifact(root, release['artifact_path'])
        manifest = json.loads(release['manifest_json'])
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
            raise ValueError('invalid manifest')
        disk_manifest=artifact/'manifest.json'
        if disk_manifest.is_symlink() or disk_manifest.stat().st_size>100000 or json.loads(disk_manifest.read_text())!=manifest:
            raise ValueError('changed manifest')
    except (WorkflowError, ValueError, TypeError, OSError):
        artifact=None
        manifest={'files':{}}
        details['errors'].append('Stored artifact path or manifest is invalid')
    for filename, expected in manifest.get('files', {}).items():
        if not isinstance(filename,str) or not isinstance(expected,str) or (filename!='index.html' and not re.fullmatch(r'[a-z0-9-]{1,40}\.html', filename)):
            details['errors'].append('Invalid manifest filename')
            continue
        path = artifact / filename
        try:
            if path.is_symlink() or path.stat().st_size>MAX_PAGE_BYTES:raise OSError('Unsafe artifact')
            raw = path.read_bytes()
        except OSError:
            details['errors'].append('Missing file: ' + filename)
            continue
        actual = hashlib.sha256(raw).hexdigest()
        ok = actual == expected and len(raw) <= MAX_PAGE_BYTES and not static_errors(raw.decode('utf-8',errors='replace'))
        details['files'].append(dict(filename=filename, ok=ok, sha256=actual))
        if not ok:
            details['errors'].append('Integrity or static-content check failed: ' + filename)
    if not manifest.get('files'):
        details['errors'].append('Manifest contains no files')
    result = 'passed' if not details['errors'] else 'failed'
    conn.execute('INSERT INTO p10_checks(release_id,result,details_json,checked_at) VALUES(?,?,?,?)',
                 (release['id'], result, store.dumps(details), stamp()))
    if result == 'failed':
        conn.execute('INSERT INTO p10_alerts(owner_id,release_id,severity,message,created_at) VALUES(?,?,?,?,?)',
                     (release['owner_id'], release['id'], 'attention', '; '.join(details['errors'])[:1000], stamp()))
    return dict(result=result, details=details)


def maintenance_once(database, staging_root):
    """Check current local releases at most once per UTC day; only record checks/alerts."""
    from phase3_store import connect
    conn=connect(database)
    try:
        count=0
        releases=conn.execute("SELECT * FROM p10_releases WHERE status='Current' ORDER BY id").fetchall()
        today=stamp()[:10]
        for release in releases:
            last=conn.execute('SELECT checked_at FROM p10_checks WHERE release_id=? ORDER BY id DESC LIMIT 1',(release['id'],)).fetchone()
            if last and last['checked_at'][:10]==today:
                continue
            conn.execute('BEGIN IMMEDIATE')
            result=health_check(conn,release,staging_root)
            conn.commit()
            count+=1
        return count
    finally:
        conn.close()


def register(app, get_db, login_required, app_dir):
    root = lambda: Path(app.config.get('AGENCYOS_STAGING_ROOT', os.environ.get('AGENCYOS_STAGING_ROOT',Path(app_dir) / 'output' / 'staging')))

    def owned_site(site_id):
        row=get_db().execute('''SELECT s.*,f.id flow_id FROM p6_sites s
          JOIN p5_project_briefs b ON b.id=s.brief_id JOIN p5_acceptances a ON a.id=b.acceptance_id
          JOIN p5_quotes q ON q.id=a.quote_id JOIN p5_flows f ON f.id=q.flow_id
          WHERE s.id=? AND s.owner_id=? AND f.user_id=?''',(site_id,session['user_id'],session['user_id'])).fetchone()
        if not row: abort(404)
        return row

    def owned_release(release_id):
        row=get_db().execute('SELECT * FROM p10_releases WHERE id=? AND owner_id=?',(release_id,session['user_id'])).fetchone()
        if not row: abort(404)
        return row

    @app.route('/websites/<int:site_id>/stage/<int:version>', methods=['POST'])
    @login_required
    def stage_approved_version(site_id,version):
        conn=get_db();site=owned_site(site_id)
        if request.form.get('confirm')!='yes':
            raise WorkflowError('Confirm local private staging of this approved static version.')
        item=conn.execute('SELECT * FROM p6_site_versions WHERE site_id=? AND version=?',(site_id,version)).fetchone()
        if not item or item['status']!='Approved' or site['active_version']!=version:
            raise WorkflowError('Only the currently approved version can be staged.')
        if conn.execute('SELECT 1 FROM p10_releases WHERE site_id=? AND version=?',(site_id,version)).fetchone():
            raise WorkflowError('This approved version already has a staging record.')
        qa=json.loads(item['qa_json'])
        if not qa.get('passed'):
            raise WorkflowError('A version with failed QA cannot be staged.')
        pages=json.loads(item['pages_json'] or '{}')
        import website_builder
        brief=json.loads(conn.execute('SELECT brief_json FROM p5_project_briefs WHERE id=?',(site['brief_id'],)).fetchone()[0])
        if not website_builder.quality_check(pages,brief,json.loads(item['content_json']))['passed']:
            raise WorkflowError('Source QA changed; staging requires a freshly valid approved artifact.')
        artifact,manifest=LocalStagingAdapter(root()).stage(site_id,version,pages)
        relative=str(artifact.relative_to(Path(root()).resolve()))
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE p10_releases SET status='Staged' WHERE site_id=? AND status='Current'",(site_id,))
        release_id=conn.execute('''INSERT INTO p10_releases(owner_id,site_id,version,artifact_path,manifest_json,status,created_at)
          VALUES(?,?,?,?,?,'Current',?)''',(session['user_id'],site_id,version,relative,store.dumps(manifest),stamp())).lastrowid
        conn.execute('INSERT INTO p10_events(owner_id,site_id,release_id,kind,message,created_at) VALUES(?,?,?,?,?,?)',
                     (session['user_id'],site_id,release_id,'staged','Approved static version staged privately on this computer; no publication occurred.',stamp()))
        store.log(conn,session['user_id'],'Staged approved static version locally; no public deployment or domain change.',site['flow_id'])
        conn.commit()
        return redirect(url_for('website_project',project_id=site['project_id']))

    @app.route('/websites/releases/<int:release_id>/check', methods=['POST'])
    @login_required
    def check_release(release_id):
        conn=get_db();release=owned_release(release_id)
        conn.execute('BEGIN IMMEDIATE')
        result=health_check(conn,release,root())
        conn.commit()
        return redirect(url_for('website_project',project_id=conn.execute('SELECT project_id FROM p6_sites WHERE id=?',(release['site_id'],)).fetchone()[0]))

    @app.route('/websites/<int:site_id>/rollback/<int:release_id>', methods=['POST'])
    @login_required
    def rollback_release(site_id,release_id):
        conn=get_db();site=owned_site(site_id);release=owned_release(release_id)
        if release['site_id']!=site_id or request.form.get('confirm')!='yes':
            raise WorkflowError('Confirm rollback to a previously staged release for this same site.')
        conn.execute('BEGIN IMMEDIATE')
        if health_check(conn,release,root())['result']!='passed':
            conn.commit();raise WorkflowError('Rollback blocked: current target files failed integrity checks.')
        conn.execute("UPDATE p10_releases SET status='Staged' WHERE site_id=? AND status='Current'",(site_id,))
        conn.execute("UPDATE p10_releases SET status='Current' WHERE id=?",(release_id,))
        conn.execute('INSERT INTO p10_events(owner_id,site_id,release_id,kind,message,created_at) VALUES(?,?,?,?,?,?)',
                     (session['user_id'],site_id,release_id,'rollback','Current local staging pointer rolled back to a previously checked release. No public origin was changed.',stamp()))
        store.log(conn,session['user_id'],'Rolled local staging pointer back to release #'+str(release_id)+'; no publication occurred.',site['flow_id'])
        conn.commit()
        return redirect(url_for('website_project',project_id=site['project_id']))


"""Single-owner installation security, persistent throttles and metadata-only audits."""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from datetime import timedelta
from flask import abort, g, request, session


def secret(name, default=''):
    path=os.environ.get(name+'_FILE','')
    return Path(path).read_text().strip() if path else os.environ.get(name,default)


def configure(app):
    production=os.environ.get('AGENCYOS_ENV')=='production'
    key=secret('AGENCYOS_SECRET_KEY')
    if production:
        if len(key)<32:raise RuntimeError('Production requires a private stable session secret of at least 32 characters.')
        if not os.path.isabs(os.environ.get('AGENCYOS_DB','')):raise RuntimeError('Production requires an absolute AGENCYOS_DB.')
        hosts=os.environ.get('AGENCYOS_TRUSTED_HOSTS','').split(',')
        if not all(hosts):raise RuntimeError('Production requires explicit AGENCYOS_TRUSTED_HOSTS.')
        app.config['TRUSTED_HOSTS']=hosts
        app.config['SESSION_COOKIE_SECURE']=True
        app.config['SESSION_COOKIE_NAME']='__Host-agencyos'
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app=ProxyFix(app.wsgi_app,x_proto=1)
    if key:app.secret_key=key
    app.config.update(PRODUCTION_MODE=production,PERMANENT_SESSION_LIFETIME=timedelta(hours=8))


def migrate(conn):
    conn.executescript('''CREATE TABLE IF NOT EXISTS security_rate (
      key TEXT PRIMARY KEY, starts REAL NOT NULL, attempts INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS security_audit (
      id INTEGER PRIMARY KEY, actor INTEGER, event TEXT NOT NULL, object_json TEXT NOT NULL, created_at REAL NOT NULL);
    ''')


def audit(conn,event,actor=None,details=None):
    conn.execute('INSERT INTO security_audit(actor,event,object_json,created_at) VALUES(?,?,?,?)',
                 (actor,event,json.dumps(details or {},sort_keys=True),time.time()))


def allow_login(conn,key,username,remote,now=None):
    now=now or time.time()
    values=[('ip:'+remote,30),('pair:'+remote+':'+username.casefold(),5)]
    conn.execute('BEGIN IMMEDIATE')
    allowed=True
    for value,limit in values:
        token=hmac.new(str(key).encode(),value.encode(),hashlib.sha256).hexdigest()
        row=conn.execute('SELECT * FROM security_rate WHERE key=?',(token,)).fetchone()
        attempts=(row['attempts'] if row and row['starts']>now-900 else 0)+1
        starts=row['starts'] if row and row['starts']>now-900 else now
        conn.execute('INSERT INTO security_rate VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET starts=excluded.starts,attempts=excluded.attempts',(token,starts,attempts))
        allowed=allowed and attempts<=limit
    conn.execute('DELETE FROM security_rate WHERE starts<?',(now-86400,))
    conn.commit()
    return allowed


def install(app,get_db):
    @app.before_request
    def installation_boundary():
        g.request_started=time.monotonic()
        if app.config['PRODUCTION_MODE'] and request.endpoint=='setup':abort(403)
        if session.get('user_id'):
            owner=get_db().execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()
            if not owner or owner[0]!=session['user_id']:
                if request.endpoint in ('login','logout'):session.clear()
                else:abort(404)
            issued=session.get('authenticated_at')
            if (issued is not None and time.time()-issued>28800) or (app.config['PRODUCTION_MODE'] and issued is None):
                session.clear();return __import__('flask').redirect('/login')

    @app.after_request
    def secure_response(response):
        response.headers.setdefault('X-Content-Type-Options','nosniff')
        response.headers.setdefault('Referrer-Policy','no-referrer')
        response.headers.setdefault('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if request.endpoint!='static':response.headers.setdefault('Cache-Control','no-store')
        if app.config['PRODUCTION_MODE']:
            response.headers.setdefault('Strict-Transport-Security','max-age=31536000')
            app.logger.info(json.dumps(dict(endpoint=request.endpoint,status=response.status_code,duration_ms=round((time.monotonic()-g.get('request_started',time.monotonic()))*1000))))
        if request.method=='POST' and request.endpoint in ('invoice_settings','sales_settings','stage_approved_version','rollback_release','sales_contact_basis') and response.status_code<400:
            conn=get_db();audit(conn,request.endpoint,session.get('user_id'),request.view_args);conn.commit()
        return response

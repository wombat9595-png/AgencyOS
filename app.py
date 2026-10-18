import os
import sqlite3
import json
import secrets
import hmac
import time
from functools import wraps
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import Flask, g, redirect, render_template, request, session, url_for, flash, abort, Response
from werkzeug.security import check_password_hash, generate_password_hash

from lead_finder import STATUSES, validate_lead, parse_csv, duplicate_reasons
from ai_drafts import generate_draft, DraftError
from agent_center import migrate_agents, register_agent_routes
from phase3_store import migrate as migrate_phase3
from phase3 import register as register_phase3
from phase4 import register as register_phase4
from phase4_store import migrate as migrate_phase4
from phase4_data import migrate as migrate_phase4_data
from sales_store import migrate as migrate_sales
from sales import register as register_sales
import website_builder
import runtime_status
import phase7_billing
import p8_ops
import p10_release
import production_security
import production_ops
import production_portal
import email_preparation
import gmail_agent
import first_sale
import client_plans
import lead_engine
import office
import smart_writer
import night_shift
import story_mockups

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = runtime_status.database_path(os.environ.get("AGENCYOS_DB"))
app = Flask(__name__)
app.secret_key = os.environ.get("AGENCYOS_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
production_security.configure(app)

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS leads (
      id INTEGER PRIMARY KEY AUTOINCREMENT, business_name TEXT NOT NULL,
      contact_name TEXT DEFAULT '', email TEXT DEFAULT '', website TEXT DEFAULT '',
      industry TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'New',
      notes TEXT DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS quotes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER,
      client_name TEXT NOT NULL, title TEXT NOT NULL, amount_cents INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'Draft', notes TEXT DEFAULT '', created_at TEXT NOT NULL,
      FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS invoices (
      id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT NOT NULL,
      reference TEXT NOT NULL, amount_cents INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'Unpaid', due_date TEXT DEFAULT '', notes TEXT DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT NOT NULL,
      project_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Planning',
      due_date TEXT DEFAULT '', website_url TEXT DEFAULT '', notes TEXT DEFAULT '',
      created_at TEXT NOT NULL
    );
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
    for name in ('location', 'source'):
        if name not in columns:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    conn.execute("""CREATE TABLE IF NOT EXISTS lead_imports (
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, rows_json TEXT NOT NULL,
        created_at REAL NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS leads_status_idx ON leads(status)")
    migrate_agents(conn)
    migrate_phase3(conn)
    migrate_phase4(conn)
    migrate_phase4_data(conn)
    migrate_sales(conn)
    website_builder.migrate(conn)
    phase7_billing.migrate(conn)
    p8_ops.migrate(conn)
    p10_release.migrate(conn)
    runtime_status.migrate(conn)
    production_security.migrate(conn)
    production_ops.migrate(conn)
    production_portal.migrate(conn)
    email_preparation.migrate(conn)
    gmail_agent.migrate(conn)
    first_sale.migrate(conn)
    client_plans.migrate(conn)
    lead_engine.migrate(conn)
    smart_writer.migrate(conn)
    night_shift.migrate(conn)
    conn.commit()
    conn.close()

def money(cents):
    return f"${cents / 100:,.2f}"

@app.template_filter("money")
def money_filter(cents):
    return money(cents or 0)

@app.template_filter("fromjson")
def fromjson_filter(value):
    return json.loads(value or '{}')

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/setup", methods=["GET", "POST"])
def setup():
    conn = db()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 12:
            flash("Use a username of at least 3 characters and a password of at least 12 characters.", "error")
        else:
            try:
                conn.execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                             (username, generate_password_hash(password, method="pbkdf2:sha256"), datetime.now(timezone.utc).isoformat()))
                conn.commit()
                flash("Owner account created. Sign in to continue.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already in use.", "error")
    return render_template("setup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username)>254 or len(password)>1024 or not production_security.allow_login(db(),app.secret_key,username,request.remote_addr or ''):
            return render_template('error.html',message='Too many sign-in attempts. Try again in 15 minutes.'),429,{'Retry-After':'900'}
        user = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        owner=db().execute('SELECT MIN(id) FROM users').fetchone()[0]
        if user and user['id']==owner and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session['authenticated_at']=time.time()
            session.permanent=True
            production_security.audit(db(),'login_success',user['id']);db().commit()
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    conn = db()
    counts = {
      "leads": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
      "quotes": conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0],
      "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
      "unpaid": conn.execute("SELECT COUNT(*) FROM invoices WHERE status != 'Paid'").fetchone()[0],
      "phase7_open": conn.execute("SELECT COUNT(*) FROM p7_invoices WHERE status IN ('Draft','Approved (test)','Partially paid')").fetchone()[0],
      "provider_verified_cents": phase7_billing.verified_net_cents(conn, synthetic=False),
      "owner_reconciled_cents": conn.execute("SELECT COALESCE(SUM(p.amount_cents),0) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE p.source='owner_reconciled' AND p.status='Verified' AND i.synthetic=0").fetchone()[0],
      "test_paid_cents": phase7_billing.verified_net_cents(conn, synthetic=True),
      "test_owner_cents": conn.execute("SELECT COALESCE(SUM(p.amount_cents),0) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE p.source='owner_reconciled' AND p.status='Verified' AND i.synthetic=1").fetchone()[0],
    }
    recent_leads = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 5").fetchall()
    projects = conn.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 5").fetchall()
    return render_template("dashboard.html", counts=counts, recent_leads=recent_leads, projects=projects)

@app.route("/leads", methods=["GET", "POST"])
@login_required
def leads():
    conn = db()
    if request.method == "POST":
        row, errors = validate_lead(request.form)
        row['source'] = row['source'] or 'Manual entry'
        if errors:
            flash('; '.join(errors), 'error')
        else:
            insert_lead(conn, row)
            conn.commit()
            flash("Lead saved.", "success")
            return redirect(url_for("leads"))
    query = request.args.get('q', '').strip()[:254]
    conditions, params = [], []
    if query:
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append("(" + " OR ".join(f"{field} LIKE ? ESCAPE '\\'" for field in ('business_name', 'contact_name', 'email', 'website', 'industry', 'location', 'source')) + ")")
        params.extend([pattern] * 7)
    filters = {field: request.args.get(field, '').strip()[:254] for field in ('status', 'industry', 'location', 'source')}
    for field, value in filters.items():
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    sql = "SELECT * FROM leads" + (" WHERE " + " AND ".join(conditions) if conditions else '') + " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    options = {field: [r[0] for r in conn.execute(f"SELECT DISTINCT {field} FROM leads WHERE {field} != '' ORDER BY {field}")] for field in ('industry', 'location', 'source')}
    return render_template("leads.html", leads=rows, statuses=STATUSES, query=query, filters=filters, options=options)

@app.route("/leads/<int:lead_id>/delete", methods=["POST"])
@login_required
def delete_lead(lead_id):
    db().execute("DELETE FROM leads WHERE id=?", (lead_id,))
    db().commit()
    flash("Lead deleted.", "success")
    return redirect(url_for("leads"))

@app.route("/outreach", methods=["GET", "POST"])
@login_required
def outreach():
    conn = db()
    selected = None
    lead_id = request.values.get("lead_id", type=int)
    if lead_id:
        selected = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    draft = ""
    if request.method == "POST":
        if not selected:
            flash("Choose a lead first.", "error")
        else:
            tone = request.form.get("tone", "friendly")
            offer = request.form.get("offer", "a modern, mobile-friendly website")
            subject = f"Quick idea for {selected['business_name']}'s website"
            contact = selected["contact_name"] or "there"
            draft = f"""Subject: {subject}

Hi {contact},

I came across {selected['business_name']} and wanted to reach out. I help businesses improve their online presence with {offer}.

If improving your website is on your radar, I’d be happy to share a few tailored ideas. No pressure — just a quick conversation to see whether it could be useful.

Would you be open to a short chat?

Best,
[Your name]"""
            if tone not in ('friendly', 'professional', 'direct') or len(offer) > 1000:
                flash('Choose a supported tone and an offer of at most 1,000 characters.', 'error')
                draft = ''
            elif request.form.get('draft_mode', 'template') == 'ai' and request.form.get('approve_ai') != 'yes':
                flash('Approve the AI charge and sharing of lead details before generating an AI draft.', 'error')
                draft = ''
            elif request.form.get('draft_mode', 'template') == 'ai':
                try:
                    draft = generate_draft(selected, offer, tone)
                except DraftError as exc:
                    flash(str(exc), 'error')
                    draft = ''
            elif request.form.get('draft_mode', 'template') != 'template':
                flash('Choose Template or AI draft.', 'error')
                draft = ''
    leads_rows = conn.execute("SELECT id,business_name,contact_name,email FROM leads ORDER BY business_name").fetchall()
    session.pop("last_outreach_draft", None)
    return render_template("outreach.html", leads=leads_rows, selected=selected, draft=draft)

@app.route("/quotes", methods=["GET", "POST"])
@login_required
def quotes():
    conn = db()
    lead_rows = conn.execute("SELECT id,business_name FROM leads ORDER BY business_name").fetchall()
    if request.method == "POST":
        client = request.form.get("client_name","").strip()
        title = request.form.get("title","").strip()
        try:
            amount = Decimal(request.form.get("amount","0")).quantize(Decimal("0.01"))
            cents = int(amount * 100) if amount.is_finite() and amount <= Decimal("1000000000") else -1
        except (InvalidOperation, ValueError):
            cents = -1
        if not client or not title or cents < 0:
            flash("Enter a client, quote title and valid non-negative amount.", "error")
        else:
            conn.execute("""INSERT INTO quotes(lead_id,client_name,title,amount_cents,status,notes,created_at)
                VALUES(?,?,?,?,?,?,?)""", (request.form.get("lead_id") or None, client, title, cents,
                request.form.get("status","Draft"), request.form.get("notes","").strip(), datetime.now(timezone.utc).isoformat()))
            conn.commit()
            flash("Quote saved.", "success")
            return redirect(url_for("quotes"))
    rows = conn.execute("SELECT * FROM quotes ORDER BY id DESC").fetchall()
    return render_template("quotes.html", quotes=rows, leads=lead_rows)

@app.route("/quotes/<int:quote_id>/status", methods=["POST"])
@login_required
def quote_status(quote_id):
    status = request.form.get("status", "Draft")
    if status in ("Draft", "Sent", "Accepted", "Declined"):
        db().execute("UPDATE quotes SET status=? WHERE id=?", (status, quote_id))
        db().commit()
    return redirect(url_for("quotes"))

@app.route("/invoices", methods=["POST"])
@login_required
def legacy_invoice_create():
    conn = db()
    if request.method == "POST":
        client = request.form.get("client_name","").strip()
        reference = request.form.get("reference","").strip()
        try:
            amount = Decimal(request.form.get("amount","0")).quantize(Decimal("0.01"))
            cents = int(amount * 100) if amount.is_finite() and amount <= Decimal("1000000000") else -1
        except (InvalidOperation, ValueError):
            cents = -1
        if not client or not reference or cents < 0:
            flash("Enter a client, reference and valid non-negative amount.", "error")
        else:
            conn.execute("""INSERT INTO invoices(client_name,reference,amount_cents,status,due_date,notes,created_at)
                VALUES(?,?,?,?,?,?,?)""", (client, reference, cents, request.form.get("status","Unpaid"),
                request.form.get("due_date",""), request.form.get("notes","").strip(), datetime.now(timezone.utc).isoformat()))
            conn.commit()
            flash("Invoice record saved.", "success")
            return redirect(url_for("invoices"))
    return redirect(url_for("invoices"))

@app.route("/invoices/<int:invoice_id>/status", methods=["POST"])
@login_required
def invoice_status(invoice_id):
    status = request.form.get("status", "Unpaid")
    if status in ("Unpaid", "Paid", "Overdue", "Cancelled"):
        db().execute("UPDATE invoices SET status=? WHERE id=?", (status, invoice_id))
        db().commit()
    return redirect(url_for("invoices"))

@app.route("/invoices/legacy")
@login_required
def legacy_invoices():
    rows = db().execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    return render_template("invoices_legacy.html", invoices=rows)

@app.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    conn = db()
    if request.method == "POST":
        client = request.form.get("client_name","").strip()
        name = request.form.get("project_name","").strip()
        if not client or not name:
            flash("Client and project name are required.", "error")
        else:
            conn.execute("""INSERT INTO projects(client_name,project_name,status,due_date,website_url,notes,created_at)
                VALUES(?,?,?,?,?,?,?)""", (client, name, request.form.get("status","Planning"),
                request.form.get("due_date",""), request.form.get("website_url","").strip(),
                request.form.get("notes","").strip(), datetime.now(timezone.utc).isoformat()))
            conn.commit()
            flash("Project saved.", "success")
            return redirect(url_for("projects"))
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    website_project_ids={r['project_id'] for r in conn.execute('''SELECT b.project_id FROM p5_project_briefs b
        JOIN p5_acceptances a ON a.id=b.acceptance_id JOIN p5_quotes q ON q.id=a.quote_id
        JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=?''',(session['user_id'],)).fetchall()}
    return render_template("projects.html", projects=rows, website_project_ids=website_project_ids)

@app.route("/projects/<int:project_id>/status", methods=["POST"])
@login_required
def project_status(project_id):
    status = request.form.get("status", "Planning")
    if status in ("Planning", "In progress", "Review", "Delivered", "On hold"):
        db().execute("UPDATE projects SET status=? WHERE id=?", (status, project_id))
        db().commit()
    return redirect(url_for("projects"))

@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")

def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']

@app.context_processor
def template_helpers():
    return {'csrf_token': csrf_token}

@app.before_request
def protect_forms():
    if request.method == 'POST' and request.endpoint not in ('sales_provider_event', 'payment_webhook','unsubscribe'):
        expected = session.get('csrf_token', '')
        supplied = request.form.get('csrf_token', '')
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(400, description='Form expired or invalid. Reload the page and try again.')

@app.errorhandler(413)
def oversized_upload(_error):
    return render_template('error.html', message='Upload is too large. Use a CSV smaller than 2 MB.'), 413

@app.errorhandler(409)
def conflicting_action(error):
    return render_template('error.html', message=error.description), 409

@app.errorhandler(400)
def bad_request(error):
    from werkzeug.exceptions import SecurityError
    if isinstance(error,SecurityError):return Response('Invalid request host.',status=400,mimetype='text/plain')
    return render_template('error.html', message=error.description), 400

def insert_lead(conn, row):
    fields = ('business_name', 'contact_name', 'email', 'website', 'industry', 'location', 'source', 'status', 'notes')
    conn.execute('INSERT INTO leads(' + ','.join(fields) + ',created_at) VALUES(' + ','.join('?' for _ in range(10)) + ')',
                 tuple(row[field] for field in fields) + (datetime.now(timezone.utc).isoformat(),))

@app.route('/leads/<int:lead_id>/status', methods=['POST'])
@login_required
def lead_status(lead_id):
    status = request.form.get('status', '')
    if status not in STATUSES:
        abort(400, description='Invalid lead status.')
    cursor = db().execute('UPDATE leads SET status=? WHERE id=?', (status, lead_id))
    if not cursor.rowcount:
        abort(404)
    db().commit()
    flash('Lead status updated.', 'success')
    return redirect(url_for('leads'))

@app.route('/lead-finder/sample.csv')
@login_required
def sample_csv():
    return Response('business_name,contact_name,email,website,industry,location,source\nExample Studio,Alex,alex@example.com,https://example.com,Design,Sydney,User research\n',
                    mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=agencyos-leads-sample.csv'})

@app.route('/lead-finder', methods=['GET', 'POST'])
@login_required
def lead_finder():
    if request.method == 'POST':
        upload = request.files.get('csv_file')
        source = request.form.get('source', '').strip()
        if not upload or not upload.filename or not upload.filename.lower().endswith('.csv'):
            flash('Choose a .csv file.', 'error')
        elif not source or len(source) > 254 or any(ord(c) < 32 for c in source):
            flash('Enter a source of 1–254 characters, such as your directory export or research list.', 'error')
        else:
            try:
                rows = parse_csv(upload.read(), source, db().execute('SELECT * FROM leads').fetchall())
            except ValueError as exc:
                flash(str(exc), 'error')
            else:
                token = secrets.token_urlsafe(32)
                conn = db()
                conn.execute('DELETE FROM lead_imports WHERE created_at < ?', (time.time() - 3600,))
                conn.execute('INSERT INTO lead_imports VALUES(?,?,?,?)', (token, session['user_id'], json.dumps(rows), time.time()))
                conn.commit()
                return redirect(url_for('import_preview', token=token))
    return render_template('lead_finder.html')

@app.route('/lead-finder/preview/<token>', methods=['GET', 'POST'])
@login_required
def import_preview(token):
    conn = db()
    if request.method == 'POST':
        conn.execute('BEGIN IMMEDIATE')
    batch = conn.execute('SELECT * FROM lead_imports WHERE token=? AND user_id=?', (token, session['user_id'])).fetchone()
    if not batch or batch['created_at'] < time.time() - 3600:
        conn.rollback()
        flash('Import preview expired or already completed. Upload the CSV again.', 'error')
        return redirect(url_for('lead_finder'))
    rows = json.loads(batch['rows_json'])
    if request.method == 'POST':
        selected = set(request.form.getlist('selected'))
        allowed = set(request.form.getlist('allow_duplicate'))
        existing = list(conn.execute('SELECT * FROM leads').fetchall())
        imported, skipped, rejected = 0, 0, 0
        for item in rows:
            row = item['data']
            if item['errors']:
                rejected += 1
                continue
            number = str(item['number'])
            if number not in selected:
                skipped += 1
                continue
            duplicate = any(duplicate_reasons(row, other) for other in existing)
            if (duplicate or item['duplicates']) and number not in allowed:
                skipped += 1
                continue
            insert_lead(conn, row)
            existing.append(row)
            imported += 1
        conn.execute('DELETE FROM lead_imports WHERE token=?', (token,))
        conn.commit()
        flash(f'Import complete: {imported} imported, {rejected} rejected (invalid), {skipped} skipped (unselected or duplicate).', 'success')
        return redirect(url_for('leads'))
    return render_template('import_preview.html', rows=rows, token=token,
                           valid=sum(not row['errors'] for row in rows), invalid=sum(bool(row['errors']) for row in rows))


register_agent_routes(app, db, login_required)
production_security.install(app,db)
production_ops.register(app,db)
production_portal.register(app,db,login_required,APP_DIR)
email_preparation.register(app,db)
gmail_agent.register(app,db,login_required)
first_sale.register(app,db,login_required)
client_plans.register(app,db,login_required)
lead_engine.register(app,db,login_required,insert_lead)
office.register(app,db,login_required)
smart_writer.register(app,db,login_required)
night_shift.register(app,db,login_required)
story_mockups.register(app,db,login_required)
register_phase3(app, db, login_required, insert_lead)
register_phase4(app, db, login_required, insert_lead)
register_sales(app, db, login_required)
website_builder.register(app, db, login_required)
p10_release.register(app, db, login_required, APP_DIR)
phase7_billing.register(app, db, login_required)
p8_ops.register(app, db, login_required, lambda: DB_PATH)

if __name__ == "__main__":
    init_db()
    print('AgencyOS database: '+DB_PATH,flush=True)
    with app.app_context():
        print('Database identity: '+runtime_status.status(db(),DB_PATH)['database_identity'],flush=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False, request_handler=production_security.PrivateRequestHandler)

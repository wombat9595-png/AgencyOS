import os
import sqlite3
from functools import wraps
from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Flask, g, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("AGENCYOS_DB", os.path.join(APP_DIR, "agencyos.db"))
app = Flask(__name__)
app.secret_key = os.environ.get("AGENCYOS_SECRET_KEY", "change-this-before-deployment")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
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
    conn.commit()
    conn.close()

def money(cents):
    return f"${cents / 100:,.2f}"

@app.template_filter("money")
def money_filter(cents):
    return money(cents or 0)

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/setup", methods=["GET", "POST"])
def setup():
    init_db()
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
                             (username, generate_password_hash(password, method="pbkdf2:sha256"), datetime.utcnow().isoformat()))
                conn.commit()
                flash("Owner account created. Sign in to continue.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already in use.", "error")
    return render_template("setup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    init_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
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
    }
    recent_leads = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 5").fetchall()
    projects = conn.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 5").fetchall()
    return render_template("dashboard.html", counts=counts, recent_leads=recent_leads, projects=projects)

@app.route("/leads", methods=["GET", "POST"])
@login_required
def leads():
    conn = db()
    if request.method == "POST":
        name = request.form.get("business_name", "").strip()
        if not name:
            flash("Business name is required.", "error")
        else:
            conn.execute("""INSERT INTO leads(business_name,contact_name,email,website,industry,status,notes,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (
                name, request.form.get("contact_name","").strip(), request.form.get("email","").strip(),
                request.form.get("website","").strip(), request.form.get("industry","").strip(),
                request.form.get("status","New"), request.form.get("notes","").strip(), datetime.utcnow().isoformat()))
            conn.commit()
            flash("Lead saved.", "success")
            return redirect(url_for("leads"))
    rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    return render_template("leads.html", leads=rows)

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
            session["last_outreach_draft"] = draft
    leads_rows = conn.execute("SELECT id,business_name,contact_name,email FROM leads ORDER BY business_name").fetchall()
    draft = draft or session.pop("last_outreach_draft", "")
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
            cents = int(amount * 100)
        except (InvalidOperation, ValueError):
            cents = -1
        if not client or not title or cents < 0:
            flash("Enter a client, quote title and valid non-negative amount.", "error")
        else:
            conn.execute("""INSERT INTO quotes(lead_id,client_name,title,amount_cents,status,notes,created_at)
                VALUES(?,?,?,?,?,?,?)""", (request.form.get("lead_id") or None, client, title, cents,
                request.form.get("status","Draft"), request.form.get("notes","").strip(), datetime.utcnow().isoformat()))
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

@app.route("/invoices", methods=["GET", "POST"])
@login_required
def invoices():
    conn = db()
    if request.method == "POST":
        client = request.form.get("client_name","").strip()
        reference = request.form.get("reference","").strip()
        try:
            amount = Decimal(request.form.get("amount","0")).quantize(Decimal("0.01"))
            cents = int(amount * 100)
        except (InvalidOperation, ValueError):
            cents = -1
        if not client or not reference or cents < 0:
            flash("Enter a client, reference and valid non-negative amount.", "error")
        else:
            conn.execute("""INSERT INTO invoices(client_name,reference,amount_cents,status,due_date,notes,created_at)
                VALUES(?,?,?,?,?,?,?)""", (client, reference, cents, request.form.get("status","Unpaid"),
                request.form.get("due_date",""), request.form.get("notes","").strip(), datetime.utcnow().isoformat()))
            conn.commit()
            flash("Invoice record saved.", "success")
            return redirect(url_for("invoices"))
    rows = conn.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    return render_template("invoices.html", invoices=rows)

@app.route("/invoices/<int:invoice_id>/status", methods=["POST"])
@login_required
def invoice_status(invoice_id):
    status = request.form.get("status", "Unpaid")
    if status in ("Unpaid", "Paid", "Overdue", "Cancelled"):
        db().execute("UPDATE invoices SET status=? WHERE id=?", (status, invoice_id))
        db().commit()
    return redirect(url_for("invoices"))

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
                request.form.get("notes","").strip(), datetime.utcnow().isoformat()))
            conn.commit()
            flash("Project saved.", "success")
            return redirect(url_for("projects"))
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return render_template("projects.html", projects=rows)

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

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)

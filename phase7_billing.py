"""Invoice drafts and test-only payment reconciliation for AgencyOS Phase 7."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from production_security import secret
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

from flask import abort, flash, redirect, render_template, request, send_file, url_for
import payment_provider
from sales_store import digest

try:
    from cryptography.fernet import Fernet
except ImportError:  # bank detail storage remains disabled without this dependency
    Fernet = None


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p7_control (
      id INTEGER PRIMARY KEY CHECK(id=1), invoice_prefix TEXT NOT NULL DEFAULT 'TEST-INV',
      next_number INTEGER NOT NULL DEFAULT 1, business_name TEXT NOT NULL DEFAULT '',
      business_abn TEXT NOT NULL DEFAULT '', business_address TEXT NOT NULL DEFAULT '',
      business_email TEXT NOT NULL DEFAULT '', gst_mode TEXT NOT NULL DEFAULT '',
      terms TEXT NOT NULL DEFAULT 'Payment due within 14 days', provider TEXT NOT NULL DEFAULT 'mock',
      bank_ciphertext TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
    INSERT OR IGNORE INTO p7_control(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS p7_invoices (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), quote_id INTEGER NOT NULL REFERENCES p5_quotes(id),
      project_id INTEGER NOT NULL REFERENCES projects(id), cycle TEXT NOT NULL, invoice_number TEXT UNIQUE,
      snapshot_json TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'AUD', subtotal_cents INTEGER NOT NULL,
      gst_cents INTEGER NOT NULL, total_cents INTEGER NOT NULL, due_date TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Draft', synthetic INTEGER NOT NULL DEFAULT 0,
      pdf BLOB, created_at TEXT NOT NULL, approved_at TEXT, UNIQUE(quote_id,cycle));
    CREATE TABLE IF NOT EXISTS p7_payment_links (
      id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES p7_invoices(id), provider TEXT NOT NULL,
      token TEXT NOT NULL UNIQUE, hosted_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open',
      idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p7_payment_events (
      id INTEGER PRIMARY KEY, provider TEXT NOT NULL, external_event_id TEXT NOT NULL,
      event_type TEXT NOT NULL, payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
      verified_at TEXT NOT NULL, result TEXT NOT NULL DEFAULT 'Received',
      UNIQUE(provider,external_event_id));
    CREATE TABLE IF NOT EXISTS p7_payments (
      id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES p7_invoices(id),
      transaction_id TEXT NOT NULL UNIQUE, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
      currency TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('provider_verified','owner_reconciled')),
      evidence_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Verified', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p7_refunds (
      id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES p7_invoices(id),
      external_id TEXT NOT NULL UNIQUE, amount_cents INTEGER NOT NULL, status TEXT NOT NULL,
      event_id INTEGER NOT NULL REFERENCES p7_payment_events(id));
    CREATE TABLE IF NOT EXISTS p7_disputes (
      id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES p7_invoices(id),
      external_id TEXT NOT NULL UNIQUE, amount_cents INTEGER NOT NULL, status TEXT NOT NULL,
      event_id INTEGER NOT NULL REFERENCES p7_payment_events(id));
    CREATE TABLE IF NOT EXISTS p7_reminders (
      id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES p7_invoices(id),
      kind TEXT NOT NULL, scheduled_for TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft',
      created_at TEXT NOT NULL, UNIQUE(invoice_id,kind));
    CREATE INDEX IF NOT EXISTS p7_invoice_owner_idx ON p7_invoices(user_id,id);
    CREATE INDEX IF NOT EXISTS p7_payment_invoice_idx ON p7_payments(invoice_id,status);
    ''')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sign_mock(payload, secret):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def verify_mock(payload, signature, secret):
    return bool(secret and signature and hmac.compare_digest(sign_mock(payload, secret), signature))


def verify_stripe(raw_body, header, secret, tolerance=300, now=None):
    """Verify Stripe's timestamped HMAC signature. No network calls are made here."""
    if not secret or not header:
        return False
    fields = {}
    for part in header.split(','):
        key, sep, value = part.partition('=')
        if sep:
            fields.setdefault(key, []).append(value)
    try:
        timestamp = int(fields['t'][0])
    except (KeyError, ValueError, IndexError):
        return False
    current = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    if abs(current - timestamp) > tolerance:
        return False
    signed = str(timestamp).encode() + b'.' + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in fields.get('v1', []))


def _fernet():
    key = secret('AGENCYOS_BANK_ENCRYPTION_KEY')
    if not key or Fernet is None:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def _totals(content, cycle):
    total = content.get('totals', {}).get(cycle, {})
    lines = [item for item in content.get('items', []) if item.get('cycle') == cycle]
    return lines, int(total.get('subtotal_cents', 0)), int(total.get('gst_cents', 0)), int(total.get('total_cents', 0))


def verified_net_cents(conn, synthetic=False):
    gross=conn.execute("SELECT COALESCE(SUM(p.amount_cents),0) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE p.source='provider_verified' AND p.status='Verified' AND i.synthetic=? AND i.status!='Disputed (test)'",(int(synthetic),)).fetchone()[0]
    refunds=conn.execute("SELECT COALESCE(SUM(r.amount_cents),0) FROM p7_refunds r JOIN p7_invoices i ON i.id=r.invoice_id WHERE i.synthetic=? AND r.status IN ('verified','succeeded','complete')",(int(synthetic),)).fetchone()[0]
    return max(0,gross-refunds)


def _invoice_row(conn, invoice_id, user_id):
    row = conn.execute('SELECT * FROM p7_invoices WHERE id=? AND user_id=?', (invoice_id, user_id)).fetchone()
    if not row:
        abort(404)
    return row


def register(app, get_db, login_required):
    @app.route('/invoices', methods=['GET'])
    @login_required
    def invoices():
        conn = get_db()
        rows = conn.execute('''SELECT i.*,(SELECT hosted_url FROM p7_payment_links l WHERE l.invoice_id=i.id AND l.status='Open' ORDER BY l.id DESC LIMIT 1) payment_url
            FROM p7_invoices i WHERE i.user_id=? ORDER BY i.id DESC''', (request_session_user(),)).fetchall()
        quotes = conn.execute('''SELECT q.id quote_id,q.version,q.content_json,a.customer_name,p.project_id
            FROM p5_quotes q JOIN p5_acceptances a ON a.quote_id=q.id
            JOIN p5_project_briefs p ON p.acceptance_id=a.id
            JOIN p5_flows f ON f.id=q.flow_id
            WHERE f.user_id=? ORDER BY q.id DESC''', (request_session_user(),)).fetchall()
        control = dict(conn.execute('SELECT * FROM p7_control WHERE id=1').fetchone())
        paid = verified_net_cents(conn, synthetic=False)
        owner_paid = conn.execute("SELECT COALESCE(SUM(p.amount_cents),0) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE p.source='owner_reconciled' AND p.status='Verified' AND i.synthetic=0").fetchone()[0]
        owner_test_paid = conn.execute("SELECT COALESCE(SUM(p.amount_cents),0) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE p.source='owner_reconciled' AND p.status='Verified' AND i.synthetic=1").fetchone()[0]
        legacy_count = conn.execute('SELECT COUNT(*) FROM invoices').fetchone()[0]
        reminders = conn.execute('''SELECT r.*,i.invoice_number,i.due_date,i.total_cents FROM p7_reminders r
            JOIN p7_invoices i ON i.id=r.invoice_id WHERE i.user_id=? ORDER BY r.id DESC''',(request_session_user(),)).fetchall()
        return render_template('invoices.html', invoices=rows, quotes=quotes, control=control,
                               verified_paid=paid, owner_paid=owner_paid, owner_test_paid=owner_test_paid, legacy_count=legacy_count, reminders=reminders)

    @app.route('/invoices/settings', methods=['POST'])
    @login_required
    def invoice_settings():
        conn = get_db()
        fields = {key: request.form.get(key, '').strip() for key in ('business_name','business_abn','business_address','business_email','gst_mode','terms','provider')}
        if fields['gst_mode'] not in ('', 'not_registered', 'registered_10') or fields['provider'] not in ('mock','stripe_test'):
            flash('Choose an explicit GST setting.', 'error')
        elif len(fields['business_name']) > 160 or len(fields['business_abn']) > 20 or len(fields['business_address']) > 500 or len(fields['business_email']) > 254 or len(fields['terms']) > 500:
            flash('One or more business configuration fields are too long.', 'error')
        else:
            bank = [request.form.get(k, '').strip() for k in ('account_name','bsb','account_number')]
            ciphertext = conn.execute('SELECT bank_ciphertext FROM p7_control WHERE id=1').fetchone()[0]
            if any(bank):
                cipher = _fernet()
                if not cipher or not all(bank) or len(bank[0]) > 160 or len(bank[1]) > 12 or len(bank[2]) > 32:
                    flash('Bank details were not saved. Configure encryption and enter all three fields, or leave all blank.', 'error')
                    return redirect(url_for('invoices'))
                ciphertext = cipher.encrypt(json.dumps(dict(account_name=bank[0],bsb=bank[1],account_number=bank[2])).encode()).decode()
            conn.execute('''UPDATE p7_control SET business_name=?,business_abn=?,business_address=?,business_email=?,gst_mode=?,terms=?,provider=?,bank_ciphertext=?,updated_at=? WHERE id=1''',
                         (*fields.values(), ciphertext, stamp()))
            conn.commit()
            flash('Invoice configuration saved. Bank details are encrypted at rest and are not shown again.', 'success')
        return redirect(url_for('invoices'))

    @app.route('/invoices/draft', methods=['POST'])
    @login_required
    def invoice_draft():
        conn = get_db()
        quote_id = request.form.get('quote_id', type=int)
        cycle = request.form.get('cycle', 'one-off')
        source = conn.execute('''SELECT q.*,a.customer_name,a.quote_hash accepted_hash,p.project_id,f.user_id,f.synthetic
            FROM p5_quotes q JOIN p5_acceptances a ON a.quote_id=q.id
            JOIN p5_project_briefs p ON p.acceptance_id=a.id JOIN p5_flows f ON f.id=q.flow_id
            WHERE q.id=? AND f.user_id=? AND q.status='Owner-attested acceptance' AND q.content_hash=a.quote_hash''', (quote_id, request_session_user())).fetchone()
        if not source or cycle not in ('one-off','monthly'):
            flash('A draft can only be created from your accepted quote for this workspace.', 'error')
            return redirect(url_for('invoices'))
        config = dict(conn.execute('SELECT * FROM p7_control WHERE id=1').fetchone())
        if config['gst_mode'] not in ('not_registered','registered_10'):
            flash('Set the GST treatment explicitly before creating an invoice draft.', 'error')
            return redirect(url_for('invoices'))
        content = json.loads(source['content_json'])
        if digest(content) != source['content_hash']:
            flash('Accepted quote snapshot integrity check failed; invoice draft was not created.', 'error')
            return redirect(url_for('invoices'))
        if content.get('gst_mode') != config['gst_mode']:
            flash('Invoice GST treatment must match the accepted quote. Review the GST configuration before drafting.', 'error')
            return redirect(url_for('invoices'))
        lines, subtotal, gst, total = _totals(content, cycle)
        if not lines or total <= 0:
            flash('The accepted quote has no billable items for that cycle.', 'error')
            return redirect(url_for('invoices'))
        snapshot = dict(client_name=source['customer_name'], business={k:config[k] for k in ('business_name','business_abn','business_address','business_email','gst_mode','terms')},
                        quote_id=quote_id, quote_version=source['version'], acceptance_provenance='Owner-attested; not independently verified',
                        lines=lines, quote_gst_mode=content.get('gst_mode'), cycle=cycle)
        due = date.today() + timedelta(days=14)
        try:
            invoice_id = conn.execute('''INSERT INTO p7_invoices(user_id,quote_id,project_id,cycle,snapshot_json,subtotal_cents,gst_cents,total_cents,due_date,synthetic,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (request_session_user(),quote_id,source['project_id'],cycle,json.dumps(snapshot),subtotal,gst,total,due.isoformat(),int(source['synthetic']),stamp())).lastrowid
            conn.commit()
            flash('Synthetic invoice draft created. Review it before marking it test-approved.' if source['synthetic'] else 'Real-scope draft prepared, not issued. Verify legal details and approve a compliant issuance process separately.', 'success')
        except Exception:
            conn.rollback()
            flash('An invoice draft already exists for that quote and billing cycle.', 'error')
        return redirect(url_for('invoices'))

    @app.route('/invoices/<int:invoice_id>/approve-test', methods=['POST'])
    @login_required
    def invoice_approve_test(invoice_id):
        conn = get_db(); row = _invoice_row(conn, invoice_id, request_session_user())
        if row['status'] != 'Draft' or not row['synthetic'] or request.form.get('confirm')!='yes':
            flash('Only an unissued synthetic invoice draft can enter the test workflow.', 'error')
            return redirect(url_for('invoices'))
        config = conn.execute('SELECT * FROM p7_control WHERE id=1').fetchone()
        if not config['business_name'] or not config['gst_mode']:
            flash('Set the business identity and GST treatment before approving a test invoice.', 'error')
            return redirect(url_for('invoices'))
        number = f"{config['invoice_prefix']}-{date.today().year}-{config['next_number']:04d}"
        snapshot = json.loads(row['snapshot_json'])
        snapshot['business'] = {k:config[k] for k in ('business_name','business_abn','business_address','business_email','gst_mode','terms')}
        snapshot['test_notice'] = 'SYNTHETIC TEST INVOICE - NOT ISSUED TO A CUSTOMER'
        due = date.fromisoformat(row['due_date'])
        pdf = make_pdf(number, snapshot, row, due)
        conn.execute('UPDATE p7_control SET next_number=next_number+1 WHERE id=1')
        conn.execute("UPDATE p7_invoices SET invoice_number=?,snapshot_json=?,status='Approved (test)',approved_at=?,pdf=? WHERE id=?",
                     (number,json.dumps(snapshot),stamp(),pdf,invoice_id))
        conn.commit()
        flash('Test invoice approved. It is synthetic, local and not sent to a customer.', 'success')
        return redirect(url_for('invoices'))

    @app.route('/invoices/<int:invoice_id>/draft-pdf')
    @login_required
    def invoice_draft_pdf(invoice_id):
        row=_invoice_row(get_db(),invoice_id,request_session_user())
        if row['status']!='Draft':abort(409)
        snapshot=json.loads(row['snapshot_json'])
        if not snapshot['business'].get('business_name') or snapshot['quote_gst_mode'] not in ('not_registered','registered_10'):
            abort(409,description='Confirm actual business identity and GST treatment before exporting a draft.')
        snapshot['test_notice']='DRAFT - NOT ISSUED; OWNER LEGAL AND TAX REVIEW REQUIRED'
        pdf=make_pdf('DRAFT-'+str(invoice_id),snapshot,row,date.fromisoformat(row['due_date']))
        return send_file(BytesIO(pdf),mimetype='application/pdf',as_attachment=True,download_name='unissued-draft-'+str(invoice_id)+'.pdf')

    @app.route('/invoices/<int:invoice_id>/pdf')
    @login_required
    def invoice_pdf(invoice_id):
        row = _invoice_row(get_db(), invoice_id, request_session_user())
        if not row['pdf']:
            abort(404)
        return send_file(BytesIO(row['pdf']), mimetype='application/pdf', as_attachment=True,
                         download_name=(row['invoice_number'] or f'draft-{row["id"]}')+'.pdf')

    @app.route('/invoices/<int:invoice_id>/payment-link', methods=['POST'])
    @login_required
    def invoice_payment_link(invoice_id):
        conn=get_db(); row=_invoice_row(conn,invoice_id,request_session_user())
        if row['status'] not in ('Approved (test)','Partially paid') or not row['synthetic']:
            flash('A test payment link is available only for an approved synthetic invoice.', 'error')
        else:
            link=conn.execute('SELECT * FROM p7_payment_links WHERE invoice_id=? AND status=\'Open\'',(invoice_id,)).fetchone()
            if not link:
                token=secrets.token_urlsafe(24); provider=conn.execute('SELECT provider FROM p7_control WHERE id=1').fetchone()[0]
                if provider == 'mock':
                    hosted_url='/payments/mock/'+token
                    idempotency_key='invoice-'+str(invoice_id)
                elif provider == 'stripe_test':
                    try:
                        checkout=payment_provider.create_stripe_test_checkout(row,'http://127.0.0.1:5000/invoices','http://127.0.0.1:5000/invoices')
                    except payment_provider.ProviderError as exc:
                        flash(str(exc),'error')
                        return redirect(url_for('invoices'))
                    hosted_url=checkout['url']; idempotency_key=checkout['provider_id']
                else:
                    flash('Unknown payment provider; test link was not created.', 'error')
                    return redirect(url_for('invoices'))
                conn.execute('INSERT INTO p7_payment_links(invoice_id,provider,token,hosted_url,idempotency_key,created_at) VALUES(?,?,?,?,?,?)',
                             (invoice_id,provider,token,hosted_url,idempotency_key,stamp()))
                conn.commit(); link=conn.execute('SELECT * FROM p7_payment_links WHERE token=?',(token,)).fetchone()
            flash('Test payment link ready: '+link['hosted_url'], 'success')
        return redirect(url_for('invoices'))

    @app.route('/invoices/<int:invoice_id>/reconcile', methods=['POST'])
    @login_required
    def invoice_reconcile(invoice_id):
        conn=get_db(); row=_invoice_row(conn,invoice_id,request_session_user())
        reference=request.form.get('reference','').strip()[:160]
        amount=request.form.get('amount_cents',type=int)
        recorded=conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM p7_payments WHERE invoice_id=? AND status='Verified'",(invoice_id,)).fetchone()[0]
        if row['status'] not in ('Approved (test)','Partially paid') or not row['synthetic'] or not reference or not amount or amount<1 or amount>row['total_cents']-recorded:
            flash('Owner reconciliation here accepts only a synthetic approved invoice, positive amount and evidence reference.', 'error')
        else:
            txn='owner-'+secrets.token_hex(12)
            conn.execute("INSERT INTO p7_payments(invoice_id,transaction_id,amount_cents,currency,source,evidence_id,created_at) VALUES(?,?,?,'AUD','owner_reconciled',?,?)",
                         (invoice_id,txn,amount,reference,stamp()))
            conn.execute("UPDATE p7_invoices SET status='Owner reconciled (test)' WHERE id=?",(invoice_id,))
            conn.commit(); flash('Owner-recorded test reconciliation saved separately from provider-verified payment.','success')
        return redirect(url_for('invoices'))

    @app.route('/invoices/<int:invoice_id>/reminder', methods=['POST'])
    @login_required
    def invoice_reminder(invoice_id):
        conn=get_db(); row=_invoice_row(conn,invoice_id,request_session_user())
        if row['status'] not in ('Approved (test)','Partially paid'):
            flash('Only open test invoices can have a reminder draft.','error')
        else:
            kind=request.form.get('kind','due_soon')
            if kind not in ('due_soon','overdue'):
                flash('Unknown reminder schedule.','error')
            else:
                when=date.fromisoformat(row['due_date'])-timedelta(days=3) if kind=='due_soon' else date.fromisoformat(row['due_date'])+timedelta(days=1)
                conn.execute("INSERT OR IGNORE INTO p7_reminders(invoice_id,kind,scheduled_for,created_at) VALUES(?,?,?,?)",(invoice_id,kind,when.isoformat(),stamp()))
                conn.commit(); flash('Local reminder draft scheduled. It will not send an email.','success')
        return redirect(url_for('invoices'))

    @app.route('/payments/mock/<token>', methods=['GET','POST'])
    def mock_payment(token):
        conn=get_db(); link=conn.execute('''SELECT l.*,i.total_cents,i.currency,i.invoice_number,i.status invoice_status,i.user_id
            FROM p7_payment_links l JOIN p7_invoices i ON i.id=l.invoice_id WHERE l.token=?''',(token,)).fetchone()
        if not link or link['provider']!='mock' or link['invoice_status'] not in ('Approved (test)','Partially paid'):
            abort(404)
        if request.method=='POST':
            amount=request.form.get('amount_cents',type=int)
            if amount is None or amount<1 or amount>link['total_cents']:
                flash('Enter a positive test payment amount no greater than the invoice total.','error')
            else:
                payment_id='mock-tx-'+secrets.token_hex(12)
                event=dict(id='mock-evt-'+secrets.token_hex(12),type='payment.succeeded',data=dict(object=dict(id=payment_id,invoice_id=link['invoice_id'],amount=amount,currency='aud')))
                sig=sign_mock(event,secret('AGENCYOS_PAYMENT_WEBHOOK_SECRET') or secrets.token_hex(32))
                response=apply_event(conn,'mock',event,sig)
                flash('Synthetic payment event '+response+'.', 'success' if response in ('Applied','Duplicate') else 'error')
                conn.commit()
                return redirect(url_for('mock_payment',token=token))
        return render_template('mock_payment.html',link=link)

    @app.route('/payments/webhook/<provider>', methods=['POST'])
    def payment_webhook(provider):
        raw=request.get_data(cache=True)
        try: payload=json.loads(raw)
        except Exception: abort(400)
        if not isinstance(payload,dict) or len(raw)>100000:abort(400)
        if provider=='mock':
            signing_secret=secret('AGENCYOS_PAYMENT_WEBHOOK_SECRET')
            signature=request.headers.get('X-AgencyOS-Signature','')
            valid=verify_mock(payload,signature,signing_secret)
        elif provider=='stripe_test':
            signing_secret=secret('AGENCYOS_STRIPE_TEST_WEBHOOK_SECRET')
            valid=verify_stripe(raw,request.headers.get('Stripe-Signature',''),signing_secret)
        else: abort(404)
        if not valid: abort(400)
        conn=get_db();conn.execute('BEGIN IMMEDIATE')
        result=apply_event(conn,provider,payload,signature if provider=='mock' else request.headers.get('Stripe-Signature',''))
        get_db().commit()
        return {'result':result},200


def request_session_user():
    from flask import session
    return session.get('user_id')


def apply_event(conn, provider, payload, signature):
    """Accept only locally verified payloads; record each event once."""
    event_id=payload.get('id','')
    event_type=payload.get('type','')
    if not isinstance(event_id,str) or not 1<=len(event_id)<=200 or not isinstance(event_type,str) or not 1<=len(event_type)<=100:
        return 'Rejected'
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(raw.encode()).hexdigest()
    try:
        event_pk=conn.execute('INSERT INTO p7_payment_events(provider,external_event_id,event_type,payload_hash,payload_json,verified_at) VALUES(?,?,?,?,?,?)',
                              (provider,event_id,event_type,digest,raw,stamp())).lastrowid
    except sqlite3.IntegrityError:
        previous=conn.execute('SELECT payload_hash FROM p7_payment_events WHERE provider=? AND external_event_id=?',(provider,event_id)).fetchone()
        return 'Duplicate' if previous and previous[0]==digest else 'Rejected'
    data=payload.get('data',{})
    obj=data.get('object',{}) if isinstance(data,dict) else {}
    if not isinstance(obj,dict):obj={}
    if provider=='stripe_test' and (payload.get('livemode') is not False or
        (event_type=='checkout.session.completed' and obj.get('payment_status')!='paid') or
        (event_type=='payment_intent.succeeded' and obj.get('status')!='succeeded')):
        conn.execute("UPDATE p7_payment_events SET result='Rejected test-mode or unpaid event' WHERE id=?",(event_pk,));return 'Rejected'
    metadata=obj.get('metadata',{})
    invoice_id=obj.get('invoice_id') or (metadata.get('agencyos_invoice_id') if isinstance(metadata,dict) else None)
    if type(invoice_id) not in (int,str) or not str(invoice_id).isdigit():invoice_id=None
    else:invoice_id=int(invoice_id)
    if not invoice_id:
        conn.execute("UPDATE p7_payment_events SET result='Unmatched' WHERE id=?",(event_pk,)); return 'Unmatched'
    invoice=conn.execute('SELECT * FROM p7_invoices WHERE id=? AND synthetic=1',(invoice_id,)).fetchone()
    if not invoice:
        conn.execute("UPDATE p7_payment_events SET result='Unmatched' WHERE id=?",(event_pk,)); return 'Unmatched'
    amount=obj.get('amount_received',obj.get('amount_total',obj.get('amount',0)))
    currency=obj.get('currency') or ''
    currency=currency.lower() if isinstance(currency,str) else ''
    charge_event=event_type in ('payment.succeeded','payment_intent.succeeded','checkout.session.completed')
    if type(amount) is not int or amount<=0 or currency not in ('aud',) or (charge_event and invoice['status'] not in ('Approved (test)','Partially paid')):
        conn.execute("UPDATE p7_payment_events SET result='Needs review' WHERE id=?",(event_pk,)); return 'Needs review'
    if event_type in ('payment.succeeded','payment_intent.succeeded','checkout.session.completed'):
        txn=obj.get('payment_intent') if event_type=='checkout.session.completed' else obj.get('id')
        if not isinstance(txn,str) or not 1<=len(txn)<=200:
            conn.execute("UPDATE p7_payment_events SET result='Missing canonical transaction' WHERE id=?",(event_pk,));return 'Rejected'
        existing=conn.execute('SELECT * FROM p7_payments WHERE transaction_id=?',(txn,)).fetchone()
        if existing:
            result='Duplicate transaction' if existing['invoice_id']==invoice_id and existing['amount_cents']==amount else 'Needs review'
            conn.execute('UPDATE p7_payment_events SET result=? WHERE id=?',(result,event_pk));return 'Duplicate' if result=='Duplicate transaction' else result
        try:
            conn.execute("INSERT INTO p7_payments(invoice_id,transaction_id,amount_cents,currency,source,evidence_id,created_at) VALUES(?,?,?,?,?,?,?)",
                         (invoice_id,txn,amount,'AUD','provider_verified',event_id,stamp()))
        except sqlite3.IntegrityError:
            conn.execute("UPDATE p7_payment_events SET result='Duplicate transaction' WHERE id=?",(event_pk,)); return 'Duplicate'
        sum_paid=conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM p7_payments WHERE invoice_id=? AND status='Verified'",(invoice_id,)).fetchone()[0]
        if sum_paid>invoice['total_cents']:
            status='Needs reconciliation'
        elif sum_paid==invoice['total_cents']:
            status='Paid (test)'
        else:
            status='Partially paid'
        conn.execute('UPDATE p7_invoices SET status=? WHERE id=?',(status,invoice_id))
        conn.execute("UPDATE p7_payment_events SET result='Applied' WHERE id=?",(event_pk,)); return 'Applied'
    if event_type in ('charge.refunded','refund.updated'):
        if provider=='stripe_test':
            conn.execute("UPDATE p7_payment_events SET result='Needs provider refund correlation review' WHERE id=?",(event_pk,));return 'Needs review'
        amount=obj.get('amount_refunded',amount)
        paid=conn.execute('SELECT COALESCE(SUM(amount_cents),0) FROM p7_payments WHERE invoice_id=?',(invoice_id,)).fetchone()[0]
        external=obj.get('id')
        previous=conn.execute('SELECT * FROM p7_refunds WHERE external_id=?',(external,)).fetchone() if isinstance(external,str) else None
        others=conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM p7_refunds WHERE invoice_id=? AND external_id!=? AND status IN ('verified','succeeded','complete')",(invoice_id,external or '')).fetchone()[0]
        mixed=conn.execute('SELECT 1 FROM p7_refunds r JOIN p7_payment_events e ON e.id=r.event_id WHERE r.invoice_id=? AND e.event_type!=? LIMIT 1',(invoice_id,event_type)).fetchone()
        if type(amount) is not int or amount<=0 or amount+others>paid or not isinstance(external,str) or not 1<=len(external)<=200 or mixed or (previous and (previous['invoice_id']!=invoice_id or amount<previous['amount_cents'])):
            conn.execute("UPDATE p7_payment_events SET result='Needs review' WHERE id=?",(event_pk,));return 'Needs review'
        status=obj.get('status','verified')
        if status not in ('verified','succeeded','complete'):
            conn.execute("UPDATE p7_payment_events SET result='Refund pending or failed' WHERE id=?",(event_pk,));return 'Needs review'
        if previous:conn.execute('UPDATE p7_refunds SET amount_cents=?,status=?,event_id=? WHERE id=?',(amount,status,event_pk,previous['id']))
        else:conn.execute('INSERT INTO p7_refunds(invoice_id,external_id,amount_cents,status,event_id) VALUES(?,?,?,?,?)',(invoice_id,external,amount,status,event_pk))
        total_refunded=conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM p7_refunds WHERE invoice_id=? AND status IN ('verified','succeeded','complete')",(invoice_id,)).fetchone()[0]
        if total_refunded>=invoice['total_cents']:
            conn.execute("UPDATE p7_invoices SET status='Refunded (test)' WHERE id=?",(invoice_id,))
        elif total_refunded:
            conn.execute("UPDATE p7_invoices SET status='Partially refunded (test)' WHERE id=?",(invoice_id,))
        conn.execute("UPDATE p7_payment_events SET result='Refund recorded' WHERE id=?",(event_pk,)); return 'Applied'
    if event_type.startswith('charge.dispute.'):
        conn.execute('INSERT OR IGNORE INTO p7_disputes(invoice_id,external_id,amount_cents,status,event_id) VALUES(?,?,?,?,?)',
                     (invoice_id,obj.get('id') or event_id,amount,obj.get('status',event_type),event_pk))
        conn.execute("UPDATE p7_invoices SET status='Disputed (test)' WHERE id=?",(invoice_id,))
        conn.execute("UPDATE p7_payment_events SET result='Dispute recorded' WHERE id=?",(event_pk,)); return 'Applied'
    conn.execute("UPDATE p7_payment_events SET result='Ignored' WHERE id=?",(event_pk,)); return 'Ignored'


def make_pdf(number, snapshot, invoice, due):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    stream=BytesIO()
    doc=SimpleDocTemplate(stream,pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=18*mm,bottomMargin=18*mm)
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name='Subtle',parent=styles['Normal'],textColor=colors.HexColor('#536273'),fontSize=9,leading=13))
    story=[Paragraph('INVOICE DRAFT' if snapshot.get('test_notice','').startswith('DRAFT') else 'INVOICE',styles['Title']),Paragraph(_esc(snapshot.get('test_notice','SYNTHETIC TEST - NOT ISSUED TO A CUSTOMER')),styles['Heading2']),Spacer(1,5*mm)]
    business=snapshot['business']; story.extend([Paragraph(f"<b>{_esc(business['business_name'])}</b>",styles['Heading2']),Paragraph(_esc(business.get('business_address','')).replace('\n','<br/>'),styles['Normal']),Paragraph('ABN: '+_esc(business.get('business_abn') or 'Not supplied'),styles['Subtle']),Spacer(1,4*mm)])
    story.append(Paragraph(f"<b>Bill to:</b> {_esc(snapshot['client_name'])}<br/><b>Invoice:</b> {_esc(number)}<br/><b>Issue date:</b> {date.today().isoformat()}<br/><b>Due date:</b> {due.isoformat()}<br/><b>Currency:</b> AUD",styles['Normal']))
    data=[['Description','Qty','Unit price','GST','Line total']]
    for line in snapshot['lines']:
        data.append([_esc(line['description']),str(line['quantity']),_aud(line['unit_cents']),_aud(line['gst_cents']),_aud(line['total_cents'])])
    table=Table(data,colWidths=[78*mm,15*mm,29*mm,24*mm,29*mm],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#17324d')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#d3dce5')),('ALIGN',(1,1),(-1,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f4f7fa')]),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.extend([Spacer(1,7*mm),table,Spacer(1,5*mm)])
    totals=[['Subtotal',_aud(invoice['subtotal_cents'])],['GST',_aud(invoice['gst_cents'])],['Total AUD',_aud(invoice['total_cents'])]]
    t=Table(totals,colWidths=[35*mm,35*mm],hAlign='RIGHT'); t.setStyle(TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),('LINEABOVE',(0,-1),(-1,-1),.8,colors.HexColor('#17324d')),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])); story.append(t)
    story.extend([Spacer(1,8*mm),Paragraph('<b>Payment terms:</b> '+_esc(business.get('terms','')),styles['Normal']),Spacer(1,3*mm),Paragraph('No payment has been taken. This is an unissued draft for owner review; it is not a request for payment. Payment instructions are omitted.' if snapshot.get('test_notice','').startswith('DRAFT') else 'No payment has been taken. This synthetic example is for local testing only. Payment instructions are omitted because no approved business bank details were configured.',styles['Subtle'])])
    doc.build(story)
    return stream.getvalue()


def _esc(value):
    from xml.sax.saxutils import escape
    return escape(str(value or ''))


def _aud(cents):
    return 'AUD '+format(Decimal(cents)/100,',.2f')

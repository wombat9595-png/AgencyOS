"""Owner launch dashboard and deployment/data preparation; no external execution."""
import io
import json
import time
import zipfile
from pathlib import Path
from flask import abort,redirect,render_template,request,session,url_for,send_file
import discovery_preparation as discovery
import p10_release
import phase7_billing
from phase3_store import WorkflowError,stamp
from sales_quotes import money_input
from production_security import audit


def migrate(conn):
    discovery.migrate(conn)
    conn.executescript('''CREATE TABLE IF NOT EXISTS prep_expenses (
      id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,category TEXT NOT NULL,amount_cents INTEGER NOT NULL,
      evidence TEXT NOT NULL,synthetic INTEGER NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS prep_delivery (
      id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,release_id INTEGER NOT NULL,
      customer_evidence TEXT NOT NULL,plan_json TEXT NOT NULL,created_at TEXT NOT NULL);
    ''')
    columns={row[1] for row in conn.execute('PRAGMA table_info(p4_candidates)')}
    if 'crm_imported_at' not in columns:conn.execute("ALTER TABLE p4_candidates ADD COLUMN crm_imported_at TEXT NOT NULL DEFAULT ''")


def register(app,get_db,login_required,app_dir):
    @app.post('/launch/flows/<int:flow_id>/ai-assistance')
    @login_required
    def prepare_ai_assistance(flow_id):
        import sales_store
        conn=get_db();flow=conn.execute('SELECT * FROM p5_flows WHERE id=? AND user_id=?',(flow_id,session['user_id'])).fetchone()
        if not flow:abort(404)
        kind=request.form.get('kind')
        if kind not in ('research-assist','qa-assist') or flow['state']=='Cancelled':raise WorkflowError('Choose an active evidence synthesis or QA assistance request.')
        source=json.loads(flow['snapshot_json'])
        payload=dict(purpose='Review-only '+kind+' suggestions. Never change QA gates, invent observations or execute actions.',lead=source['lead'],evidence=source.get('evidence',[]))
        if kind=='qa-assist':
            version=conn.execute('''SELECT v.* FROM p6_site_versions v JOIN p6_sites s ON s.id=v.site_id
              JOIN p5_project_briefs b ON b.id=s.brief_id JOIN p5_acceptances a ON a.id=b.acceptance_id JOIN p5_quotes q ON q.id=a.quote_id
              WHERE q.flow_id=? ORDER BY v.version DESC LIMIT 1''',(flow_id,)).fetchone()
            if not version:raise WorkflowError('Generate a local website and deterministic QA report before requesting assistance.')
            payload.update(qa=json.loads(version['qa_json']),site_content=json.loads(version['content_json']),version=version['version'])
        conn.execute('BEGIN IMMEDIATE');sales_store.enqueue(conn,flow_id,kind,payload,'ai')
        conn.commit();return redirect(url_for('sales_flow',flow_id=flow_id))

    @app.get('/launch')
    @login_required
    def launch_dashboard():
        conn=get_db();owner=session['user_id']
        def n(sql,args=()):return conn.execute(sql,args).fetchone()[0]
        metrics={
          'Research results approved':n("SELECT COUNT(*) FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND j.kind='research' AND j.status='Approved'",(owner,)),
          'Qualification results approved':n("SELECT COUNT(*) FROM p4_jobs WHERE user_id=? AND kind='qualification' AND status='Approved'",(owner,)),
          'Emails prepared':n('SELECT COUNT(*) FROM p5_messages m JOIN p5_flows f ON f.id=m.flow_id WHERE f.user_id=?',(owner,)),
          'Live emails sent':0,
          'Replies recorded (all provenance)':n("SELECT COUNT(*) FROM p5_events e JOIN p5_messages m ON m.id=e.message_id JOIN p5_flows f ON f.id=m.flow_id WHERE f.user_id=? AND e.kind='reply'",(owner,)),
          'Quotes generated':n('SELECT COUNT(*) FROM p5_quotes q JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=?',(owner,)),
          'Accepted project briefs (owner-attested)':n('SELECT COUNT(*) FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id JOIN p5_flows f ON f.id=q.flow_id WHERE f.user_id=?',(owner,)),
          'Websites built':n('SELECT COUNT(*) FROM p6_sites s WHERE owner_id=? AND EXISTS (SELECT 1 FROM p6_site_versions v WHERE v.site_id=s.id)',(owner,)),
          'Websites approved':n("SELECT COUNT(*) FROM p6_sites WHERE owner_id=? AND status='Approved'",(owner,)),
          'Websites publicly published':0,
          'Synthetic invoices test-approved':n("SELECT COUNT(*) FROM p7_invoices WHERE user_id=? AND synthetic=1 AND status!='Draft'",(owner,)),
          'Live invoices issued':0,
          'Synthetic payment records verified':n("SELECT COUNT(*) FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id WHERE i.user_id=? AND i.synthetic=1 AND p.source='provider_verified' AND p.status='Verified'",(owner,)),
          'Pending sales approvals/reviews':n("SELECT COUNT(*) FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND j.status IN ('Awaiting approval','Needs review')",(owner,))}
        rule=conn.execute('SELECT config_json FROM prep_discovery WHERE user_id=?',(owner,)).fetchone()
        import runtime_status
        runtime=runtime_status.status(conn,conn.execute('PRAGMA database_list').fetchone()[2],'8')
        return render_template('launch.html',metrics=metrics,plan=json.loads(rule[0]) if rule else discovery.DEFAULTS,
          agents=conn.execute('SELECT * FROM agents ORDER BY id').fetchall(),runtime=runtime,
          alerts=conn.execute('SELECT * FROM ops_alerts WHERE resolved_at IS NULL ORDER BY id DESC').fetchall(),
          maintenance=conn.execute('SELECT * FROM p10_alerts WHERE owner_id=? ORDER BY id DESC LIMIT 10',(owner,)).fetchall(),
          live_paid=phase7_billing.verified_net_cents(conn,False),test_paid=phase7_billing.verified_net_cents(conn,True),
          expenses=conn.execute('SELECT * FROM prep_expenses WHERE user_id=? ORDER BY id DESC LIMIT 20',(owner,)).fetchall(),
          expense_total=n('SELECT COALESCE(SUM(amount_cents),0) FROM prep_expenses WHERE user_id=? AND synthetic=0',(owner,)),
          ai_reserved=n('SELECT COALESCE(SUM(reserved_cents),0) FROM p5_ai_usage WHERE day=?',(stamp()[:10],)),
          releases=conn.execute('SELECT * FROM p10_releases WHERE owner_id=? ORDER BY id DESC',(owner,)).fetchall())

    @app.post('/launch/discovery')
    @login_required
    def launch_discovery():
        plan=dict(states=request.form.getlist('states'),cities=[v.strip() for v in request.form.get('cities','').split(',') if v.strip()],industries=[v.strip() for v in request.form.get('industries','').split(',') if v.strip()],
          daily_leads=request.form.get('daily_leads',type=int),research_budget_cents=request.form.get('research_budget_cents',type=int),minimum_score=request.form.get('minimum_score',type=int),provider=request.form.get('provider'))
        plan=discovery.validate_plan(plan);conn=get_db()
        conn.execute('INSERT INTO prep_discovery VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET config_json=excluded.config_json,updated_at=excluded.updated_at',(session['user_id'],json.dumps(plan),stamp()))
        audit(conn,'discovery_plan',session['user_id']);conn.commit()
        return redirect(url_for('launch_dashboard'))

    @app.post('/launch/expenses')
    @login_required
    def launch_expense():
        amount=money_input(request.form.get('amount',''))
        category=request.form.get('category','');evidence=request.form.get('evidence','').strip()
        if category not in ('AI','Hosting','Data','Other') or not evidence or len(evidence)>500:raise WorkflowError('Record a category, actual amount and evidence reference.')
        conn=get_db();conn.execute('INSERT INTO prep_expenses(user_id,category,amount_cents,evidence,synthetic,created_at) VALUES(?,?,?,?,?,?)',(session['user_id'],category,amount,evidence,int(request.form.get('synthetic')=='yes'),stamp()))
        audit(conn,'expense_recorded',session['user_id']);conn.commit();return redirect(url_for('launch_dashboard'))

    @app.post('/launch/releases/<int:release_id>/prepare')
    @login_required
    def prepare_delivery(release_id):
        conn=get_db();release=conn.execute('SELECT * FROM p10_releases WHERE id=? AND owner_id=?',(release_id,session['user_id'])).fetchone()
        if not release:abort(404)
        site=conn.execute('SELECT * FROM p6_sites WHERE id=?',(release['site_id'],)).fetchone()
        version=conn.execute('SELECT * FROM p6_site_versions WHERE site_id=? AND version=?',(site['id'],release['version'])).fetchone()
        evidence=request.form.get('customer_evidence','').strip();target=request.form.get('target','local')
        if target not in ('local','aws_s3_sydney') or not evidence or len(evidence)>1000 or request.form.get('confirm')!='yes':raise WorkflowError('Record accurate customer permission evidence and approve preparation only.')
        if site['active_version']!=release['version'] or version['status']!='Approved':raise WorkflowError('Deployment preparation requires the exact currently approved website revision.')
        root=app.config.get('AGENCYOS_STAGING_ROOT',__import__('os').environ.get('AGENCYOS_STAGING_ROOT',Path(app_dir)/'output'/'staging'))
        conn.execute('BEGIN IMMEDIATE')
        if p10_release.health_check(conn,release,root)['result']!='passed':conn.commit();raise WorkflowError('Release integrity failed; preparation blocked.')
        plan=dict(provider=target,region='ap-southeast-2',release_id=release_id,version=release['version'],manifest=json.loads(release['manifest_json']),
          public_execution_authorized=False,customer_evidence_provenance='Owner-attested; not independently verified',
          prerequisites=['Separate owner launch authorization','Approved customer domain and DNS plan','Validated TLS','Approved working contact endpoint','External backup and monitoring'],
          api_contract='S3 PutObject for each manifest file; versioned private bucket, explicit SSE, content type text/html. CloudFront/TLS and DNS require separate approved resources. No request executed.')
        conn.execute('INSERT INTO prep_delivery(user_id,release_id,customer_evidence,plan_json,created_at) VALUES(?,?,?,?,?)',(session['user_id'],release_id,evidence,json.dumps(plan),stamp()))
        audit(conn,'deployment_plan_prepared',session['user_id'],{'release_id':release_id});conn.commit()
        return send_file(io.BytesIO(json.dumps(plan,indent=2).encode()),mimetype='application/json',as_attachment=True,download_name=f'release-{release_id}-preparation.json')

    @app.get('/launch/releases/<int:release_id>/handover')
    @login_required
    def handover(release_id):
        conn=get_db();release=conn.execute('SELECT * FROM p10_releases WHERE id=? AND owner_id=?',(release_id,session['user_id'])).fetchone()
        prepared=conn.execute('SELECT 1 FROM prep_delivery WHERE release_id=? AND user_id=?',(release_id,session['user_id'])).fetchone()
        if not release or not prepared:abort(404)
        root=Path(app.config.get('AGENCYOS_STAGING_ROOT',__import__('os').environ.get('AGENCYOS_STAGING_ROOT',Path(app_dir)/'output'/'staging')))
        conn.execute('BEGIN IMMEDIATE');check=p10_release.health_check(conn,release,root);conn.commit()
        if check['result']!='passed':raise WorkflowError('Handover blocked by failed artifact integrity.')
        stream=io.BytesIO();manifest=json.loads(release['manifest_json']);artifact=p10_release._safe_artifact(root,release['artifact_path'])
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in manifest['files']:archive.write(artifact/name,name)
            archive.writestr('manifest.json',release['manifest_json'])
            archive.writestr('HANDOVER.txt','Private review bundle. Connect an approved contact form before publication. No website was published. Preserve this manifest and prior release for rollback.')
        return send_file(io.BytesIO(stream.getvalue()),mimetype='application/zip',as_attachment=True,download_name=f'private-release-{release_id}.zip')

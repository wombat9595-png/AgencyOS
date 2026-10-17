"""Owner-facing sales workflow. No public customer portal or live sending."""
import json
import time
import uuid
from flask import abort, redirect, render_template, request, session, url_for
from phase3_store import WorkflowError, stamp
from phase3 import available_evidence, evidence_snapshot
from phase4_store import paused
from ai_drafts import DraftError
import sales_store as store
import sales_email as email
import sales_quotes as quotes
import sales_ai
import runtime_status


def register(app,get_db,login_required):
    app.add_template_filter(json.loads,'sales_decode')
    def flow(identifier):
        row=get_db().execute('SELECT * FROM p5_flows WHERE id=? AND user_id=?',(identifier,session['user_id'])).fetchone()
        if not row:abort(404)
        return row

    def owned_job(identifier):
        row=get_db().execute('SELECT j.* FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE j.id=? AND f.user_id=?',(identifier,session['user_id'])).fetchone()
        if not row:abort(404)
        return row

    def active(row):
        if row['state']=='Cancelled':
            raise WorkflowError('Sales workflow cancelled; create a new opportunity instead.')

    def payload(row):
        value=json.loads(row['snapshot_json'])
        return dict(lead=value['lead'],evidence=value['evidence'],packages=json.loads(row['package_json']),tone=row['tone'],research=value.get('research'),
                    requirements=row['requirements'],requirements_source=row['requirements_source'],branding=row['branding'])

    def message(identifier):
        row=get_db().execute('SELECT m.* FROM p5_messages m JOIN p5_flows f ON f.id=m.flow_id WHERE m.id=? AND f.user_id=?',(identifier,session['user_id'])).fetchone()
        if not row:abort(404)
        return row

    @app.route('/sales')
    @login_required
    def sales_home():
        conn=get_db()
        existing=conn.execute("SELECT * FROM p5_flows WHERE user_id=? AND state NOT IN ('Cancelled','Project brief ready') ORDER BY id DESC",(session['user_id'],)).fetchall()
        return render_template('sales.html',flows=conn.execute('SELECT * FROM p5_flows WHERE user_id=? ORDER BY id DESC LIMIT 100',(session['user_id'],)).fetchall(),
          active_flows={r['lead_id']:r['id'] for r in existing},runtime=runtime_status.status(conn,conn.execute('PRAGMA database_list').fetchone()[2],'5'),
          leads=conn.execute('SELECT * FROM leads ORDER BY business_name').fetchall(),packages=conn.execute('SELECT * FROM p5_packages WHERE user_id=? ORDER BY id DESC',(session['user_id'],)).fetchall(),
          research3=conn.execute("SELECT id,payload_json FROM p3_jobs WHERE user_id=? AND kind='research' AND status='Approved'",(session['user_id'],)).fetchall(),
          research4=conn.execute("SELECT id,payload_json FROM p4_jobs WHERE user_id=? AND kind='research' AND status='Approved'",(session['user_id'],)).fetchall(),
          evidence=conn.execute('SELECT id,lead_id,origin,source_url FROM p3_evidence WHERE user_id=? ORDER BY id DESC LIMIT 100',(session['user_id'],)).fetchall(),
          config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone(),readiness=email.readiness(conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()),
          suppression=conn.execute('SELECT * FROM p5_suppressions WHERE user_id=?',(session['user_id'],)).fetchall(),
          usage=conn.execute('SELECT COUNT(*) n,COALESCE(SUM(reserved_cents),0) cents FROM p5_ai_usage WHERE day=?',(stamp()[:10],)).fetchone())

    @app.route('/sales/settings',methods=['POST'])
    @login_required
    def sales_settings():
        conn=get_db()
        sender=email.address(request.form.get('sender',''))
        provider=request.form.get('provider','mock')
        gst=request.form.get('gst_mode','unset')
        budget=request.form.get('daily_cents',type=int)
        requests=request.form.get('daily_requests',type=int)
        inrate=request.form.get('input_rate',type=int)
        outrate=request.form.get('output_rate',type=int)
        model=request.form.get('pricing_model','').strip()
        if provider not in ('mock','ses-disabled') or gst not in ('unset','not_registered','registered_10') or any(v is None or v<0 for v in (budget,requests,inrate,outrate)) or budget>10000 or requests>100 or max(inrate,outrate)>1000000000 or len(model)>200:
            raise WorkflowError('Invalid settings. Maximum AUD 100/day and 100 AI requests/day; live sending cannot be enabled.')
        if budget and (request.form.get('pricing_review')!='yes' or not model or min(requests,inrate,outrate)<=0):
            raise WorkflowError('Positive budgets require explicit current AUD pricing review, model and request/rate ceilings. Keep zero for free local tests.')
        conn.execute('UPDATE p5_control SET sender=?,provider=?,gst_mode=?,daily_cents=?,daily_requests=?,input_rate=?,output_rate=?,pricing_model=?,pricing_expires=? WHERE id=1',
                     (sender,provider,gst,budget,requests,inrate,outrate,model,time.time()+7*86400 if budget else 0))
        store.log(conn,session['user_id'],'Updated sales configuration; live sending remains disabled. Pricing is owner-configured, not provider-verified.')
        conn.commit()
        return redirect(url_for('sales_home'))

    @app.route('/sales/packages',methods=['POST'])
    @login_required
    def sales_package():
        conn=get_db()
        name=request.form.get('name','').strip()
        category=request.form.get('category','')
        scope=request.form.get('scope','').strip()
        exclusions=request.form.get('exclusions','').strip()
        cycle=request.form.get('cycle','one-off')
        cents=quotes.money_input(request.form.get('price',''))
        if not name or len(name)>100 or category not in ('one-page','multi-page','custom','maintenance') or not scope or not exclusions or max(len(scope),len(exclusions))>4000 or cycle not in ('one-off','monthly'):
            raise WorkflowError('Provide package name, category, scope/exclusions and billing period.')
        conn.execute('BEGIN IMMEDIATE')
        version=conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM p5_packages WHERE user_id=? AND name=?',(session['user_id'],name)).fetchone()[0]
        conn.execute('INSERT INTO p5_packages(user_id,name,version,category,price_cents,cycle,scope,exclusions,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                     (session['user_id'],name,version,category,cents,cycle,scope,exclusions,stamp()))
        store.log(conn,session['user_id'],'Created package version '+name+' v'+str(version)+'. Existing snapshots unchanged.')
        conn.commit()
        return redirect(url_for('sales_home'))

    @app.route('/sales/new',methods=['POST'])
    @login_required
    def sales_new():
        conn=get_db()
        lead=conn.execute('SELECT * FROM leads WHERE id=?',(request.form.get('lead_id',type=int),)).fetchone()
        tone=request.form.get('tone','professional')
        mode=request.form.get('mode','local')
        if not lead or tone not in ('friendly','professional','direct') or mode not in ('local','ai') or request.form.get('approve_lead')!='yes':
            raise WorkflowError('Select and approve a lead for internal research, a tone and drafting mode. This is not marketing consent.')
        packages=[]
        for identifier in sorted(set(request.form.getlist('package_ids'))):
            package=conn.execute('SELECT * FROM p5_packages WHERE id=? AND user_id=?',(identifier,session['user_id'])).fetchone()
            if not package:raise WorkflowError('Package must belong to this owner.')
            item=dict(package)
            quantity=request.form.get('quantity_'+identifier,'1')
            try:item['quantity']=int(quantity)
            except ValueError:raise WorkflowError('Package quantity must be an integer.') from None
            if not 1<=item['quantity']<=100:raise WorkflowError('Package quantity must be 1–100.')
            packages.append(item)
        if not 1<=len(packages)<=5:raise WorkflowError('Select 1–5 immutable package versions.')
        available=available_evidence(conn,session['user_id'],lead['id'])
        selected=set(request.form.getlist('evidence_ids'))
        if len(selected)>10 or not selected<={str(r['id']) for r in available}:
            raise WorkflowError('Select at most ten reviewed evidence records for this lead.')
        evidence=evidence_snapshot([r for r in available if str(r['id']) in selected])
        snapshot=dict(lead={k:lead[k] for k in ('id','business_name','website','industry','location')},evidence=evidence,mode=mode)
        reference=request.form.get('research_reference','new')
        approved=False
        if reference!='new':
            try:phase,identifier=reference.split(':')
            except ValueError:raise WorkflowError('Invalid research reference.') from None
            if phase not in ('p3','p4'):raise WorkflowError('Unknown research source.')
            row=conn.execute('SELECT * FROM '+phase+'_jobs WHERE id=? AND user_id=? AND kind=\'research\' AND status=\'Approved\'',(identifier,session['user_id'])).fetchone()
            if not row:raise WorkflowError('Research must be owner-approved.')
            original=json.loads(row['payload_json'])
            original_lead=original['lead']
            if (original.get('lead_id') if phase=='p3' else original_lead['id'])!=lead['id'] or original_lead['website']!=lead['website'] or original_lead['business_name']!=lead['business_name']:
                raise WorkflowError('Research is for another/changed lead. Create fresh research.')
            snapshot['research']=dict(reference=reference,result=json.loads(row['result'] if phase=='p3' else row['result_json']))
            approved=True
        if len(store.dumps(snapshot))>40000:raise WorkflowError('Research snapshot too large; choose fewer evidence records.')
        conn.execute('BEGIN IMMEDIATE')
        existing=conn.execute("SELECT id FROM p5_flows WHERE user_id=? AND lead_id=? AND state NOT IN ('Cancelled','Project brief ready')",(session['user_id'],lead['id'])).fetchone()
        if existing:
            conn.rollback()
            from flask import flash
            flash('Opened existing sales opportunity #'+str(existing['id'])+'. No duplicate workflow or task was created.','success')
            return redirect(url_for('sales_flow',flow_id=existing['id']))
        identifier=conn.execute('INSERT INTO p5_flows(user_id,lead_id,snapshot_json,package_json,state,tone,synthetic,created_at) VALUES(?,?,?,?,?,?,?,?)',
          (session['user_id'],lead['id'],store.dumps(snapshot),store.dumps(packages),'Research approved' if approved else 'Research queued',tone,int(request.form.get('synthetic')=='yes'),stamp())).lastrowid
        row=conn.execute('SELECT * FROM p5_flows WHERE id=?',(identifier,)).fetchone()
        store.enqueue(conn,identifier,'outreach' if approved else 'research',payload(row),mode if approved else 'local',key='initial-'+str(identifier))
        store.log(conn,session['user_id'],'Owner approved lead for internal sales work; no marketing permission inferred.',identifier)
        conn.commit()
        return redirect(url_for('sales_flow',flow_id=identifier))

    @app.route('/sales/<int:flow_id>')
    @login_required
    def sales_flow(flow_id):
        row=flow(flow_id);conn=get_db()
        jobs=conn.execute('SELECT * FROM p5_jobs WHERE flow_id=? ORDER BY id',(flow_id,)).fetchall()
        estimates={}
        for job in jobs:
            if job['mode']=='ai' and job['status']=='Awaiting approval':
                try:
                    hashed,cents=sales_ai.approval(conn,job)
                    estimates[job['id']]=dict(hash=hashed,cents=cents)
                except (WorkflowError,DraftError):
                    estimates[job['id']]=None
        return render_template('sales_flow.html',flow=row,snapshot=json.loads(row['snapshot_json']),packages=json.loads(row['package_json']),
          jobs=jobs,estimates=estimates,sender=conn.execute('SELECT sender FROM p5_control WHERE id=1').fetchone()[0],
          runtime=runtime_status.status(conn,conn.execute('PRAGMA database_list').fetchone()[2],'5'),
          drafts=conn.execute('SELECT * FROM p5_drafts WHERE flow_id=? ORDER BY id DESC',(flow_id,)).fetchall(),
          messages=conn.execute('SELECT * FROM p5_messages WHERE flow_id=? ORDER BY id DESC',(flow_id,)).fetchall(),
          events=conn.execute('SELECT e.* FROM p5_events e JOIN p5_messages m ON m.id=e.message_id WHERE m.flow_id=? ORDER BY e.id',(flow_id,)).fetchall(),
          quotes=conn.execute('SELECT * FROM p5_quotes WHERE flow_id=? ORDER BY version DESC',(flow_id,)).fetchall(),
          followups=conn.execute('SELECT u.* FROM p5_followups u JOIN p5_messages m ON m.id=u.message_id WHERE m.flow_id=?',(flow_id,)).fetchall(),
          contact_basis=conn.execute('SELECT * FROM p5_contact_basis WHERE user_id=? ORDER BY reviewed_at DESC',(session['user_id'],)).fetchall(),
          acceptances=conn.execute('SELECT a.* FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id WHERE q.flow_id=?',(flow_id,)).fetchall(),
          briefs=[quotes.brief_view(conn,r) for r in conn.execute('SELECT b.* FROM p5_project_briefs b JOIN p5_acceptances a ON a.id=b.acceptance_id JOIN p5_quotes q ON q.id=a.quote_id WHERE q.flow_id=?',(flow_id,)).fetchall()],
          activity=conn.execute('SELECT * FROM p5_activity WHERE flow_id=? ORDER BY id DESC',(flow_id,)).fetchall())

    @app.route('/sales/jobs/<int:job_id>/decision',methods=['POST'])
    @login_required
    def sales_job_decision(job_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE')
        job=owned_job(job_id);row=flow(job['flow_id']);active(row)
        decision=request.form.get('decision','')
        if decision=='Approve AI' and job['status']=='Awaiting approval' and job['mode']=='ai':
            if request.form.get('confirm')!='yes':raise WorkflowError('Explicit AI data-sharing and maximum-charge approval required.')
            hashed,cents=sales_ai.approval(conn,job)
            if request.form.get('approval_hash')!=hashed or request.form.get('maximum_cents',type=int)!=cents:
                raise WorkflowError('Review the current displayed request and maximum price; approval inputs changed.')
            config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()
            context={key:config[key] for key in ('pricing_model','input_rate','output_rate','daily_cents','daily_requests','pricing_expires')}
            context.update(maximum_cents=cents,maximum_output_tokens=sales_ai.MAX_OUTPUT)
            conn.execute("UPDATE p5_jobs SET status='Queued',approval_hash=?,approval_expires=?,approval_context=?,updated_at=? WHERE id=?",(hashed,time.time()+3600,store.dumps(context),stamp(),job_id))
            store.log(conn,row['user_id'],f'Owner approved one exact AI request with ceiling AUD {cents/100:.2f}, expires in one hour.',row['id'],job_id)
        elif decision=='Approve research' and job['kind']=='research' and job['status']=='Needs review':
            snapshot=json.loads(row['snapshot_json']);snapshot['research']=dict(reference='p5:'+str(job_id),result=json.loads(job['result_json']))
            conn.execute("UPDATE p5_flows SET snapshot_json=?,state='Research approved' WHERE id=?",(store.dumps(snapshot),row['id']))
            revised=conn.execute('SELECT * FROM p5_flows WHERE id=?',(row['id'],)).fetchone()
            store.enqueue(conn,row['id'],'outreach',payload(revised),snapshot['mode'],key='research-to-outreach-'+str(job_id))
            conn.execute("UPDATE p5_jobs SET status='Approved',updated_at=? WHERE id=?",(stamp(),job_id))
        elif decision=='Prepare reply' and job['kind']=='classify' and job['status']=='Needs review':
            result=json.loads(job['result_json'])
            if result['classification'] in ('opt-out','rejection'):raise WorkflowError('No reply draft handoff after rejection/opt-out in this release.')
            original=json.loads(job['payload_json'])
            content=payload(row);content['original_reply']=original['original'];content['reason']='Owner reviewed reply interpretation'
            content['reply_event_id']=original['event_id'];content['reply_provenance']=original['provenance']
            store.enqueue(conn,row['id'],'reply',content,key='classification-to-reply-'+str(job_id))
            conn.execute("UPDATE p5_jobs SET status='Approved',updated_at=? WHERE id=?",(stamp(),job_id))
        elif decision=='Cancel' and job['status'] in ('Queued','Awaiting approval'):
            conn.execute("UPDATE p5_jobs SET status='Cancelled',updated_at=? WHERE id=?",(stamp(),job_id))
        elif decision=='Acknowledge result' and job['status']=='Needs review' and (job['kind'] in ('followup','research-assist','qa-assist') or (job['kind']=='classify' and json.loads(job['result_json'])['classification'] in ('rejection','opt-out'))):
            conn.execute("UPDATE p5_jobs SET status='Approved',updated_at=? WHERE id=?",(stamp(),job_id))
        elif decision=='Retry local' and job['status'] in ('Failed','Interrupted') and job['mode']=='local' and job['kind']!='dispatch' and job['attempts']<3:
            conn.execute("UPDATE p5_jobs SET status='Queued',error='',not_before=?,updated_at=? WHERE id=?",(time.time()+10,stamp(),job_id))
        else:abort(409,description='Decision invalid for this task state.')
        store.log(conn,row['user_id'],'Owner decision: '+decision,row['id'],job_id)
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/drafts/<int:draft_id>/approve',methods=['POST'])
    @login_required
    def sales_draft_approve(draft_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE')
        draft=conn.execute('SELECT * FROM p5_drafts WHERE id=?',(draft_id,)).fetchone()
        if not draft:abort(404)
        row=flow(draft['flow_id']);active(row)
        latest=conn.execute('SELECT MAX(version) FROM p5_drafts WHERE flow_id=? AND kind=?',(row['id'],draft['kind'])).fetchone()[0]
        if draft['status']!='Needs review' or draft['version']!=latest:abort(409)
        if conn.execute("SELECT 1 FROM p5_jobs WHERE flow_id=? AND kind=? AND status IN ('Queued','Running','Awaiting approval')",(row['id'],draft['kind'])).fetchone():
            raise WorkflowError('A revision is pending; review the latest completed draft afterward.')
        if request.form.get('confirm')!='yes':raise WorkflowError('Owner content review required.')
        content=json.loads(draft['content_json'])
        if draft['kind']=='proposal':
            if conn.execute('SELECT 1 FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id WHERE q.flow_id=?',(row['id'],)).fetchone():
                raise WorkflowError('Accepted scope is frozen; no further proposal handoff in this opportunity.')
            config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()
            origin=conn.execute('SELECT payload_json FROM p5_jobs WHERE id=?',(draft['job_id'],)).fetchone()
            content_payload=json.loads(origin['payload_json']);content_payload.update(gst_mode=config['gst_mode'],proposal=content,proposal_draft_id=draft_id)
            if config['gst_mode']=='unset':raise WorkflowError('Configure GST treatment before quote generation.')
            store.enqueue(conn,row['id'],'quote',content_payload,key='proposal-to-quote-'+str(draft_id))
        else:
            config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()
            if not config['sender']:raise WorkflowError('Configure sender metadata in Sales team → Sender, GST and optional AI configuration before preparing correspondence. Your reviewed draft has been preserved; return to this opportunity after saving the sender.')
            recipient=email.address(request.form.get('recipient',''))
            conn.execute('INSERT INTO p5_messages(flow_id,draft_id,recipient,sender,subject,body,created_at) VALUES(?,?,?,?,?,?,?)',
                         (row['id'],draft_id,recipient,config['sender'],content['subject'],content['body'],stamp()))
        conn.execute("UPDATE p5_drafts SET status='Approved' WHERE id=?",(draft_id,))
        conn.execute("UPDATE p5_jobs SET status='Approved',updated_at=? WHERE id=? AND status='Needs review'",(stamp(),draft['job_id']))
        conn.execute('UPDATE p5_flows SET state=? WHERE id=?',('Quote queued' if draft['kind']=='proposal' else 'Correspondence ready for exact approval',row['id']))
        store.log(conn,row['user_id'],'Owner approved exact draft version '+str(draft['version'])+'; no email sent.',row['id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/<int:flow_id>/revise',methods=['POST'])
    @login_required
    def sales_revise(flow_id):
        conn=get_db();row=flow(flow_id);active(row)
        kind=request.form.get('kind','outreach');reason=request.form.get('reason','').strip()
        mode=request.form.get('mode','local');tone=request.form.get('tone',row['tone'])
        if kind not in ('outreach','reply','proposal') or not reason or len(reason)>1000 or tone not in ('friendly','professional','direct'):
            raise WorkflowError('Choose a draft type, tone and revision reason.')
        if not conn.execute('SELECT 1 FROM p5_drafts WHERE flow_id=? AND kind=?',(flow_id,kind)).fetchone():raise WorkflowError('Complete the initial draft first.')
        if conn.execute('SELECT 1 FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id WHERE q.flow_id=?',(flow_id,)).fetchone():raise WorkflowError('Accepted scope is frozen. Create a new opportunity for changes.')
        content=payload(row);content.update(tone=tone,reason=reason)
        subject=request.form.get('subject','').strip();body=request.form.get('body','').strip()
        if subject or body:
            if mode!='local' or not subject or not body or len(subject)>200 or len(body)>6000 or any(c in subject for c in '\r\n'):
                raise WorkflowError('Owner edits require local mode, subject ≤200 and body ≤6,000 characters; no subject newlines.')
            content.update(owner_subject=subject,owner_body=body)
        conn.execute('BEGIN IMMEDIATE');store.enqueue(conn,flow_id,kind,content,mode)
        store.log(conn,row['user_id'],'Requested draft revision: '+reason,flow_id)
        conn.commit();return redirect(url_for('sales_flow',flow_id=flow_id))

    @app.route('/sales/messages/<int:message_id>/approve',methods=['POST'])
    @login_required
    def sales_message_approve(message_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE');item=message(message_id);row=flow(item['flow_id']);active(row)
        config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()
        if item['status']!='Draft' or request.form.get('confirm')!='yes' or request.form.get('mock_authorisation')!='yes':
            raise WorkflowError('Approve the exact recipient, sender, subject and body, and acknowledge mock-only fictional dispatch.')
        if config['provider']!='mock' or not row['synthetic']:raise WorkflowError('No live sending adapter; mock dispatch requires a fictional workflow.')
        valid,reason=email.eligibility(conn,item)
        if not valid:raise WorkflowError(reason)
        conn.execute("UPDATE p5_messages SET status='Approved',approval_hash=?,approval_expires=? WHERE id=?",(email.message_hash(item,config),time.time()+3600,message_id))
        store.enqueue(conn,row['id'],'dispatch',dict(message_id=message_id),key='dispatch-'+str(message_id))
        store.log(conn,row['user_id'],'Owner approved exact fictional recipient/content for mock dispatch only.',row['id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/events/mock',methods=['POST'])
    def sales_provider_event():
        raw=request.get_data(cache=False)
        event=email.verify_event(raw,request.headers.get('X-AgencyOS-Signature',''))
        conn=get_db();conn.execute('BEGIN IMMEDIATE')
        item=conn.execute('SELECT * FROM p5_messages WHERE provider_id=?',(event['provider_id'],)).fetchone()
        if not item:abort(404)
        try:identifier,created=email.apply_event(conn,item,'mock',event['event_id'],event['type'],event.get('text',''),event)
        except KeyError:raise WorkflowError('Incomplete mock event envelope.') from None
        conn.commit();return dict(event_id=identifier,created=created,provenance='Mock provider; not a real delivery/reply')

    @app.route('/sales/messages/<int:message_id>/record',methods=['POST'])
    @login_required
    def sales_record_reply(message_id):
        conn=get_db();item=message(message_id)
        text=request.form.get('text','').strip();kind=request.form.get('kind','reply')
        if not text or kind not in ('reply','bounce','complaint','unsubscribe') or request.form.get('confirm')!='yes':raise WorkflowError('Record actual correspondence text, type and owner attestation; do not invent a customer reply.')
        conn.execute('BEGIN IMMEDIATE')
        email.apply_event(conn,item,'owner-recorded',uuid.uuid4().hex,kind,text,dict(type=kind,text=text,provenance='Owner-recorded; not provider-verified'))
        conn.commit();return redirect(url_for('sales_flow',flow_id=item['flow_id']))

    @app.route('/sales/suppress',methods=['POST'])
    @login_required
    def sales_suppress():
        conn=get_db();reason=request.form.get('reason','').strip()
        if not reason or len(reason)>500:raise WorkflowError('Provide the suppression reason.')
        conn.execute('BEGIN IMMEDIATE');email.suppress(conn,session['user_id'],request.form.get('email',''),reason)
        conn.commit();return redirect(url_for('sales_home'))

    @app.route('/sales/contact-basis',methods=['POST'])
    @login_required
    def sales_contact_basis():
        conn=get_db();flow_id=request.form.get('flow_id',type=int);row=flow(flow_id)
        address=email.address(request.form.get('email',''))
        basis=request.form.get('basis_type','')
        reference=request.form.get('evidence_reference','').strip()
        expires=request.form.get('expires_on','').strip()
        if basis not in ('consent','existing_relationship','other_reviewed_basis') or not reference or len(reference)>1000 or request.form.get('attest')!='yes':
            raise WorkflowError('Choose a reviewed basis, record its evidence reference, and attest that the record is accurate.')
        if expires:
            from datetime import date
            try:date.fromisoformat(expires)
            except ValueError:raise WorkflowError('Expiry must be a valid ISO date (YYYY-MM-DD).') from None
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''INSERT INTO p5_contact_basis(user_id,email,basis_type,evidence_reference,reviewed_at,expires_on)
          VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,email) DO UPDATE SET basis_type=excluded.basis_type,
          evidence_reference=excluded.evidence_reference,reviewed_at=excluded.reviewed_at,expires_on=excluded.expires_on''',
          (session['user_id'],address,basis,reference,stamp(),expires))
        store.log(conn,session['user_id'],'Recorded owner-attested contact eligibility evidence for '+address+'; not independently verified and no permission to send inferred.',row['id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=flow_id))

    @app.route('/sales/messages/<int:message_id>/followup',methods=['POST'])
    @login_required
    def sales_followup(message_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE');item=message(message_id);row=flow(item['flow_id']);active(row)
        hours=request.form.get('hours',type=int)
        valid,reason=email.eligibility(conn,item,True)
        if not valid or not hours or not 1<=hours<=720 or request.form.get('confirm')!='yes':raise WorkflowError('Internal review requires eligible correspondence, 1–720 hours and approval. '+reason)
        if conn.execute('SELECT 1 FROM p5_followups WHERE message_id=?',(message_id,)).fetchone():raise WorkflowError('Review schedule already exists for this message.')
        conn.execute('INSERT INTO p5_followups(message_id,due_at) VALUES(?,?)',(message_id,time.time()+hours*3600))
        conn.execute("UPDATE p5_flows SET follow_state='Internal review scheduled' WHERE id=?",(row['id'],))
        store.log(conn,row['user_id'],'Scheduled internal follow-up eligibility review; no follow-up email.',row['id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/<int:flow_id>/proposal',methods=['POST'])
    @login_required
    def sales_proposal(flow_id):
        conn=get_db();row=flow(flow_id);active(row)
        requirements=request.form.get('requirements','').strip();source=request.form.get('requirements_source','').strip();branding=request.form.get('branding','').strip()
        if not requirements or not source or max(len(requirements),len(source),len(branding))>4000 or request.form.get('confirm')!='yes':raise WorkflowError('Record actual customer requirements, their source and owner review. Do not infer agreement from interest.')
        if not conn.execute("SELECT 1 FROM p5_drafts WHERE flow_id=? AND kind='outreach' AND status='Approved'",(flow_id,)).fetchone():raise WorkflowError('Approve outreach/research before preparing a proposal.')
        if conn.execute('SELECT 1 FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id WHERE q.flow_id=?',(flow_id,)).fetchone():raise WorkflowError('Accepted scope is frozen; create a new opportunity for changes.')
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE p5_flows SET requirements=?,requirements_source=?,branding=? WHERE id=?',(requirements,source,branding,flow_id))
        revised=conn.execute('SELECT * FROM p5_flows WHERE id=?',(flow_id,)).fetchone()
        store.enqueue(conn,flow_id,'proposal',payload(revised),request.form.get('mode','local'))
        conn.execute("UPDATE p5_flows SET state='Proposal queued' WHERE id=?",(flow_id,))
        store.log(conn,row['user_id'],'Owner recorded requirements and requested proposal; no customer acceptance inferred.',flow_id)
        conn.commit();return redirect(url_for('sales_flow',flow_id=flow_id))

    @app.route('/sales/quotes/<int:quote_id>/approve',methods=['POST'])
    @login_required
    def sales_quote_approve(quote_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE');quote=conn.execute('SELECT * FROM p5_quotes WHERE id=?',(quote_id,)).fetchone()
        if not quote:abort(404)
        row=flow(quote['flow_id']);active(row)
        latest=conn.execute('SELECT MAX(version) FROM p5_quotes WHERE flow_id=?',(row['id'],)).fetchone()[0]
        if quote['status']!='Draft' or quote['version']!=latest or request.form.get('confirm')!='yes':raise WorkflowError('Review and approve the current quote version.')
        config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()
        recipient=email.address(request.form.get('recipient',''))
        if not config['sender']:raise WorkflowError('Configure sender metadata first.')
        conn.execute("UPDATE p5_quotes SET status='Approved' WHERE id=?",(quote_id,))
        candidates=[]
        for job in conn.execute("SELECT * FROM p5_jobs WHERE flow_id=? AND kind='quote' AND result_json!=''",(row['id'],)).fetchall():
            if json.loads(job['result_json']).get('quote_id')==quote_id:
                candidates=[job['id']];break
            if job['result_json']==quote['content_json']:
                candidates.append(job['id'])
        # Legacy quotes without an origin ID are linked only when unambiguous.
        if len(candidates)==1:
            conn.execute("UPDATE p5_jobs SET status='Approved',updated_at=? WHERE id=? AND status='Needs review'",(stamp(),candidates[0]))
        conn.execute("UPDATE p5_flows SET state='Quote approved; awaiting acceptance' WHERE id=?",(row['id'],))
        conn.execute('INSERT INTO p5_messages(flow_id,quote_id,recipient,sender,subject,body,created_at) VALUES(?,?,?,?,?,?,?)',
          (row['id'],quote_id,recipient,config['sender'],'Draft quote #'+str(quote_id)+' for review',quotes.render_quote(json.loads(quote['content_json']),quote['version']),stamp()))
        store.log(conn,row['user_id'],'Approved quote version; correspondence still needs exact-content approval.',row['id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/quotes/<int:quote_id>/accept',methods=['POST'])
    @login_required
    def sales_quote_accept(quote_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE');quote=conn.execute('SELECT * FROM p5_quotes WHERE id=?',(quote_id,)).fetchone()
        if not quote:abort(404)
        row=flow(quote['flow_id']);active(row)
        if request.form.get('confirm')!='yes' or request.form.get('confirm_project')!='yes':raise WorkflowError('Attest that you verified actual customer acceptance of this exact version and authorise project creation.')
        if conn.execute("SELECT 1 FROM p5_jobs WHERE flow_id=? AND kind IN ('quote','proposal') AND status IN ('Queued','Running','Awaiting approval')",(row['id'],)).fetchone():raise WorkflowError('A proposal/quote revision is pending; acceptance must use the final version.')
        if conn.execute("SELECT 1 FROM p5_drafts WHERE flow_id=? AND kind='proposal' AND status='Needs review'",(row['id'],)).fetchone():raise WorkflowError('Review or reject pending proposal revisions before recording acceptance.')
        quotes.accept(conn,row,quote,request.form.get('customer_name',''),request.form.get('evidence',''),request.form.get('evidence_source',''),request.form.get('quote_hash',''))
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/<int:flow_id>/cancel',methods=['POST'])
    @login_required
    def sales_cancel(flow_id):
        conn=get_db();row=flow(flow_id)
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE p5_flows SET state='Cancelled',follow_state='Stopped' WHERE id=?",(flow_id,))
        conn.execute("UPDATE p5_jobs SET status='Cancelled',updated_at=? WHERE flow_id=? AND status IN ('Queued','Awaiting approval')",(stamp(),flow_id))
        conn.execute("UPDATE p5_followups SET status='Stopped' WHERE message_id IN (SELECT id FROM p5_messages WHERE flow_id=?)",(flow_id,))
        store.log(conn,row['user_id'],'Owner cancelled workflow. Already dispatched work may complete and remains recorded.',flow_id)
        conn.commit();return redirect(url_for('sales_flow',flow_id=flow_id))

    @app.route('/sales/jobs/<int:job_id>/interpret-ai',methods=['POST'])
    @login_required
    def sales_interpret_ai(job_id):
        conn=get_db();job=owned_job(job_id);row=flow(job['flow_id']);active(row)
        if job['kind']!='classify' or job['status']!='Needs review':raise WorkflowError('Select a reply classification requiring review.')
        conn.execute('BEGIN IMMEDIATE')
        store.enqueue(conn,row['id'],'classify',json.loads(job['payload_json']),'ai',key='ai-interpret-'+str(job_id))
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/followups/<int:followup_id>/stop',methods=['POST'])
    @login_required
    def sales_followup_stop(followup_id):
        conn=get_db()
        item=conn.execute('SELECT * FROM p5_followups WHERE id=?',(followup_id,)).fetchone()
        if not item:abort(404)
        owned=message(item['message_id'])
        conn.execute("UPDATE p5_followups SET status='Stopped' WHERE id=?",(followup_id,))
        conn.execute("UPDATE p5_jobs SET status='Cancelled',updated_at=? WHERE dedupe_key=? AND status='Queued'",(stamp(),'followup-'+str(followup_id)))
        store.log(conn,session['user_id'],'Owner stopped internal follow-up review.',owned['flow_id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=owned['flow_id']))

    @app.route('/sales/events/<int:event_id>/classify',methods=['POST'])
    @login_required
    def sales_classify_deferred(event_id):
        conn=get_db();event=conn.execute('SELECT * FROM p5_events WHERE id=?',(event_id,)).fetchone()
        if not event:abort(404)
        item=message(event['message_id']);row=flow(item['flow_id']);active(row)
        if event['kind']!='reply':raise WorkflowError('Only original replies can be interpreted.')
        original=json.loads(event['original_json'])
        conn.execute('BEGIN IMMEDIATE')
        text=original.get('text','')
        evidence=[dict(id=event_id,source_url='message:'+str(item['id']),observed_at=event['received_at'],origin=event['provider'],facts=dict(original=text))]
        store.enqueue(conn,row['id'],'classify',dict(event_id=event_id,original=text,provenance=event['provider'],evidence=evidence),key='classify-event-'+str(event_id))
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

    @app.route('/sales/drafts/<int:draft_id>/reject',methods=['POST'])
    @login_required
    def sales_draft_reject(draft_id):
        conn=get_db();conn.execute('BEGIN IMMEDIATE')
        draft=conn.execute('SELECT * FROM p5_drafts WHERE id=?',(draft_id,)).fetchone()
        if not draft:abort(404)
        row=flow(draft['flow_id']);active(row)
        if draft['status']!='Needs review':abort(409)
        conn.execute("UPDATE p5_drafts SET status='Rejected' WHERE id=?",(draft_id,))
        conn.execute("UPDATE p5_jobs SET status='Rejected',updated_at=? WHERE id=? AND status='Needs review'",(stamp(),draft['job_id']))
        store.log(conn,row['user_id'],'Owner rejected '+draft['kind']+' version '+str(draft['version'])+'; no handoff.',row['id'])
        conn.commit();return redirect(url_for('sales_flow',flow_id=row['id']))

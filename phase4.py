"""Working milestones 1–3: local coordination, licensed imports, authorised audits."""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from flask import abort, flash, redirect, render_template, request, session, url_for
from phase3_store import WorkflowError, connect, stamp, reserve_call
import phase4_store as store
import phase4_data as data
import website_audit


def worker_once(path):
    conn = connect(path)
    try:
        store.schedule_tick(conn, data.snapshot)
        data.search_tick(conn)
        job = store.claim(conn)
        if job is None:
            return False
        payload = json.loads(job['payload_json'])
        try:
            agent_id = 'website-audit' if job['kind']=='audit' else ('lead-discovery' if job['kind']=='discovery' else 'lead-research')
            agent = conn.execute('SELECT enabled FROM agents WHERE id=?',(agent_id,)).fetchone()
            if not agent or not agent['enabled']:
                raise WorkflowError('The selected agent is disabled in the Control Center.')
            if job['kind'] == 'audit':
                if job['approval_expires'] < time.time() or job['approval_hash'] != store.fingerprint(job, website_audit.context()):
                    conn.execute("UPDATE p4_jobs SET status='Awaiting approval',token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (stamp(),job['id']))
                    store.log(conn, job['user_id'], 'Audit approval expired or configuration changed; no request made.', job['id'])
                    conn.commit()
                    return True
                agent = conn.execute("SELECT enabled FROM agents WHERE id='website-audit'").fetchone()
                if not agent or not agent['enabled']:
                    raise WorkflowError('Website Audit Agent is disabled in the Control Center.')
                reserve_call(conn, 'p4-audit:'+payload['url'], 60, 20)

                def before_request():
                    # Recheck before every request, including secondary link checks.
                    if store.paused(conn):
                        raise WorkflowError('Emergency pause active; no further requests started.')
                    if job['approval_expires'] < time.time():
                        raise WorkflowError('Approval expired during audit; no further requests started.')
                    reserve_call(conn, 'p4-audit-requests', 0, 100)

                result = website_audit.audit(payload['url'], before_request)
            elif job['kind'] == 'discovery':
                result=dict(payload)
                result['candidates']=[item for item in payload['candidates'] if data.source_current(item)]
                result['expired_omitted']=len(payload['candidates'])-len(result['candidates'])
            elif job['kind'] == 'qualification':
                result = data.qualify(payload)
            elif job['kind'] == 'research':
                from phase3 import research_report
                # Real local analysis of saved facts; no simulated model output.
                result = research_report(dict(lead=payload['lead'], evidence=[], brief=''))
                result['source_records'] = payload['sources']
                result['approved_audits'] = payload['audits']
                result['classification'] += ' Deterministic local research; no AI provider was called.'
            else:
                raise WorkflowError('Unknown Phase 4 handler.')
            conn.execute('BEGIN IMMEDIATE')
            active = conn.execute("SELECT 1 FROM p4_jobs WHERE id=? AND status='Running' AND token=? AND lease_until>?", (job['id'],job['token'],time.time())).fetchone()
            if not active:
                conn.rollback()
                return True
            if store.paused(conn):
                # Retain observations but stop handoffs until explicitly resumed.
                store.log(conn, job['user_id'], 'Pause observed; completed output retained for review, no handoff.', job['id'])
            elif job['kind']=='qualification' and job['handoff'] and job['lead_id']:
                store.enqueue(conn, job['user_id'], job['lead_id'], 'research', payload, parent_id=job['id'])
            conn.execute("UPDATE p4_jobs SET status='Awaiting review',result_json=?,updated_at=?,lease_until=NULL WHERE id=?", (json.dumps(result),stamp(),job['id']))
            conn.execute('UPDATE p4_budget SET actual_cents=0 WHERE job_id=?', (job['id'],))
            store.log(conn, job['user_id'], 'Completed '+job['kind']+'; output requires review. No paid API call.', job['id'])
            conn.commit()
        except Exception as exc:
            conn.rollback()
            message = str(exc) if isinstance(exc,WorkflowError) else 'Unexpected task failure; no fabricated output. Check configuration and logs.'
            conn.execute("UPDATE p4_jobs SET status='Failed',error=?,updated_at=?,lease_until=NULL WHERE id=? AND token=? AND status='Running'", (message,stamp(),job['id'],job['token']))
            store.log(conn, job['user_id'], message, job['id'])
            conn.commit()
        return True
    finally:
        conn.close()


def register(app, get_db, login_required, insert_lead):
    def owner_job(identifier):
        row = get_db().execute('SELECT * FROM p4_jobs WHERE id=? AND user_id=?', (identifier,session['user_id'])).fetchone()
        if not row:
            abort(404)
        return row

    @app.before_request
    def pause_actions():
        # Applies to legacy action endpoints too. Login/logout and the pause switch
        # remain available so the owner can recover. GET pages stay accessible.
        if request.method=='POST' and request.endpoint not in ('agency_pause','login','logout','setup'):
            if store.paused(get_db()):
                raise WorkflowError('Emergency pause active. Resume in Agency Manager before making changes.')

    @app.route('/agency')
    @login_required
    def agency_manager():
        conn=get_db()
        jobs=conn.execute('SELECT * FROM p4_jobs WHERE user_id=? ORDER BY id DESC LIMIT 100', (session['user_id'],)).fetchall()
        activity=conn.execute('SELECT * FROM p4_activity WHERE user_id=? ORDER BY id DESC LIMIT 100', (session['user_id'],)).fetchall()
        schedules=conn.execute('''SELECT s.*,l.business_name FROM p4_schedules s JOIN leads l ON l.id=s.lead_id WHERE s.user_id=? ORDER BY s.id DESC''', (session['user_id'],)).fetchall()
        report={row['status']:row['n'] for row in conn.execute('SELECT status,COUNT(*) n FROM p4_jobs WHERE user_id=? AND created_at>=? GROUP BY status', (session['user_id'],stamp()[:10])).fetchall()}
        usage=conn.execute('SELECT COALESCE(SUM(reserved_cents),0) reserved,COALESCE(SUM(actual_cents),0) actual FROM p4_budget WHERE day=?', (stamp()[:10],)).fetchone()
        return render_template('agency.html',jobs=jobs,activity=activity,schedules=schedules,report=report,usage=usage,
                               control=conn.execute('SELECT * FROM p4_control WHERE id=1').fetchone(),leads=conn.execute('SELECT * FROM leads ORDER BY business_name').fetchall())

    @app.route('/agency/pause',methods=['POST'])
    @login_required
    def agency_pause():
        if request.form.get('paused') not in ('0','1'):
            raise WorkflowError('Choose pause or resume.')
        conn=get_db()
        conn.execute('BEGIN IMMEDIATE')
        value=int(request.form['paused'])
        conn.execute('UPDATE p4_control SET paused=? WHERE id=1', (value,))
        store.log(conn,session['user_id'],'Owner '+('paused all new work.' if value else 'resumed approved work.'))
        conn.commit()
        return redirect(url_for('agency_manager'))

    @app.route('/agency/budget',methods=['POST'])
    @login_required
    def agency_budget():
        # No paid Phase 4 executor exists: don't offer a meaningless spending switch.
        if request.form.get('daily_budget_cents')!='0':
            raise WorkflowError('Milestones 1–3 permit AUD 0 only. Paid execution requires a future reviewed integration.')
        conn=get_db()
        conn.execute('UPDATE p4_control SET daily_budget_cents=0 WHERE id=1')
        store.log(conn,session['user_id'],'Confirmed zero-dollar Phase 4 spending ceiling.')
        conn.commit()
        return redirect(url_for('agency_manager'))

    @app.route('/agency/queue',methods=['POST'])
    @login_required
    def agency_queue():
        conn=get_db()
        lead=conn.execute('SELECT * FROM leads WHERE id=?', (request.form.get('lead_id',type=int),)).fetchone()
        if not lead:
            raise WorkflowError('Select a saved lead.')
        kind=request.form.get('kind','qualification')
        if kind not in ('qualification','research','audit'):
            raise WorkflowError('Unsupported task.')
        payload=data.snapshot(conn,lead)
        if kind=='audit':
            if request.form.get('permission')!='yes':
                raise WorkflowError('Confirm permission for these exact public website paths before requesting an audit.')
            payload['url']=website_audit.audit_url(request.form.get('url','').strip() or lead['website'])
            payload['permission']='Owner confirmed permitted inspection of selected origin and linked paths, subject to robots.'
        conn.execute('BEGIN IMMEDIATE')
        identifier=store.enqueue(conn,session['user_id'],lead['id'],kind,payload,request.form.get('handoff')=='yes')
        conn.commit()
        return redirect(url_for('agency_job',job_id=identifier))

    @app.route('/agency/jobs/<int:job_id>')
    @login_required
    def agency_job(job_id):
        job=owner_job(job_id)
        return render_template('agency_job.html',job=job,payload=json.loads(job['payload_json']),result=json.loads(job['result_json']) if job['result_json'] else None,
                               events=get_db().execute('SELECT * FROM p4_activity WHERE job_id=? ORDER BY id',(job_id,)).fetchall())

    @app.route('/agency/jobs/<int:job_id>/decision',methods=['POST'])
    @login_required
    def agency_decision(job_id):
        conn=get_db()
        conn.execute('BEGIN IMMEDIATE')
        job=owner_job(job_id)
        decision=request.form.get('decision')
        if decision=='Queue audit' and job['kind']=='audit' and job['status']=='Awaiting approval':
            if request.form.get('confirm')!='yes' or os.environ.get('AGENCYOS_WEBSITE_FETCH')!='1':
                raise WorkflowError('Explicit request approval and AGENCYOS_WEBSITE_FETCH=1 are required. No request made.')
            conn.execute("UPDATE p4_jobs SET status='Queued',approval_hash=?,approval_context=?,approval_expires=?,updated_at=? WHERE id=?", (store.fingerprint(job,website_audit.context()),website_audit.context(),time.time()+86400,stamp(),job_id))
        elif decision in ('Approved','Rejected') and job['status']=='Awaiting review':
            conn.execute('UPDATE p4_jobs SET status=?,updated_at=? WHERE id=?',(decision,stamp(),job_id))
            if decision=='Approved' and job['kind']=='audit':
                payload=json.loads(job['payload_json'])
                result=json.loads(job['result_json'])
                # Store only concise verified findings/observations for Phase 3 research;
                # the full immutable report remains in the reviewed Phase 4 job.
                facts=dict(findings=result['findings'][:20], limitations=result['limitations'],audit_job_id=job_id)
                conn.execute('''INSERT INTO p3_evidence(user_id,lead_id,source_url,observed_at,origin,facts_json,content_hash)
                    VALUES(?,?,?,?,?,?,?)''',(job['user_id'],job['lead_id'],payload['url'],result['observed_at'],'Approved technical audit',json.dumps(facts),''))
        elif decision=='Cancelled' and job['status'] in ('Awaiting approval','Queued'):
            conn.execute("UPDATE p4_jobs SET status='Cancelled',updated_at=? WHERE id=?",(stamp(),job_id))
        elif decision=='Retry local' and job['status'] in ('Failed','Interrupted') and job['kind'] in ('qualification','research') and job['attempts']<3:
            conn.execute("UPDATE p4_jobs SET status='Queued',error='',not_before=?,updated_at=? WHERE id=?",(time.time()+10,stamp(),job_id))
        else:
            abort(409,description='Decision is not valid for this task state; no action repeated.')
        store.log(conn,session['user_id'],'Owner decision: '+decision,job_id)
        conn.commit()
        return redirect(url_for('agency_job',job_id=job_id))

    @app.route('/agency/schedules',methods=['POST'])
    @login_required
    def agency_schedule():
        conn=get_db()
        lead_id=request.form.get('lead_id',type=int)
        hours=request.form.get('hours',type=int)
        if request.form.get('confirm')!='yes' or not hours or not 1<=hours<=720 or not conn.execute('SELECT 1 FROM leads WHERE id=?',(lead_id,)).fetchone():
            raise WorkflowError('Select a lead, 1–720 hours and explicit standing permission for local qualification→research only.')
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT COUNT(*) FROM p4_schedules WHERE user_id=? AND enabled=1',(session['user_id'],)).fetchone()[0]>=20:
            raise WorkflowError('At most 20 active local schedules.')
        conn.execute('INSERT INTO p4_schedules(user_id,lead_id,interval_seconds,next_run,created_at) VALUES(?,?,?,?,?)',(session['user_id'],lead_id,hours*3600,time.time(),stamp()))
        store.log(conn,session['user_id'],'Authorised recurring local qualification→research; no external access.')
        conn.commit()
        return redirect(url_for('agency_manager'))

    @app.route('/agency/schedules/<int:schedule_id>/stop',methods=['POST'])
    @login_required
    def agency_schedule_stop(schedule_id):
        conn=get_db()
        cursor=conn.execute('UPDATE p4_schedules SET enabled=0 WHERE id=? AND user_id=?',(schedule_id,session['user_id']))
        if not cursor.rowcount:
            abort(404)
        store.log(conn,session['user_id'],'Disabled schedule #'+str(schedule_id)+'; already queued tasks remain individually cancellable.')
        conn.commit()
        return redirect(url_for('agency_manager'))

    @app.route('/discovery/licensed',methods=['GET','POST'])
    @login_required
    def licensed_discovery():
        conn=get_db()
        if request.method=='POST':
            upload=request.files.get('dataset')
            required=('name','licence_url','permitted_use','attribution','reviewer')
            fields={key:request.form.get(key,'').strip() for key in required}
            days=request.form.get('review_days',type=int)
            if not upload or request.form.get('confirm')!='yes' or any(not value or len(value)>2000 for value in fields.values()) or not days or not 1<=days<=30:
                raise WorkflowError('Supply a CSV, complete source permission record, 1–30 review days and explicit attestation. No licence is verified automatically.')
            fields['licence_url']=data.public_source_url(fields['licence_url'])
            rows=data.parse_dataset(upload.read())
            conn.execute('BEGIN IMMEDIATE')
            source_id=conn.execute('''INSERT INTO p4_sources(user_id,name,licence_url,permitted_use,attribution,reviewer,reviewed_at,expires_at)
                VALUES(?,?,?,?,?,?,?,?)''',(session['user_id'],fields['name'],fields['licence_url'],fields['permitted_use'],fields['attribution'],fields['reviewer'],stamp(),(datetime.now(timezone.utc)+timedelta(days=days)).isoformat())).lastrowid
            for row in rows:
                conn.execute('''INSERT INTO p4_candidates(user_id,source_id,external_id,source_url,observed_at,imported_at,state,city,data_json)
                    VALUES(?,?,?,?,?,?,?,?,?)''',(session['user_id'],source_id,row['external_id'],row['source_url'],row['observed_at'],stamp(),row['state'],row['city'],json.dumps(row['data'])))
            store.log(conn,session['user_id'],f'Imported {len(rows)} source-reported candidates for review; permission attested by owner, not independently verified.')
            conn.commit()
            return redirect(url_for('licensed_discovery'))
        state=request.args.get('state','')
        city=request.args.get('city','').strip()
        industry=request.args.get('industry','').strip()
        if state and state not in data.STATES:
            raise WorkflowError('Unknown Australian state/territory code.')
        rows=conn.execute('''SELECT c.*,s.name,s.attribution,s.licence_url,s.expires_at FROM p4_candidates c JOIN p4_sources s ON s.id=c.source_id
            WHERE c.user_id=? AND (?='' OR c.state=?) AND (?='' OR lower(c.city)=lower(?)) ORDER BY c.id DESC LIMIT 1000''',(session['user_id'],state,state,city,city)).fetchall()
        candidates=[]
        for row in rows:
            details=json.loads(row['data_json'])
            if industry and industry.casefold() not in details['industry'].casefold():
                continue
            candidates.append(dict(row=dict(row),data=details,duplicates=data.duplicate(conn,row),current=data.source_current(row)))
        return render_template('licensed_discovery.html',candidates=candidates,states=data.STATES,state=state,city=city,industry=industry,searches=conn.execute('SELECT * FROM p4_search_schedules WHERE user_id=? ORDER BY id DESC',(session['user_id'],)).fetchall())

    @app.route('/discovery/licensed/<int:candidate_id>/import',methods=['POST'])
    @login_required
    def licensed_import(candidate_id):
        conn=get_db()
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('''SELECT c.*,s.name,s.attribution,s.licence_url,s.expires_at FROM p4_candidates c JOIN p4_sources s ON s.id=c.source_id WHERE c.id=? AND c.user_id=?''',(candidate_id,session['user_id'])).fetchone()
        if not row:
            abort(404)
        if row['status']!='Pending':
            abort(409)
        if not data.source_current(row) or request.form.get('confirm')!='yes':
            raise WorkflowError('A current owner-reviewed permission record and explicit candidate approval are required.')
        hints=data.duplicate(conn,row)
        if hints:
            raise WorkflowError('Duplicate blocked: '+'; '.join(hints[:5])+'. Review the existing profile; no automatic merge or overwrite.')
        values=json.loads(row['data_json'])
        values['source']=row['name'][:254]
        insert_lead(conn,values)
        lead_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.execute("UPDATE p4_candidates SET status='Imported',lead_id=? WHERE id=?",(lead_id,candidate_id))
        facts=dict(source_id=row['external_id'],licence_url=row['licence_url'],attribution=row['attribution'],state=row['state'],city=row['city'],data=values,
                   limitation='Source-reported; not independently verified. Public details do not establish marketing consent.')
        conn.execute('INSERT INTO p3_evidence(user_id,lead_id,source_url,observed_at,origin,facts_json) VALUES(?,?,?,?,?,?)',(session['user_id'],lead_id,row['source_url'],row['observed_at'],'Licensed directory',json.dumps(facts)))
        store.log(conn,session['user_id'],'Owner imported source candidate #'+str(candidate_id)+' as lead #'+str(lead_id))
        conn.commit()
        return redirect(url_for('licensed_discovery'))

    @app.route('/discovery/licensed/schedule',methods=['POST'])
    @login_required
    def licensed_schedule():
        conn=get_db()
        state=request.form.get('state','')
        city=request.form.get('city','').strip()
        industry=request.form.get('industry','').strip()
        hours=request.form.get('hours',type=int)
        maximum=request.form.get('maximum',type=int)
        if state not in data.STATES or len(city)>100 or len(industry)>100 or not hours or not 1<=hours<=720 or not maximum or not 1<=maximum<=10 or request.form.get('confirm')!='yes':
            raise WorkflowError('Choose a state, 1–720 hours, 1–10 candidates and explicit permission for scheduled offline searches.')
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT COUNT(*) FROM p4_search_schedules WHERE user_id=? AND enabled=1',(session['user_id'],)).fetchone()[0]>=20:
            raise WorkflowError('At most 20 active offline location schedules.')
        if not data.search_snapshot(conn,session['user_id'],state,city,industry,maximum)['candidates']:
            raise WorkflowError('Import matching currently reviewed source records before scheduling this offline search.')
        conn.execute('INSERT INTO p4_search_schedules(user_id,state,city,industry,interval_seconds,maximum,next_run) VALUES(?,?,?,?,?,?,?)',
                     (session['user_id'],state,city,industry,hours*3600,maximum,time.time()))
        store.log(conn,session['user_id'],'Authorised offline location schedule for '+state+' '+city+'; no external calls or CRM import.')
        conn.commit()
        return redirect(url_for('licensed_discovery'))

    @app.route('/discovery/licensed/schedules/<int:schedule_id>/stop',methods=['POST'])
    @login_required
    def licensed_schedule_stop(schedule_id):
        conn=get_db()
        if not conn.execute('UPDATE p4_search_schedules SET enabled=0 WHERE id=? AND user_id=?',(schedule_id,session['user_id'])).rowcount:
            abort(404)
        store.log(conn,session['user_id'],'Stopped offline location search #'+str(schedule_id))
        conn.commit()
        return redirect(url_for('licensed_discovery'))

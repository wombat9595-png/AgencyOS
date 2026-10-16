"""Named agent handlers and reliable, bounded sales handoffs."""
import json
import re
import time
from phase3_store import WorkflowError, connect, stamp
from phase4_store import paused
import sales_store as store
import sales_email as email
import sales_quotes as quotes
import sales_ai
import website_builder
from ai_drafts import DraftError


def classify(text):
    lower=text.casefold()
    if email.opted_out(text):
        label='opt-out';reason='Opt-out language found. Suppression applies conservatively; do not contact.'
    elif re.search(r'\b(not interested|no thanks|no thank you|not looking)\b',lower):
        label='rejection';reason='Rejection phrase detected; stop follow-ups pending owner review.'
    elif '?' in text:
        label='question';reason='Question punctuation detected; owner should interpret the full original.'
    elif re.search(r'\b(interested|tell me more|sounds good)\b',lower) and not re.search(r'\b(not|never|don.t)\b',lower):
        label='interest';reason='Possible interest language. Not acceptance of scope, price or a contract.'
    else:
        label='uncertain';reason='No reliable local classification. Owner attention required.'
    return dict(classification=label,reason=reason,uncertainty='Rule-based suggestion; preserve and review original message.',owner_attention=True)


def write_local(kind,payload):
    lead=payload['lead']
    name=lead['business_name']
    packages=payload['packages']
    service=', '.join(p['name'] for p in packages)
    evidence=payload.get('evidence',[])
    if 'owner_subject' in payload:
        return dict(subject=payload['owner_subject'],body=payload['owner_body'],evidence_ids=[i['id'] for i in evidence],
                    mode='Owner-edited version; not model verified',reason=payload['reason'])
    intro={'friendly':'Hi there,','professional':'Hello,','direct':'Hello,'}[payload.get('tone','professional')]
    if kind=='outreach':
        subject=('Website discussion for '+name)[:200]
        offer={'friendly':f'I’d be happy to discuss {service} if it fits your website goals.',
               'professional':f'I’m preparing an offer for {service}. Would discussing your website goals be useful?',
               'direct':f'Would a discussion about {service} be useful?'}[payload.get('tone','professional')]
        lines=[intro,'',offer]
        # Quote evidence rather than converting a directory gap into a diagnosis.
        for item in evidence:
            facts=item['facts']
            findings=facts.get('findings',[]) if item['origin']=='Approved technical audit' else []
            if findings:
                finding=findings[0]
                lines+=['',f'A reviewed technical observation from {item["observed_at"]} at {item["source_url"]} recorded: {finding["detail"]}']
                break
        lines+=['','Any proposed changes would depend on your goals and confirmation of the current website.','', '[Owner signature — review before use]']
    elif kind=='reply':
        subject=('Re: website discussion for '+name)[:200]
        lines=[intro,'','Thank you for your message. I will review it before confirming scope, pricing or next steps.','', '[Owner signature — review before use]']
    else:
        subject=('Website proposal for '+name)[:200]
        lines=['Draft proposal', '', 'Owner-recorded customer requirements:',payload['requirements'],
               '', 'Source of requirements (not independently verified):',payload['requirements_source'],
               '', 'Proposed scope:']
        for package in packages:
            lines += [package['name']+': '+package['scope'],'Exclusions: '+package['exclusions']]
        lines+=['','Pricing will be itemised in the reviewed AUD quote. No agreement or payment is implied.']
    return dict(subject=subject,body='\n'.join(lines),evidence_ids=[i['id'] for i in evidence],
                mode='Local rules; no AI request',tone=payload.get('tone','professional'),
                generation_reason=payload.get('reason','Owner-requested '+kind+' from approved saved inputs'),
                limitation='Recorded source facts are not independent business verification. Suggestions and offers are not proven needs.')


def tick(conn):
    conn.execute('BEGIN IMMEDIATE')
    if paused(conn):
        conn.commit();return
    for row in conn.execute("SELECT u.*,m.flow_id FROM p5_followups u JOIN p5_messages m ON m.id=u.message_id JOIN p5_flows f ON f.id=m.flow_id WHERE u.status='Scheduled' AND u.due_at<=? AND f.state!='Cancelled' ORDER BY u.id LIMIT 20",(time.time(),)).fetchall():
        try:
            store.enqueue(conn,row['flow_id'],'followup',dict(message_id=row['message_id']),key='followup-'+str(row['id']))
        except WorkflowError:
            conn.execute('UPDATE p5_followups SET due_at=? WHERE id=?',(time.time()+60,row['id']))
            continue
        conn.execute("UPDATE p5_followups SET status='Queued for review' WHERE id=?",(row['id'],))
    conn.commit()


def worker_once(path):
    conn=connect(path)
    try:
        tick(conn)
        job=store.claim(conn)
        if not job:return False
        payload=json.loads(job['payload_json'])
        try:
            agent_id=('lead-research' if job['kind']=='research' else
                      'sales-replies' if job['kind'] in ('classify','reply','followup') else
                      'sales-proposals' if job['kind'] in ('proposal','quote') else
                      'website-builder' if job['kind']=='website' else 'outreach')
            agent=conn.execute('SELECT enabled FROM agents WHERE id=?',(agent_id,)).fetchone()
            if not agent or not agent['enabled']:
                raise WorkflowError('The selected sales agent is disabled in the Control Center.')
            if job['kind']=='website':
                qa_agent=conn.execute('SELECT enabled FROM agents WHERE id=?',('website-qa',)).fetchone()
                if not qa_agent or not qa_agent['enabled']:
                    raise WorkflowError('The Website QA Agent is disabled in the Control Center.')
            if job['mode']=='ai' and job['kind']=='website':
                generated=sales_ai.execute(conn,job)
                result=website_builder.apply_ai_copy(website_builder.build(conn,payload),generated)
            elif job['mode']=='ai':
                # Suppression cannot be overridden by the model's interpretation.
                result=sales_ai.execute(conn,job)
                if job['kind']=='classify' and email.opted_out(payload['original']):
                    result=classify(payload['original'])
            elif job['kind']=='dispatch':
                result=email.dispatch(conn,job)
            elif job['kind']=='research':
                result=dict(lead=payload['lead'],evidence=payload['evidence'],classification='Recorded facts and reviewed observations; local analysis, no AI call.',
                            questions=['Confirm the customer’s goals, scope and permitted contact before proceeding.'])
            elif job['kind']=='classify':
                result=classify(payload['original'])
            elif job['kind']=='followup':
                message=conn.execute('SELECT * FROM p5_messages WHERE id=?',(payload['message_id'],)).fetchone()
                valid,reason=email.eligibility(conn,message,True)
                result=dict(eligible_for_internal_review=valid,reason=reason,sending_authorised=False)
            elif job['kind']=='quote':
                result=quotes.calculate(payload['packages'],payload['gst_mode'],payload['requirements'],payload['requirements_source'],payload['proposal'])
                result['branding']=payload.get('branding','')
            elif job['kind']=='website':
                result=website_builder.build(conn,payload)
            else:
                result=write_local(job['kind'],payload)
            conn.execute('BEGIN IMMEDIATE')
            active=conn.execute("SELECT 1 FROM p5_jobs WHERE id=? AND status='Running' AND token=? AND lease_until>?",(job['id'],job['token'],time.time())).fetchone()
            if not active:
                conn.rollback();return True
            flow=conn.execute('SELECT * FROM p5_flows WHERE id=?',(job['flow_id'],)).fetchone()
            if flow['state']=='Cancelled':
                conn.execute("UPDATE p5_jobs SET status='Cancelled',result_json=?,lease_until=NULL,updated_at=? WHERE id=?",(store.dumps(result),stamp(),job['id']))
                store.log(conn,flow['user_id'],'Retained completed result after cancellation; no handoff or new draft.',flow['id'],job['id'])
                conn.commit();return True
            if job['kind'] in ('outreach','reply','proposal'):
                version=conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM p5_drafts WHERE flow_id=? AND kind=?',(flow['id'],job['kind'])).fetchone()[0]
                conn.execute('INSERT INTO p5_drafts(flow_id,job_id,kind,version,content_json,evidence_json,created_at) VALUES(?,?,?,?,?,?,?)',
                             (flow['id'],job['id'],job['kind'],version,store.dumps(result),store.dumps(payload.get('evidence',[])),stamp()))
                conn.execute('UPDATE p5_flows SET state=? WHERE id=?',(job['kind'].title()+' needs review',flow['id']))
            elif job['kind']=='research':
                conn.execute("UPDATE p5_flows SET state='Research needs review' WHERE id=?",(flow['id'],))
            elif job['kind']=='quote':
                version=conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM p5_quotes WHERE flow_id=?',(flow['id'],)).fetchone()[0]
                legacy=conn.execute('INSERT INTO quotes(lead_id,client_name,title,amount_cents,status,notes,created_at) VALUES(?,?,?,?,?,?,?)',
                    (flow['lead_id'],json.loads(flow['snapshot_json'])['lead']['business_name'],'Phase 5 draft v'+str(version),result['totals']['one-off']['total_cents'],'Draft',
                     'Phase 5 flow #'+str(flow['id'])+'. One-off AUD total only; recurring items and authoritative version are in Sales. Editable legacy status is not acceptance evidence.',stamp())).lastrowid
                quote_id=conn.execute('INSERT INTO p5_quotes(flow_id,version,content_json,content_hash,legacy_quote_id,created_at) VALUES(?,?,?,?,?,?)',
                             (flow['id'],version,store.dumps(result),store.digest(result),legacy,stamp())).lastrowid
                result['quote_id']=quote_id
                conn.execute("UPDATE p5_flows SET state='Quote needs review' WHERE id=?",(flow['id'],))
            elif job['kind']=='classify':
                if result['classification'] in ('opt-out','rejection'):
                    conn.execute("UPDATE p5_flows SET follow_state='Stopped after response' WHERE id=? AND follow_state!='Suppressed'",(flow['id'],))
                conn.execute("UPDATE p5_flows SET state='Reply interpretation needs review' WHERE id=?",(flow['id'],))
            elif job['kind']=='followup':
                conn.execute("UPDATE p5_followups SET status='Review due' WHERE message_id=? AND status!='Stopped'",(payload['message_id'],))
            elif job['kind']=='dispatch':
                conn.execute("UPDATE p5_flows SET state='Mock correspondence recorded; no real email' WHERE id=?",(flow['id'],))
            elif job['kind']=='website':
                site=conn.execute('SELECT * FROM p6_sites WHERE id=? AND owner_id=?',(payload['site_id'],job['user_id'])).fetchone()
                if not site or site['project_id']!=payload['project_id'] or site['brief_id']!=payload['brief_id']:
                    raise WorkflowError('Website task is not linked to the authorized owner project brief.')
                version=conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM p6_site_versions WHERE site_id=?',(site['id'],)).fetchone()[0]
                conn.execute("UPDATE p6_site_versions SET status='Superseded' WHERE site_id=? AND status='Needs review'",(site['id'],))
                conn.execute('''INSERT INTO p6_site_versions(site_id,version,theme,content_json,html,pages_json,qa_json,revision_note,status,created_at)
                    VALUES(?,?,?,?,?,?,?,?,'Needs review',?)''',(site['id'],version,result['theme'],store.dumps(result['content']),result['html'],store.dumps(result['pages']),store.dumps(result['qa']),result['content'].get('revision_note',''),stamp()))
                result=dict(site_id=site['id'],project_id=site['project_id'],version=version,qa=result['qa'])
                conn.execute("UPDATE p6_sites SET status='Needs review',active_version=? WHERE id=?",(version,site['id']))
            # Correspondence may arrive after a project brief was created. It must
            # not regress the accepted opportunity into an earlier sales stage.
            if flow['state']=='Project brief ready':
                conn.execute("UPDATE p5_flows SET state='Project brief ready' WHERE id=?",(flow['id'],))
            conn.execute('UPDATE p5_jobs SET status=?,result_json=?,lease_until=NULL,updated_at=? WHERE id=?',('Completed' if job['kind']=='dispatch' else 'Needs review',store.dumps(result),stamp(),job['id']))
            if job['mode']=='ai':
                conn.execute("UPDATE p5_ai_usage SET status='Response received; ceiling retained, not actual billing' WHERE job_id=?",(job['id'],))
            store.log(conn,job['user_id'],'Completed dispatch; mock receipt recorded, no real email.' if job['kind']=='dispatch' else 'Completed '+job['kind']+'; review required.',flow['id'],job['id'])
            conn.commit()
        except Exception as exc:
            conn.rollback()
            message=str(exc) if isinstance(exc,(WorkflowError,DraftError)) else 'Unexpected sales task failure. No invented output; inspect configuration and history.'
            if job['kind']=='website':
                conn.execute("UPDATE p6_sites SET status='Failed' WHERE id=? AND owner_id=?",(payload.get('site_id'),job['user_id']))
            conn.execute("UPDATE p5_jobs SET status='Failed',error=?,lease_until=NULL,updated_at=? WHERE id=? AND token=? AND status='Running'",(message,stamp(),job['id'],job['token']))
            store.log(conn,job['user_id'],message,job['flow_id'],job['id'])
            conn.commit()
        return True
    finally:
        conn.close()

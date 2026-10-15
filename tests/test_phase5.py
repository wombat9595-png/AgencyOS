"""Phase 5 contracts: fictional records and mocked transports only."""
from contextlib import closing
import hashlib
import hmac
import json
import os
import threading
import shutil
import sqlite3
import time
import unittest
from unittest.mock import patch
import app as application
import test_agencyos as baseline
from ai_drafts import DraftError, request_chat
from phase3_store import WorkflowError, connect, stamp
import sales_store as store
import sales_engine as engine
import sales_email as email
import sales_ai as ai
import sales_quotes as quotes

CONFIG=dict(AGENCYOS_AI_PROVIDER='openai-compatible',AGENCYOS_AI_API_KEY='synthetic-key',
            AGENCYOS_AI_ENDPOINT='https://provider.example/chat/completions',AGENCYOS_AI_MODEL='synthetic-model')
EVENT_SECRET='synthetic-event-secret-not-for-real-use-12345'


class SalesTest(unittest.TestCase):
    post=baseline.AgencyOSTest.post
    rows=baseline.AgencyOSTest.rows

    def setUp(self):
        baseline.AgencyOSTest.setUp(self)
        self.guard=patch('ai_drafts.request.build_opener',side_effect=AssertionError('Unmocked AI prohibited'))
        self.guard.start()
        self.env=patch.dict(os.environ,dict(AGENCYOS_EMAIL_EVENT_SECRET=EVENT_SECRET,AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE=''))
        self.env.start()
        self.post('/leads',dict(business_name='Fictional Studio',industry='Design',location='Sydney',website='https://studio.example/',email='prospect@example.com'))
        self.settings()
        self.package()

    def tearDown(self):
        self.env.stop();self.guard.stop();baseline.AgencyOSTest.tearDown(self)

    def sql(self,command,values=()):
        with closing(connect(application.DB_PATH)) as conn,conn:conn.execute(command,values)

    def settings(self,**changes):
        fields=dict(sender='owner@example.com',provider='mock',gst_mode='not_registered',daily_cents='0',daily_requests='0',input_rate='0',output_rate='0',pricing_model='')
        fields.update(changes)
        return self.post('/sales/settings',fields)

    def package(self,**changes):
        fields=dict(name='Fictional one-page package',category='one-page',price='100.05',cycle='one-off',scope='One responsive page; client supplies copy',exclusions='Hosting, domain, payments and publication')
        fields.update(changes)
        return self.post('/sales/packages',fields)

    def new(self,**changes):
        fields=dict(lead_id='1',package_ids=['1'],research_reference='new',tone='professional',mode='local',approve_lead='yes',synthetic='yes')
        fields.update(changes)
        return self.post('/sales/new',fields)

    def work(self):return engine.worker_once(application.DB_PATH)

    def outreach(self,**changes):
        response=self.new(**changes)
        self.assertEqual(response.status_code,302)
        self.work()
        research=self.rows('p5_jobs')[-1]
        self.assertEqual(self.post(f'/sales/jobs/{research["id"]}/decision',{'decision':'Approve research'}).status_code,302)
        self.work()
        return self.rows('p5_drafts')[-1]

    def prepare_message(self):
        draft=self.outreach()
        response=self.post(f'/sales/drafts/{draft["id"]}/approve',dict(recipient='prospect@example.com',confirm='yes'))
        self.assertEqual(response.status_code,302)
        return self.rows('p5_messages')[-1]

    def dispatch(self):
        item=self.prepare_message()
        self.assertEqual(self.post(f'/sales/messages/{item["id"]}/approve',dict(confirm='yes',mock_authorisation='yes')).status_code,302)
        self.work()
        return self.rows('p5_messages')[-1]

    def proposal_quote(self):
        self.prepare_message()
        response=self.post('/sales/1/proposal',dict(requirements='Fictional customer requested one service page',requirements_source='Synthetic fixture email — not a real customer',branding='Fixture blue brand',confirm='yes',mode='local'))
        self.assertEqual(response.status_code,302)
        self.work()
        proposal=self.rows('p5_drafts')[-1]
        self.assertEqual(self.post(f'/sales/drafts/{proposal["id"]}/approve',dict(confirm='yes')).status_code,302)
        self.work()
        return self.rows('p5_quotes')[-1]

    def approve_quote(self,quote):
        return self.post(f'/sales/quotes/{quote["id"]}/approve',dict(confirm='yes',recipient='prospect@example.com'))

    def accept(self,quote,**changes):
        fields=dict(customer_name='Fictional Customer',evidence='Synthetic acceptance of exact quote for tests only',evidence_source='Fictional fixture correspondence',quote_hash=quote['content_hash'],confirm='yes',confirm_project='yes')
        fields.update(changes)
        return self.post(f'/sales/quotes/{quote["id"]}/accept',fields)

    def signed_event(self,message,kind='reply',text='Could you explain the scope?',identifier='event-1',**changes):
        event=dict(timestamp=int(time.time()),event_id=identifier,provider_id=message['provider_id'],type=kind,text=text)
        event.update(changes)
        raw=json.dumps(event).encode()
        signature=hmac.new(EVENT_SECRET.encode(),raw,hashlib.sha256).hexdigest()
        response=self.client.post('/sales/events/mock',data=raw,content_type='application/json',headers={'X-AgencyOS-Signature':signature})
        response.close()
        return response

    def test_pages_authentication_and_csrf(self):
        self.assertEqual(self.client.get('/sales').status_code,200)
        self.assertEqual(self.client.post('/sales/new',data={}).status_code,400)
        self.assertEqual(self.client.get('/sales/999').status_code,404)
        self.post('/logout')
        self.assertEqual(self.client.get('/sales').status_code,302)

    def test_complete_local_workflow_and_acceptance_project_bridge(self):
        quote=self.proposal_quote()
        self.assertEqual(self.approve_quote(quote).status_code,302)
        self.assertEqual(self.accept(quote).status_code,302)
        self.assertEqual(len(self.rows('p5_acceptances')),1)
        self.assertEqual(len(self.rows('projects')),1)
        brief=json.loads(self.rows('p5_project_briefs')[0]['brief_json'])
        self.assertEqual(brief['quote_hash'],quote['content_hash'])
        self.assertEqual(brief['branding_references'],'Fixture blue brand')
        self.assertFalse(brief['publication_authorised'])
        self.assertFalse(brief['website_generation_authorised'])
        self.assertEqual(self.rows('quotes')[0]['status'],'Draft')
        self.assertIn('Owner-attested',self.rows('p5_acceptances')[0]['provenance'])
        self.assertEqual(self.accept(quote).status_code,400)
        self.assertEqual(len(self.rows('projects')),1)
        page=self.client.get('/sales/1')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Project #1 brief',page.data)
        self.assertEqual(len(self.rows('invoices')),0)

    def test_lead_research_approval_is_real_checkpoint_and_deduped(self):
        self.new()
        self.assertEqual(self.new().status_code,400)
        self.assertTrue(self.work())
        self.assertFalse(self.work())
        self.assertEqual(len(self.rows('p5_drafts')),0)
        self.assertEqual(self.post('/sales/jobs/1/decision',{'decision':'Approve research'}).status_code,302)
        self.assertEqual(self.post('/sales/jobs/1/decision',{'decision':'Approve research'}).status_code,409)
        self.assertTrue(self.work())
        self.assertEqual(len(self.rows('p5_drafts')),1)

    def test_approved_phase4_research_import_and_changed_lead_refusal(self):
        self.post('/agency/queue',dict(lead_id='1',kind='research'))
        import phase4
        phase4.worker_once(application.DB_PATH)
        self.post('/agency/jobs/1/decision',{'decision':'Approved'})
        self.assertEqual(self.new(research_reference='p4:1').status_code,302)
        self.assertEqual(self.rows('p5_jobs')[0]['kind'],'outreach')
        self.post('/sales/1/cancel')
        self.sql("UPDATE leads SET website='https://changed.example/'")
        self.assertEqual(self.new(research_reference='p4:1').status_code,400)

    def test_snapshot_preserves_original_lead_and_packages(self):
        self.new()
        self.sql("UPDATE leads SET business_name='Changed lead'")
        self.package(price='900',scope='Different scope')
        self.work();self.post('/sales/jobs/1/decision',{'decision':'Approve research'});self.work()
        content=json.loads(self.rows('p5_drafts')[0]['content_json'])
        self.assertIn('Fictional Studio',content['subject'])
        self.assertEqual(json.loads(self.rows('p5_flows')[0]['package_json'])[0]['price_cents'],10005)

    def test_local_evidence_quotes_only_reviewed_technical_findings(self):
        facts=dict(findings=[dict(detail='viewport was absent in this retrieved HTML document.',url='https://studio.example/')])
        self.sql('INSERT INTO p3_evidence(user_id,lead_id,source_url,observed_at,origin,facts_json) VALUES(?,?,?,?,?,?)',(1,1,'https://studio.example/',stamp(),'Approved technical audit',json.dumps(facts)))
        draft=self.outreach(evidence_ids=['1'])
        content=json.loads(draft['content_json'])
        self.assertIn('viewport was absent',content['body'])
        self.assertIn('reviewed technical observation',content['body'])
        self.assertNotIn('losing customers',content['body'])
        self.assertEqual(content['evidence_ids'],[1])

    def test_foreign_or_unapproved_evidence_cannot_be_selected(self):
        self.assertEqual(self.new(evidence_ids=['999']).status_code,400)
        self.assertEqual(len(self.rows('p5_flows')),0)

    def test_revisions_are_immutable_and_stale_approvals_blocked(self):
        draft=self.outreach()
        original=draft['content_json']
        self.assertEqual(self.post('/sales/1/revise',dict(kind='outreach',mode='local',tone='direct',reason='Owner edit',subject='Edited subject',body='Owner-supplied body')).status_code,302)
        self.assertEqual(self.post('/sales/drafts/1/approve',dict(recipient='prospect@example.com',confirm='yes')).status_code,400)
        self.work()
        self.assertEqual(self.rows('p5_drafts')[0]['content_json'],original)
        self.assertEqual(self.rows('p5_drafts')[1]['version'],2)
        self.assertEqual(json.loads(self.rows('p5_drafts')[1]['content_json'])['body'],'Owner-supplied body')
        self.assertEqual(self.post('/sales/drafts/1/approve',dict(recipient='prospect@example.com',confirm='yes')).status_code,409)

    def test_mock_dispatch_requires_two_approvals_and_is_not_delivery(self):
        item=self.prepare_message()
        self.assertFalse(self.work())
        self.assertEqual(self.post('/sales/messages/1/approve',{'confirm':'yes'}).status_code,400)
        self.assertEqual(self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes')).status_code,302)
        self.work()
        message=self.rows('p5_messages')[0]
        self.assertEqual(message['status'],'Mock accepted')
        self.assertTrue(message['provider_id'].startswith('mock:'))
        self.assertEqual(self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes')).status_code,400)

    def test_suppression_rechecked_after_approval_before_dispatch(self):
        self.prepare_message()
        self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes'))
        self.post('/sales/suppress',dict(email='PROSPECT@example.com',reason='Synthetic opt-out'))
        with patch('sales_email.MockEmailProvider.submit') as transport:
            self.work();transport.assert_not_called()
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Failed')

    def test_real_provider_and_nonfictional_workflow_cannot_send(self):
        self.prepare_message()
        self.settings(provider='ses-disabled')
        self.assertEqual(self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes')).status_code,400)
        self.settings()
        self.sql('UPDATE p5_flows SET synthetic=0')
        self.assertEqual(self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes')).status_code,400)

    def test_exact_content_and_sender_change_invalidates_dispatch(self):
        self.prepare_message()
        self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes'))
        self.sql("UPDATE p5_messages SET body='Changed after approval'")
        with patch('sales_email.MockEmailProvider.submit') as transport:
            self.work();transport.assert_not_called()
        self.assertIn('changed',self.rows('p5_jobs')[-1]['error'])

    def test_unknown_send_outcome_never_auto_retries(self):
        self.prepare_message();self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes'))
        with patch('sales_email.MockEmailProvider.submit',side_effect=TimeoutError):self.work()
        self.assertEqual(self.rows('p5_messages')[0]['status'],'Outcome unknown')
        self.assertEqual(self.post('/sales/jobs/3/decision',{'decision':'Retry local'}).status_code,409)
        self.assertFalse(self.work())

    def test_signed_reply_event_duplicate_protection_and_original(self):
        item=self.dispatch()
        first=self.signed_event(item)
        self.assertEqual(first.status_code,200)
        second=self.signed_event(item,timestamp=int(json.loads(self.rows('p5_events')[0]['original_json'])['timestamp']))
        self.assertEqual(second.status_code,200)
        self.assertFalse(second.json['created'])
        self.assertEqual(len(self.rows('p5_events')),1)
        self.assertEqual(self.signed_event(item,text='Different text').status_code,400)
        self.work()
        self.assertEqual(json.loads(self.rows('p5_jobs')[-1]['result_json'])['classification'],'question')
        self.assertIn('Could you explain',self.rows('p5_events')[0]['original_json'])

    def test_event_signature_timestamp_and_payload_validation(self):
        item=self.dispatch()
        self.assertEqual(self.client.post('/sales/events/mock',data=b'{}',headers={'X-AgencyOS-Signature':'bad'}).status_code,400)
        self.assertEqual(self.signed_event(item,timestamp=0).status_code,400)
        self.assertEqual(self.signed_event(item,provider_id='real:1').status_code,400)
        self.assertEqual(self.signed_event(item,kind='unknown').status_code,400)
        self.assertEqual(len(self.rows('p5_events')),0)

    def test_unsubscribe_and_complaints_suppress_and_do_not_revive(self):
        item=self.dispatch()
        self.assertEqual(self.signed_event(item,kind='unsubscribe',text='',identifier='u1').status_code,200)
        self.assertEqual(len(self.rows('p5_suppressions')),1)
        self.signed_event(item,kind='delivered',text='',identifier='d1')
        self.assertEqual(self.rows('p5_messages')[0]['status'],'Mock unsubscribe')
        self.assertEqual(self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes')).status_code,400)

    def test_reply_stops_schedule_and_hands_off_after_owner_review(self):
        item=self.dispatch()
        self.assertEqual(self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes')).status_code,302)
        self.signed_event(item)
        self.assertEqual(self.rows('p5_followups')[0]['status'],'Stopped')
        self.work()
        job=self.rows('p5_jobs')[-1]
        self.assertEqual(self.post(f'/sales/jobs/{job["id"]}/decision',{'decision':'Prepare reply'}).status_code,302)
        self.work()
        self.assertEqual(self.rows('p5_drafts')[-1]['kind'],'reply')
        self.assertEqual(self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes')).status_code,400)

    def test_owner_recorded_reply_is_not_provider_verification(self):
        self.prepare_message()
        self.assertEqual(self.post('/sales/messages/1/record',dict(kind='reply',text='Fictional: could you explain?',confirm='yes')).status_code,302)
        self.assertEqual(self.rows('p5_events')[0]['provider'],'owner-recorded')
        self.assertEqual(self.rows('p5_messages')[0]['status'],'Draft')

    def test_followup_review_executes_internal_task_not_email(self):
        self.dispatch()
        self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes'))
        self.sql('UPDATE p5_followups SET due_at=0')
        with patch('sales_email.MockEmailProvider.submit') as provider:
            self.work();provider.assert_not_called()
        result=json.loads(self.rows('p5_jobs')[-1]['result_json'])
        self.assertTrue(result['eligible_for_internal_review'])
        self.assertFalse(result['sending_authorised'])
        self.assertFalse(self.work())

    def test_pause_blocks_work_but_not_optouts_or_event_receipts(self):
        item=self.dispatch()
        self.post('/agency/pause',{'paused':'1'})
        self.assertFalse(self.work())
        self.assertEqual(self.new().status_code,400)
        self.assertEqual(self.signed_event(item,kind='unsubscribe',text='').status_code,200)
        self.assertEqual(len(self.rows('p5_suppressions')),1)
        self.post('/agency/pause',{'paused':'0'})

    def test_cancelled_workflow_does_not_run_or_generate_projects(self):
        self.new()
        self.post('/sales/1/cancel')
        self.assertFalse(self.work())
        self.assertEqual(self.rows('p5_jobs')[0]['status'],'Cancelled')
        self.assertEqual(len(self.rows('p5_drafts')),0)

    def test_independent_flows_concurrent_claims_same_flow_serialised(self):
        self.new()
        self.post('/leads',dict(business_name='Other Fictional',website='https://other.example/'))
        self.new(lead_id='2')
        with closing(connect(application.DB_PATH)) as conn,conn:
            store.enqueue(conn,1,'research',json.loads(self.rows('p5_jobs')[0]['payload_json']))
        claimed=[]
        def claim():
            with closing(connect(application.DB_PATH)) as conn:claimed.append(store.claim(conn))
        threads=[threading.Thread(target=claim) for _ in range(3)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(len([r for r in claimed if r]),2)
        self.assertEqual({r['flow_id'] for r in claimed if r},{1,2})

    def test_worker_recovery_local_retry_and_external_interruption(self):
        self.new()
        self.sql("UPDATE p5_jobs SET status='Running',token='expired',attempts=1,lease_until=0")
        self.assertFalse(self.work())
        self.assertEqual(self.rows('p5_jobs')[0]['status'],'Queued')
        self.sql("UPDATE p5_jobs SET status='Running',mode='ai',lease_until=0")
        self.assertFalse(self.work())
        self.assertEqual(self.rows('p5_jobs')[0]['status'],'Interrupted')

    def test_legacy_ai_routes_cannot_bypass_zero_budget(self):
        with patch.dict(os.environ,CONFIG):
            with self.assertRaisesRegex(DraftError,'Legacy direct AI'):
                request_chat('system','payload')
            page=self.post('/outreach',dict(lead_id='1',offer='Offer',tone='friendly',draft_mode='ai',approve_ai='yes'))
            self.assertIn(b'AI execution blocked',page.data)
        self.assertEqual(len(self.rows('p5_ai_usage')),0)

    def ai_job(self):
        self.new(mode='ai');self.work();self.post('/sales/jobs/1/decision',{'decision':'Approve research'})
        return self.rows('p5_jobs')[-1]

    def configure_ai(self):
        response=self.settings(daily_cents='100',daily_requests='2',input_rate='100',output_rate='200',pricing_model='synthetic-model',pricing_review='yes')
        self.assertEqual(response.status_code,302)

    def approve_ai(self,job):
        with closing(connect(application.DB_PATH)) as conn:
            hashed,cents=ai.approval(conn,job)
        return self.post(f'/sales/jobs/{job["id"]}/decision',dict(decision='Approve AI',confirm='yes',approval_hash=hashed,maximum_cents=str(cents)))

    def test_optional_ai_uses_one_approved_budgeted_mocked_request(self):
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.ai_job()
            self.assertEqual(self.approve_ai(job).status_code,302)
            with patch('ai_drafts.request.build_opener') as transport:
                response=transport.return_value.open.return_value.__enter__.return_value
                response.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps(dict(subject='Fictional proposal discussion',body='Would a discussion be useful?',evidence_ids=[]))}}]}).encode()
                self.work();self.assertEqual(transport.return_value.open.call_count,1)
            self.assertEqual(len(self.rows('p5_ai_usage')),1)
            self.assertGreater(self.rows('p5_ai_usage')[0]['reserved_cents'],0)
            self.assertEqual(len(self.rows('p5_drafts')),1)
            with self.assertRaises(DraftError):request_chat('another','request')

    def test_ai_changed_config_and_exhausted_budget_make_no_request(self):
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.ai_job();self.approve_ai(job)
            self.sql('UPDATE p5_control SET input_rate=input_rate+1')
            self.work()
            self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Failed')
            self.assertEqual(len(self.rows('p5_ai_usage')),0)

    def test_ai_invalid_evidence_response_retains_uncertain_cost(self):
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.ai_job();self.approve_ai(job)
            with patch('ai_drafts.request_chat',return_value=json.dumps(dict(subject='Unsupported',body='Claim',evidence_ids=[999]))):self.work()
            self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Failed')
            self.assertEqual(len(self.rows('p5_drafts')),0)
            self.assertEqual(len(self.rows('p5_ai_usage')),1)

    def test_expired_ai_approval_and_unknown_prices_block_execution(self):
        with patch.dict(os.environ,CONFIG):
            job=self.ai_job()
            self.assertEqual(self.post(f'/sales/jobs/{job["id"]}/decision',dict(decision='Approve AI',confirm='yes')).status_code,400)
            self.configure_ai();self.approve_ai(job)
            self.sql('UPDATE p5_jobs SET approval_expires=0 WHERE id=?',(job['id'],))
            self.work();self.assertEqual(len(self.rows('p5_ai_usage')),0)

    def test_quote_requires_explicit_gst_and_current_version(self):
        self.prepare_message();self.settings(gst_mode='unset')
        self.post('/sales/1/proposal',dict(requirements='Fixture scope',requirements_source='Fixture request',confirm='yes'))
        self.work()
        self.assertEqual(self.post('/sales/drafts/2/approve',{'confirm':'yes'}).status_code,400)
        self.assertEqual(len(self.rows('p5_quotes')),0)

    def test_acceptance_hash_and_legacy_status_cannot_create_project(self):
        quote=self.proposal_quote()
        self.post('/quotes/1/status',{'status':'Accepted'})
        self.assertEqual(len(self.rows('projects')),0)
        self.assertEqual(self.accept(quote).status_code,400)
        self.approve_quote(quote)
        self.assertEqual(self.accept(quote,quote_hash='wrong').status_code,400)
        self.assertEqual(self.accept(quote,evidence='').status_code,400)
        self.assertEqual(len(self.rows('projects')),0)

    def test_pending_quote_revision_blocks_old_acceptance(self):
        quote=self.proposal_quote();self.approve_quote(quote)
        self.post('/sales/1/revise',dict(kind='proposal',mode='local',tone='professional',reason='Scope review'))
        self.assertEqual(self.accept(quote).status_code,400)
        self.work()
        self.post('/sales/drafts/3/approve',{'confirm':'yes'})
        self.work()
        self.assertEqual(len(self.rows('p5_quotes')),2)
        self.assertEqual(self.accept(quote).status_code,400)

    def test_accepted_brief_uses_quote_snapshot_not_later_flow_mutation(self):
        quote=self.proposal_quote();self.approve_quote(quote)
        self.sql("UPDATE p5_flows SET requirements='Later changed text',branding='Later changed branding'")
        self.assertEqual(self.accept(quote).status_code,302)
        brief=json.loads(self.rows('p5_project_briefs')[0]['brief_json'])
        self.assertEqual(brief['requirements'],'Fictional customer requested one service page')
        self.assertEqual(brief['branding_references'],'Fixture blue brand')

    def test_late_correspondence_does_not_regress_accepted_project_stage(self):
        quote=self.proposal_quote();self.approve_quote(quote);self.accept(quote)
        self.post('/sales/messages/1/record',dict(kind='reply',text='Fictional later question?',confirm='yes'))
        self.work()
        self.assertEqual(self.rows('p5_flows')[0]['state'],'Project brief ready')
        self.assertEqual(len(self.rows('projects')),1)

    def test_unreviewed_proposal_cannot_bypass_accepted_scope_freeze(self):
        quote=self.proposal_quote();self.approve_quote(quote)
        self.post('/sales/1/revise',dict(kind='proposal',mode='local',tone='professional',reason='Alternative scope'))
        self.work()
        revision=self.rows('p5_drafts')[-1]
        self.assertEqual(self.accept(quote).status_code,400)
        self.post(f'/sales/drafts/{revision["id"]}/reject')
        self.assertEqual(self.accept(quote).status_code,302)
        self.assertEqual(self.post(f'/sales/drafts/{revision["id"]}/approve',dict(confirm='yes')).status_code,409)
        self.assertEqual(len(self.rows('projects')),1)

    def test_owner_isolation_and_repeatable_migrations(self):
        self.new()
        self.sql("INSERT INTO users(username,password_hash,created_at) VALUES('other','unused',?)",(stamp(),))
        self.sql('UPDATE p5_flows SET user_id=2')
        self.assertEqual(self.client.get('/sales/1').status_code,404)
        self.assertEqual(self.post('/sales/jobs/1/decision',{'decision':'Cancel'}).status_code,404)
        before=dict(self.rows('p5_flows')[0])
        application.init_db();application.init_db()
        self.assertEqual(dict(self.rows('p5_flows')[0]),before)
        self.assertEqual(len(self.rows('leads')),1)

    def test_queue_pressure_does_not_lose_optout_or_original(self):
        item=self.dispatch()
        for i in range(100):
            self.sql('INSERT INTO p5_jobs(flow_id,kind,mode,payload_json,status,dedupe_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                     (1,'research','local','{}','Queued','filler-'+str(i),stamp(),stamp()))
        self.assertEqual(self.signed_event(item,text='Please unsubscribe me').status_code,200)
        self.assertEqual(len(self.rows('p5_suppressions')),1)
        self.assertEqual(len(self.rows('p5_events')),1)

    def test_agent_disable_prevents_execution_and_choice_survives_migration(self):
        self.new()
        self.sql("UPDATE agents SET enabled=0 WHERE id='lead-research'")
        self.work()
        self.assertIn('disabled',self.rows('p5_jobs')[0]['error'])
        self.sql("UPDATE agents SET enabled=0 WHERE id='sales-replies'")
        application.init_db()
        self.assertEqual(next(r['enabled'] for r in self.rows('agents') if r['id']=='sales-replies'),0)

    def test_daily_ai_request_ceiling_stops_second_request(self):
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.ai_job();self.approve_ai(job)
            content=json.dumps(dict(subject='Fixture subject',body='Fixture body',evidence_ids=[]))
            with patch('ai_drafts.request_chat',return_value=content):self.work()
            self.sql('UPDATE p5_control SET daily_requests=1')
            self.post('/sales/1/revise',dict(kind='outreach',mode='ai',tone='professional',reason='Test request ceiling'))
            second=self.rows('p5_jobs')[-1];self.approve_ai(second)
            with patch('ai_drafts.request_chat') as provider:
                self.work();provider.assert_not_called()
            self.assertIn('ceiling',self.rows('p5_jobs')[-1]['error'])
            self.assertEqual(len(self.rows('p5_ai_usage')),1)

    def test_daily_ai_money_ceiling_stops_execution_before_transport(self):
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.ai_job();self.approve_ai(job)
            # A prior unresolved reservation exhausts the day without a live API call.
            self.sql('INSERT INTO p5_ai_usage(job_id,day,reserved_cents) VALUES(?,?,?)',(1,stamp()[:10],100))
            with patch('ai_drafts.request_chat') as provider:
                self.work();provider.assert_not_called()
            self.assertIn('ceiling',self.rows('p5_jobs')[-1]['error'])

    def test_expired_pricing_and_changed_approval_form_are_rejected(self):
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.ai_job()
            self.assertEqual(self.post(f'/sales/jobs/{job["id"]}/decision',dict(decision='Approve AI',confirm='yes',approval_hash='stale',maximum_cents='1')).status_code,400)
            self.sql('UPDATE p5_control SET pricing_expires=0')
            with closing(connect(application.DB_PATH)) as conn:
                with self.assertRaises(WorkflowError):ai.approval(conn,job)

    def test_legacy_queued_ai_also_reaches_shared_transport_block(self):
        with patch.dict(os.environ,CONFIG):
            response=self.post('/research',dict(lead_id='1',mode='ai'))
            self.post(response.location+'/approve',{'confirm':'yes'})
            from phase3 import worker_once
            worker_once(application.DB_PATH)
            self.assertIn('AI execution blocked',self.rows('p3_jobs')[-1]['error'])
        self.assertEqual(len(self.rows('p5_ai_usage')),0)

    def test_two_flows_cannot_contact_same_recipient_today(self):
        self.dispatch()
        self.post('/leads',dict(business_name='Different Fictional Branch',website='https://other.example/'))
        self.new(lead_id='2');self.work()
        job=self.rows('p5_jobs')[-1]
        self.post(f'/sales/jobs/{job["id"]}/decision',{'decision':'Approve research'});self.work()
        draft=self.rows('p5_drafts')[-1]
        self.post(f'/sales/drafts/{draft["id"]}/approve',dict(recipient='prospect@example.com',confirm='yes'))
        self.post('/sales/messages/2/approve',dict(confirm='yes',mock_authorisation='yes'))
        with patch('sales_email.MockEmailProvider.submit') as provider:
            self.work();provider.assert_not_called()
        self.assertIn('duplicate contact',self.rows('p5_jobs')[-1]['error'])

    def test_changed_sender_and_expired_exact_email_approval_block(self):
        self.prepare_message()
        self.post('/sales/messages/1/approve',dict(confirm='yes',mock_authorisation='yes'))
        self.sql('UPDATE p5_messages SET approval_expires=0')
        self.settings(sender='changed@example.com')
        with patch('sales_email.MockEmailProvider.submit') as provider:
            self.work();provider.assert_not_called()
        self.assertEqual(self.rows('p5_messages')[0]['status'],'Approved')

    def test_late_bounce_stops_followups_without_losing_original(self):
        item=self.dispatch()
        self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes'))
        self.signed_event(item,kind='bounce',text='Synthetic hard bounce')
        self.assertEqual(self.rows('p5_followups')[0]['status'],'Stopped')
        self.assertEqual(len(self.rows('p5_suppressions')),1)
        self.signed_event(item,kind='delivered',text='',identifier='late-delivery')
        self.assertEqual(self.rows('p5_messages')[0]['status'],'Mock bounce')

    def test_ai_interpretation_cannot_override_optout(self):
        item=self.dispatch()
        self.signed_event(item,text='Please unsubscribe me')
        self.work()
        classification=self.rows('p5_jobs')[-1]
        self.post(f'/sales/jobs/{classification["id"]}/interpret-ai')
        with patch.dict(os.environ,CONFIG):
            self.configure_ai();job=self.rows('p5_jobs')[-1];self.approve_ai(job)
            with patch('ai_drafts.request_chat',return_value=json.dumps(dict(classification='interest',reason='Synthetic wrong model response',evidence_ids=[]))):self.work()
        self.assertEqual(json.loads(self.rows('p5_jobs')[-1]['result_json'])['classification'],'opt-out')
        self.assertEqual(len(self.rows('p5_suppressions')),1)

    def test_cancellation_during_local_run_keeps_flow_cancelled(self):
        self.new()
        self.work();self.post('/sales/jobs/1/decision',{'decision':'Approve research'})
        original=engine.write_local
        def cancel_then_write(kind,payload):
            self.post('/sales/1/cancel')
            return original(kind,payload)
        with patch('sales_engine.write_local',side_effect=cancel_then_write):self.work()
        self.assertEqual(self.rows('p5_flows')[0]['state'],'Cancelled')
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Cancelled')
        self.assertEqual(len(self.rows('p5_drafts')),0)

    def test_stopped_internal_schedule_cannot_be_requeued_by_tick(self):
        self.dispatch();self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes'))
        self.sql('UPDATE p5_followups SET due_at=0')
        self.post('/sales/followups/1/stop')
        self.assertFalse(self.work())
        self.assertEqual(self.rows('p5_followups')[0]['status'],'Stopped')

    def test_phase4_copy_migration_preserves_synthetic_original_bytes(self):
        from pathlib import Path
        original_path=application.DB_PATH
        # Construct a synthetic Phase 4 schema by removing only our empty/new
        # Phase 5 test tables; never operate on a user/customer database.
        with closing(sqlite3.connect(original_path)) as conn:
            tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'p5_%'")]
            for table in tables:conn.execute('DROP TABLE '+table)
            conn.commit()
        original=Path(original_path).read_bytes()
        upgraded=str(Path(self.temp.name)/'upgrade-copy.db')
        shutil.copy2(original_path,upgraded)
        application.DB_PATH=upgraded
        try:
            application.init_db();application.init_db()
            self.assertEqual(len(self.rows('leads')),1)
            self.assertEqual(self.rows('leads')[0]['business_name'],'Fictional Studio')
            self.assertEqual(self.rows('p5_control')[0]['daily_cents'],0)
            self.assertEqual(Path(original_path).read_bytes(),original)
        finally:application.DB_PATH=original_path


class SalesRulesTest(unittest.TestCase):
    def test_quote_correspondence_is_readable_and_excludes_internal_source(self):
        package=dict(id=1,version=1,name='Fixture site',price_cents=10000,cycle='one-off',scope='One page',exclusions='Hosting')
        content=quotes.calculate([package],'not_registered','Customer requirements','Private internal provenance',{})
        body=quotes.render_quote(content,1)
        self.assertIn('one-off total: AUD 100.00',body)
        self.assertIn('monthly total: AUD 0.00',body)
        self.assertNotIn('Private internal provenance',body)

    def test_precise_gst_rounding_and_separate_recurring_totals(self):
        packages=[dict(id=1,version=1,name='One-off',price_cents=10005,cycle='one-off',scope='Scope',exclusions='Exclusions',quantity=2),
                  dict(id=2,version=1,name='Maintenance',price_cents=1005,cycle='monthly',scope='Scope',exclusions='Exclusions')]
        quote=quotes.calculate(packages,'registered_10','Requirements','Source',{})
        self.assertEqual(quote['totals']['one-off']['total_cents'],22011)
        self.assertEqual(quote['totals']['monthly']['total_cents'],1106)
        self.assertEqual(quote['totals']['monthly']['gst_cents'],101)
        for value in ('NaN','Infinity','-1','1.001','1000001'):
            with self.assertRaises(WorkflowError):quotes.money_input(value)
        with self.assertRaises(WorkflowError):quotes.calculate(packages,'unset','','',{})

    def test_conservative_reply_classification_and_uncertainty(self):
        for text,label in [('Please unsubscribe','opt-out'),('No thanks','rejection'),('What does it include?','question'),('I am interested','interest'),('Maybe later','uncertain'),('I am not interested','rejection')]:
            self.assertEqual(engine.classify(text)['classification'],label)
        self.assertNotEqual(engine.classify('Sounds good')['classification'],'accepted')

    def test_recipient_validation_no_header_injection(self):
        for value in ('Name <user@example.com>','user@example.com\r\nBcc:bad@example.com','invalid','user@localhost'):
            with self.assertRaises(WorkflowError):email.address(value)
        self.assertEqual(email.address('USER@EXAMPLE.COM'),'user@example.com')


if __name__=='__main__':unittest.main()

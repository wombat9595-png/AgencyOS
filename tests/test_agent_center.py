from contextlib import closing
import json
import os
import sqlite3
import time
import threading
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import app as application
from ai_drafts import DraftError
import test_agencyos as phase2a_tests

CONFIG = {'AGENCYOS_AI_PROVIDER': 'openai-compatible', 'AGENCYOS_AI_ENDPOINT': 'https://provider.example/chat/completions',
          'AGENCYOS_AI_MODEL': 'synthetic-model', 'AGENCYOS_AI_API_KEY': 'synthetic-key-not-a-real-credential'}

class AgentCenterTest(unittest.TestCase):
    post = phase2a_tests.AgencyOSTest.post
    rows = phase2a_tests.AgencyOSTest.rows

    def setUp(self):
        phase2a_tests.AgencyOSTest.setUp(self)
        self.network = patch('ai_drafts.request.build_opener', side_effect=AssertionError('Unmocked AI request prohibited in tests'))
        self.network.start()
        self.post('/leads', {'business_name': 'Synthetic Bakery', 'email': 'private@example.com', 'contact_name': 'Private Contact',
                             'website': 'https://example.com', 'industry': 'Bakery', 'location': 'Sydney', 'notes': 'Private notes'})

    def tearDown(self):
        self.network.stop()
        phase2a_tests.AgencyOSTest.tearDown(self)

    def create(self, mode='local', **overrides):
        fields = dict(agent_id='lead-research', lead_id='1', title='Synthetic analysis', mode=mode, instructions='Focus on enquiries')
        fields.update(overrides)
        return self.post('/agents/tasks/new', fields)

    def finish(self):
        response = self.create()
        self.post(response.location + '/run')
        self.post(response.location + '/review', {'decision': 'Approved'})
        return response.location

    def test_catalog_and_task_forms_render(self):
        page = self.client.get('/agents')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Lead Research Agent', page.data)
        self.assertIn(b'Website Builder Agent', page.data)
        self.assertIn(b'Not configured', page.data)
        self.assertEqual(self.client.get('/agents/tasks/new?lead_id=1').status_code, 200)
        self.assertIn(b'Research lead', self.client.get('/leads').data)
        self.assertIn(b'Agent Control Center', self.client.get('/').data)

    def test_local_lifecycle_and_snapshot_privacy(self):
        with patch('agent_center.ai_analysis') as ai:
            response = self.create()
            task = self.rows('agent_tasks')[0]
            self.assertEqual(task['status'], 'Queued')
            self.assertNotIn('private@example.com', task['snapshot_json'])
            self.assertNotIn('Private', task['snapshot_json'])
            self.assertNotIn('notes', task['snapshot_json'])
            self.assertEqual(task['result'], '')
            self.assertEqual(self.post(response.location + '/run').status_code, 302)
            self.assertFalse(ai.called)
        task = self.rows('agent_tasks')[0]
        self.assertEqual((task['status'],task['progress']), ('Awaiting review',100))
        self.assertIn('No website was fetched or inspected', task['result'])
        self.assertIn('Sydney', task['result'])
        self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertEqual(self.post(response.location + '/review', {'decision': 'Approved'}).status_code, 302)
        self.assertEqual(self.rows('agent_tasks')[0]['status'], 'Approved')
        self.assertEqual(self.post(response.location + '/run').status_code, 409)
        self.assertEqual(len(self.rows('agent_approvals')), 0)
        self.assertGreaterEqual(len(self.rows('agent_events')), 4)

    def test_ai_requires_explicit_owner_approval(self):
        with patch.dict(os.environ, CONFIG), patch('agent_center.ai_analysis', return_value='Suggestions only') as ai:
            response = self.create(mode='ai')
            self.assertEqual(self.rows('agent_tasks')[0]['status'], 'Awaiting AI approval')
            self.assertEqual(self.post(response.location + '/run').status_code, 409)
            self.assertEqual(self.post(response.location + '/approve-ai').status_code, 400)
            self.assertFalse(ai.called)
            approval_page = self.client.get(response.location)
            self.assertIn(b'synthetic-model', approval_page.data)
            self.assertNotIn(CONFIG['AGENCYOS_AI_API_KEY'].encode(), approval_page.data)
            self.assertEqual(self.post(response.location + '/approve-ai', {'confirm_ai':'yes'}).status_code,302)
            self.assertFalse(ai.called)
            self.assertEqual(self.post(response.location + '/run').status_code,302)
            self.assertEqual(ai.call_count, 1)
            self.assertEqual(self.post(response.location + '/run').status_code,409)
            self.assertEqual(self.post(response.location + '/approve-ai', {'confirm_ai':'yes'}).status_code,409)
            self.assertEqual(ai.call_count, 1)
            self.assertEqual(self.rows('agent_tasks')[0]['status'],'Awaiting review')
            self.assertIn('Owner approved one AI request', '\n'.join(r['message'] for r in self.rows('agent_events')))

    def test_ai_calls_shared_provider_with_minimal_data(self):
        with patch.dict(os.environ, CONFIG), patch('agent_center.request_chat', return_value='Suggested improvements') as model:
            response = self.create(mode='ai')
            self.post(response.location + '/approve-ai', {'confirm_ai':'yes'})
            self.post(response.location + '/run')
        args = model.call_args
        details = json.loads(args.args[1])
        self.assertEqual(set(details['lead']), {'business_name','website','industry','location'})
        self.assertIn('Do not claim to have visited a website', args.args[0])
        self.assertEqual(args.kwargs['max_tokens'], 900)
        self.assertNotIn('private@example.com', args.args[1])

    def test_missing_or_invalid_provider_blocks_approval(self):
        response = self.create(mode='ai')
        with patch.dict(os.environ, {}, clear=True), patch('agent_center.ai_analysis') as ai:
            result = self.post(response.location + '/approve-ai', {'confirm_ai':'yes'})
            self.assertEqual(result.status_code,400)
            self.assertIn(b'AI is not configured', result.data)
            self.assertFalse(ai.called)
        with patch.dict(os.environ, dict(CONFIG, AGENCYOS_AI_ENDPOINT='https://username:private-password@provider.example')):
            page = self.client.get(response.location)
            self.assertNotIn(b'private-password',page.data)
            self.assertEqual(self.post(response.location + '/approve-ai', {'confirm_ai':'yes'}).status_code,400)
        self.assertEqual(self.rows('agent_tasks')[0]['status'],'Awaiting AI approval')

    def test_provider_or_key_change_invalidates_approval(self):
        for field in ('AGENCYOS_AI_MODEL','AGENCYOS_AI_ENDPOINT','AGENCYOS_AI_API_KEY'):
            with patch.dict(os.environ,CONFIG), patch('agent_center.ai_analysis') as ai:
                response = self.create(mode='ai')
                self.post(response.location + '/approve-ai', {'confirm_ai':'yes'})
                with patch.dict(os.environ, {field: 'https://changed.example/chat/completions' if field.endswith('ENDPOINT') else 'changed'}):
                    self.assertEqual(self.post(response.location + '/run').status_code,302)
                self.assertFalse(ai.called)
                self.assertEqual(self.rows('agent_tasks')[-1]['status'],'Awaiting AI approval')

    def test_agent_disable_rename_and_reenable(self):
        response = self.create()
        result = self.post('/agents/lead-research/settings', {'name':'My Lead Assistant'})
        self.assertEqual(result.status_code,302)
        self.assertEqual(self.post(response.location + '/run').status_code,400)
        self.assertEqual(self.create().status_code,400)
        self.post('/agents/lead-research/settings', {'name':'My Lead Assistant','enabled':'yes'})
        self.assertEqual(self.post(response.location + '/run').status_code,302)
        self.assertIn(b'My Lead Assistant',self.client.get('/agents').data)
        self.assertEqual(self.post('/agents/website-builder/settings', {'name':'Builder','enabled':'yes'}).status_code,302)
        self.assertIn(b'Builder',self.client.get('/agents').data)
        self.assertEqual(self.post('/agents/unknown/settings', {'name':'Unknown'}).status_code,404)
        self.assertEqual(self.post('/agents/lead-research/settings', {'name':''}).status_code,400)

    def test_task_validation_and_future_agents_cannot_run(self):
        for overrides in ({'agent_id':'website-builder'},{'agent_id':'unknown'},{'lead_id':'999'},{'title':''},
                          {'title':'x'*121},{'instructions':'x'*1001},{'mode':'unrestricted'}):
            self.assertEqual(self.create(**overrides).status_code,400,overrides)
        self.assertEqual(len(self.rows('agent_tasks')),0)

    def test_cancel_reject_and_result_approval_do_not_execute_actions(self):
        for mode in ('local','ai'):
            response = self.create(mode=mode)
            self.assertEqual(self.post(response.location + '/cancel').status_code,302)
            self.assertEqual(self.post(response.location + '/run').status_code,409)
            self.assertEqual(self.post(response.location + '/cancel').status_code,409)
        response = self.create()
        self.post(response.location + '/run')
        self.post(response.location + '/review', {'decision':'Rejected'})
        self.assertEqual(self.rows('agent_tasks')[-1]['status'],'Rejected')
        self.assertEqual(self.post(response.location + '/review', {'decision':'Approved'}).status_code,409)
        self.assertEqual(self.post(response.location + '/action-requests', {'action_type':'email','description':'Send it'}).status_code,400)

    def test_sensitive_action_records_require_separate_decisions(self):
        location = self.finish()
        for action in ('email','spending','publishing'):
            self.assertEqual(self.post(location + '/action-requests', {'action_type':action,'description':'Synthetic exact proposal'}).status_code,302)
        approvals = self.rows('agent_approvals')
        self.assertTrue(all(row['status']=='Pending' for row in approvals))
        self.assertEqual(self.post('/agents/approvals/1/decide', {'decision':'Approved'}).status_code,302)
        self.assertEqual(self.post('/agents/approvals/2/decide', {'decision':'Rejected'}).status_code,302)
        self.assertEqual(self.post('/agents/approvals/1/decide', {'decision':'Rejected'}).status_code,409)
        self.assertEqual(self.post('/agents/approvals/3/decide', {'decision':'Run anyway'}).status_code,409)
        self.assertEqual(self.rows('agent_approvals')[0]['status'],'Approved')
        page = self.client.get(location)
        self.assertIn(b'Approval is recorded, not executed',page.data)
        self.assertNotIn('Executed', [row['status'] for row in self.rows('agent_approvals')])
        self.assertEqual(self.post(location + '/action-requests', {'action_type':'other','description':'Test'}).status_code,400)
        self.assertEqual(self.post(location + '/action-requests', {'action_type':'email','description':''}).status_code,400)
        self.assertEqual(self.post('/agents/approvals/999/decide', {'decision':'Approved'}).status_code,404)

    def test_task_owner_isolation_and_authentication(self):
        location = self.finish()
        self.post(location + '/action-requests', {'action_type':'email','description':'Synthetic proposal'})
        with self.client.session_transaction() as session:
            session['user_id'] = 999
        self.assertEqual(self.client.get(location).status_code,404)
        for suffix in ('run','approve-ai','review','cancel','recover','action-requests'):
            self.assertEqual(self.post(location+'/'+suffix).status_code,404)
        self.assertEqual(self.post('/agents/approvals/1/decide', {'decision':'Approved'}).status_code,404)
        self.assertNotIn(b'Synthetic analysis',self.client.get('/agents').data)
        self.post('/logout')
        self.assertEqual(self.client.get('/agents').status_code,302)
        self.assertEqual(self.client.get('/agents/tasks/new').status_code,302)
        self.assertEqual(self.post(location+'/run').status_code,302)

    def test_csrf_on_all_new_mutations(self):
        location = self.create().location
        for path in ('/agents/tasks/new','/agents/lead-research/settings',location+'/run',location+'/approve-ai',
                     location+'/review',location+'/cancel',location+'/recover',location+'/action-requests','/agents/approvals/1/decide'):
            self.assertEqual(self.client.post(path,data={}).status_code,400,path)

    def test_ai_failure_is_safe_and_never_automatically_retried(self):
        with patch.dict(os.environ,CONFIG), patch('agent_center.ai_analysis',side_effect=DraftError('AI provider could not be reached.')) as ai:
            location = self.create(mode='ai').location
            self.post(location+'/approve-ai', {'confirm_ai':'yes'})
            self.post(location+'/run')
            self.assertEqual(ai.call_count,1)
            self.assertEqual(self.rows('agent_tasks')[0]['status'],'Failed')
            self.assertIn('could not be reached',self.rows('agent_tasks')[0]['error'])
            self.assertEqual(self.post(location+'/run').status_code,409)
            self.assertEqual(ai.call_count,1)

    def test_unexpected_error_and_oversize_results_fail_closed(self):
        for failure in (RuntimeError('synthetic-private-secret'),None):
            with patch.dict(os.environ,CONFIG), patch('agent_center.ai_analysis',side_effect=failure,return_value='x'*12001):
                location = self.create(mode='ai').location
                self.post(location+'/approve-ai', {'confirm_ai':'yes'})
                self.post(location+'/run')
                task = self.rows('agent_tasks')[-1]
                self.assertEqual(task['status'],'Failed')
                self.assertNotIn('synthetic-private-secret',task['error'])
                self.assertEqual(task['result'],'')

    def test_interrupted_recovery_does_not_retry_a_paid_call(self):
        location = self.create().location
        self.assertEqual(self.post(location+'/recover').status_code,409)
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.execute("UPDATE agent_tasks SET status='Running',started_at=?",(time.time(),))
        self.assertEqual(self.post(location+'/recover').status_code,409)
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.execute('UPDATE agent_tasks SET started_at=?',(time.time()-121,))
        self.assertIn(b'Mark interrupted run',self.client.get(location).data)
        self.assertEqual(self.post(location+'/recover').status_code,302)
        self.assertEqual(self.rows('agent_tasks')[0]['status'],'Failed')
        self.assertEqual(self.post(location+'/run').status_code,409)

    def test_snapshot_survives_lead_change_and_deletion(self):
        location = self.create().location
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.execute("UPDATE leads SET business_name='Changed'")
        self.post('/leads/1/delete')
        task = self.rows('agent_tasks')[0]
        self.assertIsNone(task['lead_id'])
        self.post(location+'/run')
        self.assertIn('Synthetic Bakery',self.rows('agent_tasks')[0]['result'])
        self.assertEqual(len(self.rows('leads')),0)

    def test_migration_preserves_phase2a_data_and_agent_settings(self):
        self.post('/quotes', {'client_name':'Synthetic','title':'Site','amount':'100','lead_id':'1'})
        self.post('/invoices', {'client_name':'Synthetic','reference':'SYN-1','amount':'100'})
        self.post('/projects', {'client_name':'Synthetic','project_name':'Synthetic site'})
        location = self.finish()
        self.post('/agents/lead-research/settings', {'name':'Custom Research'})
        tables = ('users','leads','quotes','invoices','projects','lead_imports','agents','agent_tasks','agent_events','agent_approvals')
        before = {table:[tuple(r) for r in self.rows(table)] for table in tables}
        application.init_db();application.init_db()
        for table in tables:
            self.assertEqual([tuple(r) for r in self.rows(table)],before[table],table)
        self.assertEqual(self.client.get(location).status_code,200)

    def test_untrusted_fields_results_and_proposals_are_escaped(self):
        self.post('/leads', {'business_name':'<script>alert(1)</script>'})
        location = self.create(lead_id='2', instructions='<img src=x onerror=alert(1)>').location
        self.post(location+'/run')
        self.post(location+'/review', {'decision':'Approved'})
        self.post(location+'/action-requests', {'action_type':'email','description':'<script>alert(2)</script>'})
        page = self.client.get(location)
        self.assertNotIn(b'<script>alert',page.data)
        self.assertIn(b'&lt;script&gt;',page.data)
        self.assertNotIn(b'<img src=x',page.data)

    def test_task_filter_and_missing_website_suggestions(self):
        location = self.create().location
        self.post(location+'/run')
        page = self.client.get('/agents?status=Awaiting%20review')
        self.assertIn(b'Synthetic analysis',page.data)
        self.assertNotIn(b'Synthetic analysis',self.client.get('/agents?status=Cancelled').data)
        self.post('/leads', {'business_name':'No URL'})
        location = self.create(lead_id='2').location
        self.post(location+'/run')
        self.assertIn('Ask whether the business already has a website',self.rows('agent_tasks')[-1]['result'])

    def test_upgrade_from_phase2a_preserves_all_existing_records(self):
        self.post('/quotes', {'client_name':'Synthetic','title':'Legacy quote','amount':'200','lead_id':'1'})
        self.post('/invoices', {'client_name':'Synthetic','reference':'SYN-LEGACY','amount':'200'})
        self.post('/projects', {'client_name':'Synthetic','project_name':'Legacy synthetic site'})
        original_tables = ('users','leads','quotes','invoices','projects','lead_imports')
        before = {table:[tuple(row) for row in self.rows(table)] for table in original_tables}
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            for table in ('agent_approvals','agent_events','agent_tasks','agents'):
                conn.execute('DROP TABLE '+table)
        application.init_db()
        for table in original_tables:
            self.assertEqual([tuple(row) for row in self.rows(table)],before[table],table)
        self.assertEqual(len(self.rows('agents')),9)
        self.assertTrue({'sales-replies','sales-proposals'} <= {row['id'] for row in self.rows('agents')})
        self.assertEqual(self.client.get('/agents').status_code,200)

    def test_default_database_is_separate_and_session_key_is_private(self):
        environment = dict(os.environ, AGENCYOS_DB='', AGENCYOS_SECRET_KEY='')
        code = "import app,json; print(json.dumps([app.DB_PATH, len(app.app.secret_key)>=64 and app.app.secret_key!='change-this-before-deployment']))"
        result = subprocess.run([sys.executable,'-c',code],cwd=Path(application.APP_DIR),env=environment,
                                capture_output=True,text=True,check=True)
        path,private = json.loads(result.stdout)
        self.assertEqual(Path(path),Path(application.APP_DIR)/'.development'/'agencyos-phase5.db')
        self.assertTrue(private)

    def test_overlapping_ai_requests_make_only_one_model_call(self):
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def delayed_analysis(*_args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Synthetic test wait expired')
            return 'Synthetic recommendations'
        with patch.dict(os.environ,CONFIG), patch('agent_center.ai_analysis',side_effect=delayed_analysis) as model:
            location = self.create(mode='ai').location
            self.post(location+'/approve-ai', {'confirm_ai':'yes'})
            def first_request():
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session['user_id']=1
                    session['csrf_token']='thread-token'
                outcomes.append(client.post(location+'/run',data={'csrf_token':'thread-token'}).status_code)
            worker = threading.Thread(target=first_request)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.client.get(location).status_code,200)
                self.assertEqual(self.rows('agent_tasks')[0]['status'],'Running')
                self.assertEqual(self.post(location+'/run').status_code,409)
                self.assertEqual(self.post(location+'/cancel').status_code,409)
            finally:
                release.set()
                worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertEqual(outcomes,[302])
            self.assertEqual(model.call_count,1)
        self.assertEqual(self.rows('agent_tasks')[0]['status'],'Awaiting review')

    def test_repeat_run_during_running_state_is_blocked(self):
        location = self.create().location
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.execute("UPDATE agent_tasks SET status='Running',started_at=?",(time.time(),))
        with patch('agent_center.local_analysis') as local:
            self.assertEqual(self.post(location+'/run').status_code,409)
            self.assertFalse(local.called)

if __name__ == '__main__':
    unittest.main()

"""Regressions for reported Phase 5 MacBook issues; synthetic fixtures only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import shutil
import unittest
import test_phase5 as fixtures
import app as application
import runtime_status
from phase3_store import connect
from contextlib import closing


class ValidationRegression(unittest.TestCase):
    setUp=fixtures.SalesTest.setUp
    tearDown=fixtures.SalesTest.tearDown
    post=fixtures.SalesTest.post
    rows=fixtures.SalesTest.rows
    sql=fixtures.SalesTest.sql
    settings=fixtures.SalesTest.settings
    package=fixtures.SalesTest.package
    new=fixtures.SalesTest.new
    work=fixtures.SalesTest.work
    outreach=fixtures.SalesTest.outreach
    prepare_message=fixtures.SalesTest.prepare_message
    proposal_quote=fixtures.SalesTest.proposal_quote
    approve_quote=fixtures.SalesTest.approve_quote
    accept=fixtures.SalesTest.accept

    def test_relative_database_path_has_same_absolute_meaning_in_both_terminals(self):
        env=dict(os.environ,AGENCYOS_DB='.development/relative-validation.db',PYTHONPATH=application.APP_DIR)
        paths=[]
        for cwd in (application.APP_DIR,self.temp.name):
            result=subprocess.run([sys.executable,'-c','import app; print(app.DB_PATH)'],cwd=cwd,env=env,capture_output=True,text=True,check=True)
            paths.append(result.stdout.strip())
        self.assertEqual(paths,[str(Path(application.APP_DIR)/'.development/relative-validation.db')]*2)

    def test_duplicate_new_opportunity_reopens_existing_without_losing_work(self):
        first=self.new()
        second=self.new()
        self.assertEqual(first.status_code,302)
        self.assertEqual(second.status_code,302)
        self.assertEqual(second.location,first.location)
        self.assertEqual(len(self.rows('p5_flows')),1)
        self.assertEqual(len(self.rows('p5_jobs')),1)

    def test_missing_sender_error_links_to_configuration_and_preserves_draft(self):
        self.sql("UPDATE p5_control SET sender=''")
        draft=self.outreach()
        response=self.post(f'/sales/drafts/{draft["id"]}/approve',dict(recipient='prospect@example.com',confirm='yes'))
        self.assertEqual(response.status_code,400)
        self.assertIn(b'/sales#sales-settings',response.data)
        self.assertEqual(self.rows('p5_drafts')[0]['status'],'Needs review')
        self.assertEqual(len(self.rows('p5_messages')),0)

    def test_project_brief_includes_exact_recorded_acceptance_evidence(self):
        quote=self.proposal_quote();self.approve_quote(quote);self.accept(quote)
        brief=json.loads(self.rows('p5_project_briefs')[0]['brief_json'])
        acceptance=self.rows('p5_acceptances')[0]
        self.assertIn('acceptance',brief)
        self.assertEqual(brief['acceptance']['evidence'],acceptance['evidence'])
        self.assertEqual(brief['acceptance']['evidence_source'],acceptance['evidence_source'])
        self.assertEqual(brief['acceptance']['quote_hash'],quote['content_hash'])

    def test_legacy_brief_read_enriches_evidence_without_rewriting_saved_payload(self):
        quote=self.proposal_quote();self.approve_quote(quote);self.accept(quote)
        brief=json.loads(self.rows('p5_project_briefs')[0]['brief_json'])
        del brief['acceptance'];brief['schema_version']=1
        original=json.dumps(brief)
        self.sql('UPDATE p5_project_briefs SET brief_json=?',(original,))
        page=self.client.get('/sales/1')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Synthetic acceptance of exact quote for tests only',page.data)
        self.assertIn(b'stored_schema_version',page.data)
        self.assertEqual(self.rows('p5_project_briefs')[0]['brief_json'],original)

    def cli(self,*args):
        env=dict(os.environ,AGENCYOS_DB=application.DB_PATH,AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE='')
        return subprocess.run([sys.executable,'manage.py',*args],cwd=application.APP_DIR,env=env,capture_output=True,text=True,timeout=15)

    def test_wrong_queue_is_reproduced_and_diagnosed_without_claiming_other_work(self):
        self.post('/agency/queue',dict(lead_id='1',kind='research'))
        result=self.cli('worker','--phase5')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('belong to Phase 4',result.stdout)
        self.assertEqual(self.rows('p4_jobs')[0]['attempts'],0)
        self.assertEqual(self.rows('p4_jobs')[0]['status'],'Queued')
        correct=self.cli('worker','--phase4')
        self.assertEqual(correct.returncode,0,correct.stderr)
        self.assertEqual(self.rows('p4_jobs')[0]['attempts'],1)
        self.assertEqual(self.rows('p4_jobs')[0]['status'],'Awaiting review')

    def test_worker_on_different_database_cannot_be_mistaken_for_matching_worker(self):
        other=str(Path(self.temp.name)/'other database.db')
        shutil.copy2(application.DB_PATH,other)
        self.new()
        runtime_status.heartbeat(other,'other-worker','5')
        first=json.loads(self.cli('doctor','--phase5','--json').stdout)
        second=json.loads(self.cli('doctor','--phase5','--database',other,'--json').stdout)
        self.assertFalse(first['selected_worker_connected'])
        self.assertTrue(second['selected_worker_connected'])
        self.assertEqual(first['queues']['5']['Queued'],1)
        self.assertEqual(second['queues']['5'],{})
        self.assertNotEqual(first['database_path'],second['database_path'])

    def test_doctor_is_read_only_and_does_not_claim_or_migrate(self):
        self.new()
        before=Path(application.DB_PATH).read_bytes()
        result=self.cli('doctor','--phase5','--json')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['database_path'],application.DB_PATH)
        self.assertEqual(Path(application.DB_PATH).read_bytes(),before)
        self.assertEqual(self.rows('p5_jobs')[0]['attempts'],0)

    def test_watch_worker_claims_attempt_zero_job_and_records_shutdown(self):
        self.new()
        env=dict(os.environ,AGENCYOS_DB=application.DB_PATH,AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0')
        worker=subprocess.Popen([sys.executable,'manage.py','worker','--phase5','--watch'],cwd=application.APP_DIR,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if self.rows('p5_jobs')[0]['status']=='Needs review':break
                if worker.poll() is not None:self.fail('Watch worker exited before processing research')
                time.sleep(.05)
            self.assertEqual(self.rows('p5_jobs')[0]['attempts'],1)
            self.assertEqual(self.rows('p5_jobs')[0]['status'],'Needs review')
            with closing(connect(application.DB_PATH)) as conn:
                self.assertTrue(runtime_status.status(conn,application.DB_PATH)['selected_worker_connected'])
        finally:
            worker.terminate();out,err=worker.communicate(timeout=10)
        self.assertEqual(worker.returncode,0,(out,err))
        self.assertIn(application.DB_PATH,out)
        with closing(connect(application.DB_PATH)) as conn:
            self.assertFalse(runtime_status.status(conn,application.DB_PATH)['selected_worker_connected'])

    def test_stale_worker_heartbeat_is_not_reported_as_connected(self):
        runtime_status.heartbeat(application.DB_PATH,'stale','5')
        self.sql('UPDATE runtime_workers SET last_seen=0')
        with closing(connect(application.DB_PATH)) as conn:
            self.assertFalse(runtime_status.status(conn,application.DB_PATH)['selected_worker_connected'])

    def test_runtime_and_navigation_show_matching_phase_and_existing_links(self):
        self.new()
        sales=self.client.get('/sales').data
        self.assertIn(b'id="existing-opportunities"',sales)
        self.assertIn(b'existing opportunity #1',sales)
        self.assertIn(b'--phase5',sales)
        self.assertIn(b'--phase4',self.client.get('/agency').data)
        self.assertIn(b'Draft reviews',self.client.get('/sales/1').data)

    def test_invalid_sender_is_rejected_without_corrupting_configuration(self):
        before=dict(self.rows('p5_control')[0])
        self.assertEqual(self.settings(sender='Bad Sender <owner@example.com>').status_code,400)
        self.assertEqual(dict(self.rows('p5_control')[0]),before)

    def test_all_local_tones_generate_distinct_personalised_drafts(self):
        draft=self.outreach(tone='professional')
        bodies=[json.loads(draft['content_json'])['body']]
        for tone in ('friendly','direct'):
            self.post('/sales/1/revise',dict(kind='outreach',mode='local',tone=tone,reason='Validation of tone'))
            self.work()
            current=json.loads(self.rows('p5_drafts')[-1]['content_json'])
            self.assertIn('Fictional Studio',current['subject'])
            self.assertIn('Fictional one-page package',current['body'])
            bodies.append(current['body'])
        self.assertEqual(len(set(bodies)),3)

    def test_one_multi_custom_and_recurring_package_quantities(self):
        self.package(name='Fictional multi-page',category='multi-page',price='200.00')
        self.package(name='Fictional custom',category='custom',price='300.00')
        self.package(name='Fictional maintenance',category='maintenance',price='10.05',cycle='monthly')
        self.settings(gst_mode='registered_10')
        self.new(package_ids=['1','2','3','4'],quantity_2='2')
        self.work();self.post('/sales/jobs/1/decision',{'decision':'Approve research'});self.work()
        self.post('/sales/drafts/1/approve',dict(recipient='prospect@example.com',confirm='yes'))
        self.post('/sales/1/proposal',dict(requirements='Fictional scoped package test',requirements_source='Synthetic test only',branding='Fictional colours',confirm='yes',mode='local'))
        self.work();self.post('/sales/drafts/2/approve',{'confirm':'yes'});self.work()
        quote=json.loads(self.rows('p5_quotes')[0]['content_json'])
        self.assertEqual(len(quote['items']),4)
        self.assertEqual(quote['totals']['one-off']['total_cents'],88006)
        self.assertEqual(quote['totals']['monthly']['total_cents'],1106)

    def test_complaint_and_rejection_cancel_ineligible_followups(self):
        item=fixtures.SalesTest.dispatch(self)
        self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes'))
        response=fixtures.SalesTest.signed_event(self,item,kind='complaint',text='Fictional complaint')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.rows('p5_followups')[0]['status'],'Stopped')
        self.assertEqual(len(self.rows('p5_suppressions')),1)

    def test_signed_mock_delivery_is_distinct_from_acceptance_and_deduplicated(self):
        item=fixtures.SalesTest.dispatch(self)
        original_time=int(time.time())
        for _ in range(2):
            response=fixtures.SalesTest.signed_event(self,item,kind='delivered',text='',timestamp=original_time)
            self.assertEqual(response.status_code,200)
        self.assertEqual(self.rows('p5_messages')[0]['status'],'Mock delivered')
        self.assertEqual(len(self.rows('p5_events')),1)
        self.assertEqual(len(self.rows('p5_acceptances')),0)

    def test_rejected_reply_stops_followup_and_cannot_invent_agreement(self):
        item=fixtures.SalesTest.dispatch(self)
        self.post('/sales/messages/1/followup',dict(hours='1',confirm='yes'))
        fixtures.SalesTest.signed_event(self,item,text='No thanks, not interested')
        self.work()
        job=self.rows('p5_jobs')[-1]
        self.assertEqual(json.loads(job['result_json'])['classification'],'rejection')
        self.assertEqual(self.rows('p5_followups')[0]['status'],'Stopped')
        self.assertEqual(self.post(f'/sales/jobs/{job["id"]}/decision',{'decision':'Prepare reply'}).status_code,400)
        self.assertEqual(len(self.rows('p5_acceptances')),0)
        self.assertEqual(len(self.rows('projects')),0)

    def test_actual_killed_worker_recovers_one_local_draft_after_lease_expiry(self):
        self.new();self.work();self.post('/sales/jobs/1/decision',{'decision':'Approve research'})
        marker=str(Path(self.temp.name)/'claimed-marker')
        code="""import time
from pathlib import Path
import sales_engine, app
def blocked(kind,payload):
    Path(MARKER).write_text('claimed')
    while True: time.sleep(.05)
sales_engine.write_local=blocked
sales_engine.worker_once(app.DB_PATH)
""".replace('MARKER',repr(marker))
        env=dict(os.environ,AGENCYOS_DB=application.DB_PATH,AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0')
        worker=subprocess.Popen([sys.executable,'-c',code],cwd=application.APP_DIR,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+10
            while not Path(marker).exists() and time.monotonic()<deadline:
                if worker.poll() is not None:self.fail('Instrumented worker exited before its claim')
                time.sleep(.05)
            self.assertTrue(Path(marker).exists())
            worker.kill();worker.communicate(timeout=10)
        finally:
            if worker.poll() is None:worker.kill();worker.communicate(timeout=10)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Running')
        self.assertEqual(len(self.rows('p5_drafts')),0)
        self.sql("UPDATE p5_jobs SET lease_until=0 WHERE status='Running'")
        self.assertEqual(self.cli('worker','--phase5').returncode,0)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Queued')
        self.sql("UPDATE p5_jobs SET not_before=0 WHERE status='Queued'")
        self.assertEqual(self.cli('worker','--phase5').returncode,0)
        self.assertEqual(len(self.rows('p5_drafts')),1)
        self.assertEqual(self.rows('p5_jobs')[-1]['attempts'],2)

    def test_draft_and_quote_reviews_synchronise_originating_task_status(self):
        quote=self.proposal_quote()
        drafts=self.rows('p5_drafts')
        jobs={r['id']:r for r in self.rows('p5_jobs')}
        self.assertTrue(all(jobs[d['job_id']]['status']=='Approved' for d in drafts))
        self.approve_quote(quote)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Approved')

    def test_rejected_draft_marks_job_rejected_without_new_handoff(self):
        draft=self.outreach()
        self.post(f'/sales/drafts/{draft["id"]}/reject')
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Rejected')
        self.assertEqual(len(self.rows('p5_messages')),0)

    def test_completed_mock_dispatch_and_stopped_response_have_clear_statuses(self):
        item=fixtures.SalesTest.dispatch(self)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Completed')
        fixtures.SalesTest.signed_event(self,item,text='Please unsubscribe')
        self.work()
        job=self.rows('p5_jobs')[-1]
        self.assertEqual(self.post(f'/sales/jobs/{job["id"]}/decision',{'decision':'Acknowledge result'}).status_code,302)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Approved')
        self.assertEqual(len(self.rows('p5_acceptances')),0)


if __name__=='__main__':unittest.main()

"""Synthetic-only contracts for Phase 4. No live businesses or paid APIs."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
import app as application
import test_agencyos as baseline
import phase4
import phase4_store as store
import phase4_data as data
import website_audit as audit
from phase3_store import WorkflowError, connect, stamp


def csv_data(identity='synthetic-1', name='Fictional Studio', state='NSW'):
    return ('source_id,source_url,observed_at,business_name,state,city,industry,website,email\n'
            f'{identity},https://source.example/records/1,2020-01-01T00:00:00+00:00,{name},{state},Sydney,Design,https://studio.example/,\n').encode()


class Phase4Test(unittest.TestCase):
    post = baseline.AgencyOSTest.post
    rows = baseline.AgencyOSTest.rows

    def setUp(self):
        baseline.AgencyOSTest.setUp(self)
        self.guard = patch('website_audit.public_get', side_effect=AssertionError('Unmocked network prohibited'))
        self.guard.start()
        self.env = patch.dict(os.environ, {'AGENCYOS_WEBSITE_FETCH':'0','AGENCYOS_OSM_POLICY_FILE':''})
        self.env.start()
        self.post('/leads',dict(business_name='Fictional Local',industry='Design',website='https://local.example/',location='Sydney, NSW'))

    def tearDown(self):
        self.env.stop()
        self.guard.stop()
        baseline.AgencyOSTest.tearDown(self)

    def sql(self, command, values=()):
        with closing(connect(application.DB_PATH)) as conn, conn:
            conn.execute(command, values)

    def stage(self, body=None):
        return self.post('/discovery/licensed',dict(dataset=(io.BytesIO(body or csv_data()),'fictional.csv'),name='Synthetic licensed fixture',
            licence_url='https://source.example/licence',permitted_use='Synthetic test use only',attribution='Fictional data',reviewer='Synthetic operator',review_days='30',confirm='yes'),content_type='multipart/form-data')

    def queue(self, kind='qualification', **kwargs):
        return self.post('/agency/queue',dict(lead_id='1',kind=kind,**kwargs))

    def work(self):
        return phase4.worker_once(application.DB_PATH)

    def decide(self, location, decision, **kwargs):
        return self.post(location+'/decision',dict(decision=decision,**kwargs))

    def test_pages_auth_csrf_and_unknown_jobs(self):
        for path in ('/agency','/discovery/licensed'):
            self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.client.post('/agency/pause',data={'paused':'1'}).status_code,400)
        self.assertEqual(self.client.get('/agency/jobs/999').status_code,404)
        self.post('/logout')
        self.assertEqual(self.client.get('/agency').status_code,302)
        self.assertEqual(self.client.get('/discovery/licensed').status_code,302)

    def test_immutable_local_handoff_runs_real_work_once(self):
        location=self.queue(handoff='yes').location
        self.sql("UPDATE leads SET business_name='Changed after enqueue'")
        self.assertTrue(self.work())
        job=self.rows('p4_jobs')[0]
        result=json.loads(job['result_json'])
        self.assertEqual(result['snapshot']['lead']['business_name'],'Fictional Local')
        self.assertEqual(result['score'],20)
        self.assertEqual(len(self.rows('p4_jobs')),2)
        self.assertTrue(self.work())
        self.assertFalse(self.work())
        child=self.rows('p4_jobs')[1]
        self.assertEqual(child['parent_id'],job['id'])
        self.assertIn('no AI provider',json.loads(child['result_json'])['classification'])
        self.assertEqual(self.decide(location,'Approved').status_code,302)
        self.assertEqual(self.decide(location,'Approved').status_code,409)
        self.assertEqual(sum(r['actual_cents'] for r in self.rows('p4_budget')),0)

    def test_pause_blocks_phase4_legacy_claims_and_mutations(self):
        self.queue()
        self.post('/research',dict(lead_id='1',mode='local'))
        self.assertEqual(self.post('/agency/pause',{'paused':'1'}).status_code,302)
        self.assertFalse(self.work())
        from phase3 import worker_once
        self.assertFalse(worker_once(application.DB_PATH))
        self.assertEqual(self.queue().status_code,400)
        self.assertEqual(self.post('/invoices',dict(client_name='Forbidden',reference='No',amount='10')).status_code,400)
        self.assertEqual(self.client.get('/agency').status_code,200)
        self.post('/agency/pause',{'paused':'0'})
        self.assertTrue(self.work())

    def test_only_supported_local_and_audit_handlers(self):
        self.assertEqual(self.queue('email').status_code,400)
        self.assertEqual(self.queue('paid-ai').status_code,400)
        self.assertEqual(self.post('/agency/budget',{'daily_budget_cents':'1'}).status_code,400)
        self.assertEqual(self.post('/agency/budget',{'daily_budget_cents':'0'}).status_code,302)

    def test_budget_reservation_is_atomic_and_conservative(self):
        self.queue()
        self.queue()
        with closing(connect(application.DB_PATH)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE p4_control SET daily_budget_cents=50')
            store.reserve_budget(conn,1,50)
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            store.reserve_budget(conn,1,50)
            with self.assertRaises(WorkflowError):store.reserve_budget(conn,2,1)
            with self.assertRaises(WorkflowError):store.reserve_budget(conn,1,20)
            with self.assertRaises(WorkflowError):store.reserve_budget(conn,2,-1)
            conn.rollback()
        self.assertEqual(self.rows('p4_budget')[0]['reserved_cents'],50)
        self.assertIsNone(self.rows('p4_budget')[0]['actual_cents'])

    def test_concurrent_workers_claim_once(self):
        self.queue()
        claims=[]
        def claim():
            with closing(connect(application.DB_PATH)) as conn:
                claims.append(store.claim(conn))
        workers=[threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        self.assertEqual(sum(c is not None for c in claims),1)
        self.assertEqual(self.rows('p4_jobs')[0]['attempts'],1)

    def test_recovery_retries_local_only_and_caps_attempts(self):
        self.queue()
        self.queue('audit',permission='yes')
        self.sql("UPDATE p4_jobs SET status='Running',lease_until=0,attempts=1")
        self.assertFalse(self.work())
        self.assertEqual([r['status'] for r in self.rows('p4_jobs')],['Queued','Interrupted'])
        self.sql("UPDATE p4_jobs SET status='Running',lease_until=0,attempts=3 WHERE id=1")
        self.assertFalse(self.work())
        self.assertEqual(self.rows('p4_jobs')[0]['status'],'Interrupted')

    def test_schedule_runs_with_browser_closed_no_external_calls(self):
        response=self.post('/agency/schedules',dict(lead_id='1',hours='24',confirm='yes'))
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.work())
        self.assertTrue(self.work())
        self.assertFalse(self.work())
        self.assertEqual(len(self.rows('p4_jobs')),2)
        self.assertEqual(self.post('/agency/schedules/1/stop').status_code,302)
        self.assertFalse(self.rows('p4_schedules')[0]['enabled'])
        self.assertEqual(self.post('/agency/schedules',dict(lead_id='1',hours='0',confirm='yes')).status_code,400)

    def test_schedule_catchup_does_not_flood_queue(self):
        self.post('/agency/schedules',dict(lead_id='1',hours='1',confirm='yes'))
        self.sql('UPDATE p4_schedules SET next_run=0')
        with closing(connect(application.DB_PATH)) as conn:
            self.assertEqual(store.schedule_tick(conn,data.snapshot),1)
            self.assertEqual(store.schedule_tick(conn,data.snapshot),0)
        self.assertEqual(len(self.rows('p4_jobs')),1)

    def test_licensed_intake_provenance_filters_and_qualification(self):
        self.assertEqual(self.stage().status_code,302)
        self.assertEqual(self.client.get('/discovery/licensed?state=VIC').data.count(b'<h2>Fictional Studio'),0)
        page=self.client.get('/discovery/licensed?state=NSW&city=sydney&industry=design')
        self.assertIn(b'Fictional Studio',page.data)
        self.assertEqual(self.post('/discovery/licensed/1/import',{'confirm':'yes'}).status_code,302)
        self.assertEqual(self.post('/discovery/licensed/1/import',{'confirm':'yes'}).status_code,409)
        evidence=self.rows('p3_evidence')[0]
        self.assertEqual(evidence['origin'],'Licensed directory')
        self.assertTrue(evidence['observed_at'].startswith('2020-01-01'))
        self.assertEqual(self.rows('leads')[1]['email'],'')
        self.assertEqual(self.post('/agency/queue',dict(lead_id='2',kind='qualification')).status_code,302)
        self.work()
        self.assertEqual(json.loads(self.rows('p4_jobs')[0]['result_json'])['score'],70)
        self.assertIn(b'Licensed directory',self.client.get('/research?lead_id=2').data)

    def test_deduplication_across_separate_imports_and_old_crm(self):
        self.stage()
        self.post('/discovery/licensed/1/import',{'confirm':'yes'})
        self.stage(csv_data('different-source-id'))
        self.assertEqual(self.post('/discovery/licensed/2/import',{'confirm':'yes'}).status_code,400)
        self.assertEqual(len(self.rows('leads')),2)
        self.stage(csv_data('third','Fictional Local'))
        self.assertEqual(self.post('/discovery/licensed/3/import',{'confirm':'yes'}).status_code,400)

    def test_expired_permission_prevents_import(self):
        self.stage()
        self.sql("UPDATE p4_sources SET expires_at='2000-01-01T00:00:00+00:00'")
        self.assertEqual(self.post('/discovery/licensed/1/import',{'confirm':'yes'}).status_code,400)
        self.assertEqual(len(self.rows('leads')),1)

    def test_location_schedule_queries_licensed_imports_without_network(self):
        self.stage()
        response=self.post('/discovery/licensed/schedule',dict(state='NSW',city='Sydney',industry='Design',hours='24',maximum='5',confirm='yes'))
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.work())
        result=json.loads(self.rows('p4_jobs')[0]['result_json'])
        self.assertEqual(result['candidates'][0]['data']['business_name'],'Fictional Studio')
        self.assertEqual(len(self.rows('leads')),1)
        self.assertFalse(self.work())
        self.assertEqual(self.post('/discovery/licensed/schedules/1/stop').status_code,302)
        self.assertEqual(self.rows('p4_search_schedules')[0]['enabled'],0)

    def test_expired_records_excluded_from_scheduled_discovery(self):
        self.stage()
        self.post('/discovery/licensed/schedule',dict(state='NSW',city='Sydney',industry='',hours='1',maximum='5',confirm='yes'))
        self.sql("UPDATE p4_sources SET expires_at='2000-01-01T00:00:00+00:00'")
        self.assertTrue(self.work())
        self.assertEqual(json.loads(self.rows('p4_jobs')[0]['result_json'])['candidates'],[])
        self.assertEqual(self.post('/discovery/licensed/schedule',dict(state='NSW',city='Sydney',hours='1',maximum='5',confirm='yes')).status_code,400)

    def test_duplicate_source_identity_collapsed_in_offline_search(self):
        self.stage()
        self.stage()
        with closing(connect(application.DB_PATH)) as conn:
            snapshot=data.search_snapshot(conn,1,'NSW','Sydney','Design',10)
        self.assertEqual(len(snapshot['candidates']),1)

    def test_audit_requests_respect_global_usage_and_pause(self):
        location=self.queue('audit',permission='yes').location
        def run(url,before_request):
            before_request()
            self.sql('UPDATE p4_control SET paused=1')
            before_request()
            raise AssertionError('Pause should prevent further work')
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('website_audit.audit',side_effect=run):
            self.decide(location,'Queue audit',confirm='yes')
            self.work()
        self.assertEqual(self.rows('p4_jobs')[0]['status'],'Failed')
        self.assertIn('Emergency pause',self.rows('p4_jobs')[0]['error'])
        usage=next(r for r in self.rows('p3_usage') if r['service']=='p4-audit-requests')
        self.assertEqual(usage['calls'],1)

    def test_reject_invalid_source_data_without_partial_import(self):
        for body in (csv_data(state='US'),csv_data().replace(b'https://source.example/records/1',b'javascript:bad'),csv_data().replace(b'2020-01-01T00:00:00+00:00',b'2999-01-01T00:00:00+00:00'),b'business_name\nFake\n'):
            self.assertEqual(self.stage(body).status_code,400)
        self.assertEqual(len(self.rows('p4_sources')),0)

    def test_unknown_website_does_not_become_no_website_claim(self):
        self.sql("UPDATE leads SET website=''")
        self.queue()
        self.work()
        result=json.loads(self.rows('p4_jobs')[0]['result_json'])
        self.assertIn('does not prove',result['website_status'])

    def test_audit_gate_expiry_and_changed_payload(self):
        location=self.queue('audit',permission='yes').location
        self.assertEqual(self.decide(location,'Queue audit',confirm='yes').status_code,400)
        self.assertFalse(self.work())
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}):
            self.assertEqual(self.decide(location,'Queue audit',confirm='yes').status_code,302)
            self.sql('UPDATE p4_jobs SET approval_expires=0')
            self.work()
            self.assertEqual(self.rows('p4_jobs')[0]['status'],'Awaiting approval')
            self.decide(location,'Queue audit',confirm='yes')
            self.sql("UPDATE p4_jobs SET payload_json=replace(payload_json,'local.example','changed.example')")
            self.work()
            self.assertEqual(self.rows('p4_jobs')[0]['status'],'Awaiting approval')

    def test_audit_results_need_review_before_research(self):
        location=self.queue('audit',permission='yes').location
        report=dict(url='https://local.example/',observed_at=stamp(),findings=[dict(code='missing-title',detail='Absent',url='https://local.example/')],observations=[],recommendations=[],unchecked=[],pages=[],requests=2,limitations='Synthetic fixture')
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('website_audit.audit',return_value=report) as provider:
            self.decide(location,'Queue audit',confirm='yes')
            self.work()
            provider.assert_called_once()
        self.assertEqual(len(self.rows('p3_evidence')),0)
        self.assertIn(b'Verified technical findings',self.client.get(location).data)
        self.assertEqual(self.decide(location,'Approved').status_code,302)
        self.assertEqual(len(self.rows('p3_evidence')),1)
        self.assertIn(b'Approved technical audit',self.client.get('/research?lead_id=1').data)
        self.queue()
        self.work()
        self.assertEqual(json.loads(self.rows('p4_jobs')[1]['result_json'])['score'],50)
        self.sql("UPDATE leads SET website='https://changed.example/'")
        self.queue()
        self.work()
        self.assertEqual(json.loads(self.rows('p4_jobs')[2]['result_json'])['score'],20)

    def test_disabled_audit_agent_and_failed_requests_have_no_fake_output(self):
        location=self.queue('audit',permission='yes').location
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}):
            self.decide(location,'Queue audit',confirm='yes')
            self.sql("UPDATE agents SET enabled=0 WHERE id='website-audit'")
            self.work()
        self.assertEqual(self.rows('p4_jobs')[0]['status'],'Failed')
        self.assertEqual(self.rows('p4_jobs')[0]['result_json'],'')
        self.assertEqual(self.decide(location,'Retry local').status_code,409)

    def test_job_and_candidate_owner_isolation_and_escaping(self):
        location=self.queue().location
        self.stage(csv_data(name='<script>bad</script>'))
        self.assertIn(b'&lt;script&gt;',self.client.get('/discovery/licensed').data)
        self.sql("INSERT INTO users(username,password_hash,created_at) VALUES('other','unused',?)",(stamp(),))
        self.sql('UPDATE p4_jobs SET user_id=2')
        self.sql('UPDATE p4_candidates SET user_id=2')
        self.assertEqual(self.client.get(location).status_code,404)
        self.assertEqual(self.post('/discovery/licensed/1/import',{'confirm':'yes'}).status_code,404)

    def test_migrations_repeat_and_preserve_records_and_agent_choice(self):
        self.queue()
        before=dict(self.rows('leads')[0])
        self.sql("UPDATE agents SET enabled=0 WHERE id='website-audit'")
        application.init_db()
        application.init_db()
        self.assertEqual(dict(self.rows('leads')[0]),before)
        self.assertEqual(len(self.rows('p4_jobs')),1)
        self.assertEqual(next(r['enabled'] for r in self.rows('agents') if r['id']=='website-audit'),0)


class AuditEngineTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'})
        self.env.start()
        self.sleep=patch('website_audit.time.sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.env.stop()

    def run_audit(self, responses, url='https://site.example/'):
        with patch('website_audit.public_get',side_effect=responses) as fetch:
            result=audit.audit(url)
            return result,fetch

    def test_actual_html_findings_broken_link_and_evidence(self):
        result,fetch=self.run_audit([(404,b''),(200,b'<html><a href="/missing">Lost</a><a href="mailto:owner@example.com">Contact</a></html>'),(404,b'Not found')])
        self.assertEqual(result['requests'],3)
        self.assertEqual({f['code'] for f in result['findings']},{'missing-title','missing-meta_description','missing-viewport','http-not-found'})
        self.assertEqual(len(result['observations'][1]['sha256']),64)
        self.assertTrue(result['pages'][0]['contact_links'])
        self.assertTrue(result['recommendations'])
        self.assertEqual(fetch.call_args_list[2].args[0],'https://site.example/missing')

    def test_complete_metadata_no_invented_findings(self):
        result,_=self.run_audit([(200,b'User-agent: *\nAllow: /'),(200,b'<html lang="en"><title>Actual title</title><meta name="description" content="Actual description"><meta name="viewport" content="width=device-width"><a href="tel:123">Call</a></html>')])
        self.assertEqual(result['findings'],[])
        self.assertEqual(result['pages'][0]['title'],'Actual title')

    def test_valueless_html_attributes_do_not_crash_audit(self):
        result,_=self.run_audit([(404,b''),(200,b'<meta name><a href>Blank</a><html lang><title>Actual</title>')])
        self.assertEqual(result['pages'][0]['title'],'Actual')
        self.assertEqual(result['pages'][0]['viewport'],'')

    def test_robots_per_path_and_delay_restrictions(self):
        result,fetch=self.run_audit([(200,b'User-agent: *\nDisallow: /private'),(200,b'<title>A</title><a href="/private">Private</a>')])
        self.assertEqual(fetch.call_count,2)
        self.assertTrue(any('Robots disallows' in r['reason'] for r in result['unchecked']))
        with self.assertRaisesRegex(WorkflowError,'slower crawl'):
            self.run_audit([(200,b'User-agent: *\nCrawl-delay: 10')])
        with self.assertRaisesRegex(WorkflowError,'permission'):
            self.run_audit([(403,b'')])

    def test_scope_limits_no_cross_origin_queries_or_downloads(self):
        html='<title>A</title>'+''.join(f'<a href="/page{i}">Page</a>' for i in range(20))+'<a href="https://other.example/">Other</a><a href="/search?q=secret">Query</a><a href="/file.pdf">PDF</a>'
        result,fetch=self.run_audit([(404,b''),(200,html.encode())]+[(200,b'<title>B</title>')]*5)
        self.assertEqual(fetch.call_count,7)
        self.assertEqual(len(result['pages']),6)
        self.assertTrue(all('other.example' not in call.args[0] and '?' not in call.args[0] for call in fetch.call_args_list))

    def test_redirect_timeout_and_server_error_not_site_down(self):
        result,_=self.run_audit([(404,b''),WorkflowError('Redirect blocked')])
        self.assertEqual(result['findings'],[])
        self.assertTrue(any('Redirect blocked' in row['reason'] for row in result['unchecked']))
        result,_=self.run_audit([(404,b''),(503,b'Unavailable')])
        self.assertEqual(result['findings'],[])
        self.assertTrue(any('HTTP 503' in row['reason'] for row in result['unchecked']))

    def test_base_url_and_malformed_links_do_not_create_false_broken_links(self):
        html=b'<base href="https://other.example/"><title>A</title><a href="missing">Elsewhere</a><a href="https://[invalid">Bad</a>'
        result,fetch=self.run_audit([(404,b''),(200,html)])
        self.assertEqual(fetch.call_count,2)
        self.assertFalse(any(f['code']=='http-not-found' for f in result['findings']))

    def test_invalid_urls_and_disabled_audits(self):
        for url in ('http://site.example/','https://user:pass@site.example/','https://site.example/?secret=1','https://site.example/\r\nHeader: x','https://site.example/#fragment'):
            with self.assertRaises(WorkflowError):audit.audit_url(url)
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'0'}),patch('website_audit.public_get') as fetch:
            with self.assertRaises(WorkflowError):audit.audit('https://site.example/')
            fetch.assert_not_called()

    def test_pause_callback_stops_before_dispatch(self):
        with patch('website_audit.public_get') as fetch:
            with self.assertRaisesRegex(WorkflowError,'paused'):
                audit.audit('https://site.example/',lambda: (_ for _ in ()).throw(WorkflowError('paused')))
            fetch.assert_not_called()

    def test_compressed_response_cannot_be_misread_as_missing_metadata(self):
        import website_evidence
        connection=MagicMock()
        response=connection.getresponse.return_value
        response.status=200
        response.getheader.side_effect=lambda name,default='': {'Content-Encoding':'gzip','Content-Type':'text/html'}.get(name,default)
        with patch.dict(os.environ,{},clear=True),patch('website_evidence.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('website_evidence.PinnedHTTPS',return_value=connection):
            with self.assertRaisesRegex(WorkflowError,'Compressed'):
                website_evidence.public_get('https://site.example/',100,'text/html')
        connection.close.assert_called_once()


if __name__=='__main__':
    unittest.main()

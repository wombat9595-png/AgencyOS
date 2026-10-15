from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import subprocess
import sys
import time
import unittest
from unittest.mock import patch, MagicMock
import app as application
import test_agencyos as baseline
from test_agent_center import CONFIG
import discovery
import phase3
import phase3_store as store
import website_evidence as web
from ai_drafts import DraftError


def record():
    return dict(reviewed=True,reviewed_at=store.stamp(),reviewer='Synthetic operator',contact='operator@example.com',
                policy_urls=list(discovery.POLICIES),endpoints=[discovery.NOMINATIM,discovery.OVERPASS],interval_seconds=2,daily_limit=20)


def candidate(identifier=101,name='Fictional Plumbing'):
    data=dict(business_name=name,contact_name='',email='',website='https://example.com',industry='plumbing',location='Fictional City',source=f'OpenStreetMap node/{identifier}',status='New',notes='')
    return dict(source_id=f'node/{identifier}',source_url=f'https://www.openstreetmap.org/node/{identifier}',retrieved_at=store.stamp(),data=data,attribution=discovery.ATTRIBUTION,search_location='Fictional City',matched_tag='craft=plumber')


class WorkflowTest(unittest.TestCase):
    post=baseline.AgencyOSTest.post
    rows=baseline.AgencyOSTest.rows
    def setUp(self):
        baseline.AgencyOSTest.setUp(self)
        self.env=patch.dict(os.environ,{'AGENCYOS_OSM_POLICY_FILE':'','AGENCYOS_WEBSITE_FETCH':'0'});self.env.start()
        self.net=patch('discovery.request.build_opener',side_effect=AssertionError('Unmocked network prohibited'));self.net.start()
        self.ai=patch('ai_drafts.request.build_opener',side_effect=AssertionError('Unmocked AI prohibited'));self.ai.start()
        self.policy_file=Path(self.temp.name)/'policy.json';self.policy_file.write_text(json.dumps(record()))
        self.post('/leads',dict(business_name='Fictional Studio',website='https://studio.example',industry='Design',location='Fictional City',email='private@example.com',notes='Private notes'))
    def tearDown(self):
        self.ai.stop();self.net.stop();self.env.stop();baseline.AgencyOSTest.tearDown(self)
    def work(self):return phase3.worker_once(application.DB_PATH)
    def search(self):return self.post('/discovery',dict(location='Canberra, ACT, Australia',industry='plumbing',maximum='5'))
    def research(self,mode='local',evidence_ids=None):
        return self.post('/research',dict(lead_id='1',mode=mode,brief='Enquiry goals',evidence_ids=evidence_ids or []))
    def approve(self,location):return self.post(location+'/approve',{'confirm':'yes'})
    def review(self,location,decision='Approved'):return self.post(location+'/decision',{'decision':decision})
    def add_quote(self):
        response=self.post('/research/1/evidence',dict(source_url='https://example.com/about',quote='Fictional service quotation.',confirm='yes'))
        self.assertEqual(response.status_code,302)
        return self.rows('p3_evidence')[-1]['id']
    def complete_research(self):
        location=self.research(evidence_ids=[str(self.add_quote())]).location
        self.work();self.review(location)
        return self.rows('p3_jobs')[-1]['id']

    def test_new_pages_and_existing_links(self):
        for url in ('/workflows','/discovery','/research','/research?lead_id=1','/outreach/history'):
            page=self.client.get(url);self.assertEqual(page.status_code,200,url)
        self.assertIn(b'Live discovery disabled',self.client.get('/discovery').data)
        self.assertIn(b'Business Discovery',self.client.get('/').data)
        self.assertIn(b'saved draft history',self.client.get('/outreach').data)

    def test_policy_gate_prevents_any_network_request(self):
        location=self.search().location
        self.assertIn(b'Awaiting approval',self.client.get(location).data)
        response=self.approve(location)
        self.assertEqual(response.status_code,400)
        self.assertIn(b'Live OSM discovery is disabled',response.data)
        self.assertFalse(self.work())
        self.assertEqual(len(self.rows('p3_candidates')),0)

    def test_real_discovery_contract_candidate_approval_replay_and_provenance(self):
        with patch.dict(os.environ,{'AGENCYOS_OSM_POLICY_FILE':str(self.policy_file)}),patch('phase3.discover',return_value=[candidate()]) as provider:
            location=self.search().location
            self.assertEqual(self.post(location+'/approve').status_code,400)
            self.assertEqual(self.approve(location).status_code,302)
            self.assertFalse(provider.called)
            self.assertTrue(self.work());self.assertEqual(provider.call_count,1)
            self.assertFalse(self.work())
        self.assertEqual(len(self.rows('leads')),1)
        page=self.client.get(location)
        self.assertIn(b'Fictional Plumbing',page.data);self.assertIn(b'ODbL',page.data)
        self.assertEqual(self.post('/discovery/candidates/1/decide',{'decision':'Approved'}).status_code,400)
        self.assertEqual(self.post('/discovery/candidates/1/decide',{'decision':'Approved','confirm':'yes'}).status_code,302)
        self.assertEqual(len(self.rows('leads')),2)
        self.assertEqual(self.rows('p3_evidence')[0]['origin'],'OSM directory')
        self.assertEqual(self.post('/discovery/candidates/1/decide',{'decision':'Approved','confirm':'yes'}).status_code,409)
        self.assertEqual(self.rows('p3_candidates')[0]['source_url'],'https://www.openstreetmap.org/node/101')

    def test_duplicate_import_rechecked_against_latest_leads(self):
        with patch.dict(os.environ,{'AGENCYOS_OSM_POLICY_FILE':str(self.policy_file)}),patch('phase3.discover',return_value=[candidate(),candidate(102)]):
            location=self.search().location;self.approve(location);self.work()
        self.post('/discovery/candidates/1/decide',{'decision':'Approved','confirm':'yes'})
        self.assertIn(b'Possible duplicate',self.client.get(location).data)
        self.assertEqual(self.post('/discovery/candidates/2/decide',{'decision':'Approved','confirm':'yes'}).status_code,400)
        self.assertEqual(self.post('/discovery/candidates/2/decide',{'decision':'Approved','confirm':'yes','allow_duplicate':'yes'}).status_code,302)
        self.assertEqual(len(self.rows('leads')),3)

    def test_empty_failed_and_rejected_discovery_never_creates_leads(self):
        with patch.dict(os.environ,{'AGENCYOS_OSM_POLICY_FILE':str(self.policy_file)}):
            for output in ([],[candidate()]):
                with patch('phase3.discover',return_value=output):
                    location=self.search().location;self.approve(location);self.work()
                if output:
                    self.post('/discovery/candidates/1/decide',{'decision':'Rejected'})
            with patch('phase3.discover',side_effect=store.WorkflowError('Provider unavailable')):
                location=self.search().location;self.approve(location);self.work()
        self.assertEqual(len(self.rows('leads')),1)
        self.assertEqual(self.rows('p3_jobs')[-1]['status'],'Failed')
        self.assertFalse(self.work())

    def test_approved_snapshot_local_research_and_saved_outreach(self):
        research_id=self.complete_research()
        job=self.rows('p3_jobs')[0];payload=json.loads(job['payload_json'])
        self.assertNotIn('private@example.com',job['payload_json']);self.assertNotIn('Private notes',job['payload_json'])
        self.assertEqual(payload['evidence'][0]['origin'],'Owner supplied')
        page=self.client.get('/workflows/1');self.assertIn(b'Unverified opportunities',page.data)
        self.assertIn(b'Owner supplied',page.data)
        response=self.post('/outreach/history',{'research_id':str(research_id),'mode':'local'})
        self.assertEqual(response.status_code,302);self.work()
        draft=self.rows('p3_drafts')[0]
        self.assertEqual(draft['status'],'Needs review');self.assertIn('Fictional Studio',draft['body'])
        self.assertNotIn('website has faults',draft['body'])
        self.assertEqual(self.post('/outreach/history/1/review',{'status':'Approved','follow_up_date':'2027-01-15'}).status_code,302)
        self.assertEqual(self.rows('p3_drafts')[0]['follow_up_date'],'2027-01-15')
        self.assertIn(b'Nothing sent',self.client.get('/outreach/history').data)
        self.assertEqual(len(self.rows('p3_draft_events')),2)
        self.assertFalse(self.work())

    def test_outreach_rejects_unapproved_research_and_bad_dates(self):
        self.research();self.work()
        self.assertEqual(self.post('/outreach/history',{'research_id':'1','mode':'local'}).status_code,400)
        self.review('/workflows/1')
        self.post('/outreach/history',{'research_id':'1','mode':'local'});self.work()
        self.assertEqual(self.post('/outreach/history/1/review',{'status':'Sent'}).status_code,400)
        self.assertEqual(self.post('/outreach/history/1/review',{'status':'Approved','follow_up_date':'not-date'}).status_code,400)
        self.assertEqual(self.rows('p3_drafts')[0]['status'],'Needs review')

    def test_ai_requires_approval_configuration_and_valid_evidence(self):
        evidence_id=self.add_quote()
        location=self.research('ai',[str(evidence_id)]).location
        self.assertEqual(self.post(location+'/approve').status_code,400)
        self.assertFalse(self.work())
        output=json.dumps({'suggestions':[{'text':'Consider enquiry goals.','evidence_ids':[evidence_id]}],'questions':['What services matter?'],'angles':['Offer a discussion.']})
        with patch.dict(os.environ,CONFIG),patch('phase3.request_chat',return_value=output) as model:
            self.approve(location);self.work()
            self.assertEqual(model.call_count,1)
            self.assertNotIn('private@example.com',model.call_args.args[1])
            self.assertEqual(self.rows('p3_jobs')[0]['status'],'Awaiting review')
            self.assertEqual(self.approve(location).status_code,409)
            self.assertFalse(self.work());self.assertEqual(model.call_count,1)

    def test_ai_invented_evidence_ids_are_rejected(self):
        with patch.dict(os.environ,CONFIG),patch('phase3.request_chat',return_value=json.dumps({'suggestions':[{'text':'Fake finding','evidence_ids':[999]}],'questions':[],'angles':[]})):
            location=self.research('ai').location;self.approve(location);self.work()
        self.assertEqual(self.rows('p3_jobs')[0]['status'],'Failed')
        self.assertIn('unsupported evidence',self.rows('p3_jobs')[0]['error'])
        self.assertEqual(self.rows('p3_jobs')[0]['result'],'')

    def test_ai_configuration_change_requires_fresh_approval(self):
        with patch.dict(os.environ,CONFIG),patch('phase3.request_chat') as model:
            location=self.research('ai').location;self.approve(location)
            with patch.dict(os.environ,{'AGENCYOS_AI_MODEL':'changed'}):self.work()
            self.assertFalse(model.called)
        self.assertEqual(self.rows('p3_jobs')[0]['status'],'Awaiting approval')

    def test_ai_draft_failure_has_no_fake_output_or_automatic_retry(self):
        research_id=self.complete_research()
        with patch.dict(os.environ,CONFIG),patch('phase3.request_chat',side_effect=DraftError('Provider HTTP 429')) as model:
            location=self.post('/outreach/history',{'research_id':str(research_id),'mode':'ai'}).location
            self.assertFalse(self.work());self.approve(location);self.work();self.assertEqual(model.call_count,1)
        self.assertEqual(self.rows('p3_jobs')[-1]['status'],'Failed')
        self.assertEqual(len(self.rows('p3_drafts')),0)
        self.assertFalse(self.work())

    def test_inspection_is_opt_in_and_requires_review_before_research(self):
        self.assertEqual(self.post('/research/1/inspect').status_code,400)
        location=self.post('/research/1/inspect',{'permission':'yes'}).location
        self.assertEqual(self.approve(location).status_code,400)
        observation=dict(source_url='https://example.com/',facts={'title':'Fictional Studio','visible_excerpt':'Fictional services'},content_hash='synthetic-hash')
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('phase3.inspect',return_value=observation) as fetch:
            self.approve(location);self.work();self.assertEqual(fetch.call_count,1)
        evidence_id=self.rows('p3_evidence')[0]['id']
        self.assertEqual(self.research(evidence_ids=[str(evidence_id)]).status_code,400)
        self.review(location)
        research_location=self.research(evidence_ids=[str(evidence_id)]).location;self.work();self.review(research_location)
        self.post('/outreach/history',{'research_id':'2','mode':'local'});self.work()
        self.assertIn('homepage snapshot',self.rows('p3_drafts')[0]['body'])
        self.assertIn('Fictional Studio',self.rows('p3_drafts')[0]['body'])

    def test_inspection_failure_produces_no_website_claim(self):
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('phase3.inspect',side_effect=store.WorkflowError('Robots policy blocks this inspection')):
            location=self.post('/research/1/inspect',{'permission':'yes'}).location;self.approve(location);self.work()
        self.assertEqual(len(self.rows('p3_evidence')),0)
        self.assertEqual(self.rows('p3_jobs')[0]['result'],'')
        self.assertEqual(self.rows('p3_jobs')[0]['status'],'Failed')

    def test_owner_isolation_csrf_and_snapshot_immutability(self):
        self.add_quote();location=self.research(evidence_ids=['1']).location
        snapshot=self.rows('p3_jobs')[0]['payload_json']
        with closing(sqlite3.connect(application.DB_PATH)) as conn,conn:conn.execute("UPDATE leads SET business_name='Changed'")
        self.assertEqual(snapshot,self.rows('p3_jobs')[0]['payload_json'])
        for path in (location+'/approve',location+'/decision','/discovery','/research','/research/1/evidence','/research/1/inspect','/outreach/history','/outreach/history/1/review','/discovery/candidates/1/decide'):
            self.assertEqual(self.client.post(path,data={}).status_code,400,path)
        with self.client.session_transaction() as session:session['user_id']=999
        self.assertEqual(self.client.get(location).status_code,404)
        self.assertEqual(self.approve(location).status_code,404)
        self.assertEqual(self.review(location).status_code,404)
        self.assertEqual(self.research(evidence_ids=['1']).status_code,400)
        self.assertEqual(self.post('/outreach/history/1/review',{'status':'Approved'}).status_code,404)

    def test_cancelled_tasks_do_not_execute_and_bad_validation(self):
        location=self.research().location
        self.assertEqual(self.review(location,'Cancelled').status_code,302)
        self.assertFalse(self.work())
        self.assertEqual(self.review(location).status_code,409)
        self.assertEqual(self.post('/research',{'lead_id':'1','mode':'invalid'}).status_code,400)
        self.assertEqual(self.post('/discovery',{'location':'Anywhere','industry':'plumbing','maximum':'100'}).status_code,400)
        self.assertEqual(self.post('/research/1/evidence',{'source_url':'javascript:alert(1)','quote':'x','confirm':'yes'}).status_code,400)

    def test_worker_disabled_agent_and_daily_usage_limits(self):
        self.research()
        self.post('/agents/lead-research/settings',{'name':'Research','enabled':''})
        self.work();self.assertEqual(self.rows('p3_jobs')[0]['status'],'Failed')
        self.post('/agents/lead-research/settings',{'name':'Research','enabled':'yes'})
        with closing(store.connect(application.DB_PATH)) as conn:
            conn.execute('INSERT INTO p3_usage VALUES(?,?,?,?,0)',('phase3-ai',store.stamp()[:10],20,0));conn.commit()
        with patch.dict(os.environ,CONFIG),patch('phase3.request_chat') as model:
            location=self.research('ai').location;self.approve(location);self.work();self.assertFalse(model.called)
        self.assertIn('Daily provider',self.rows('p3_jobs')[-1]['error'])

    def test_legacy_quick_ai_draft_also_requires_explicit_cost_approval(self):
        with patch('app.generate_draft') as model:
            response=self.post('/outreach',{'lead_id':'1','draft_mode':'ai'})
            self.assertIn(b'Approve the AI charge',response.data)
            self.assertFalse(model.called)

    def test_upgrade_from_phase2b_preserves_original_copy_and_tasks(self):
        import hashlib,shutil
        legacy=self.post('/agents/tasks/new',dict(agent_id='lead-research',lead_id='1',title='Saved Phase 2B task',mode='local')).location
        self.post(legacy+'/run')
        original_tables=('users','leads','quotes','invoices','projects','lead_imports','agent_tasks','agent_events','agent_approvals')
        before={table:[tuple(row) for row in self.rows(table)] for table in original_tables}
        with closing(store.connect(application.DB_PATH)) as conn:
            for table in ('p3_draft_events','p3_drafts','p3_evidence','p3_candidates','p3_events','p3_jobs','p3_cache','p3_usage','p3_migrations'):
                conn.execute('DROP TABLE '+table)
            conn.execute("UPDATE agents SET availability='planned',enabled=0 WHERE id IN ('lead-discovery','outreach')")
            conn.commit()
        original=Path(self.temp.name)/'original-phase2b.db'
        shutil.copy2(application.DB_PATH,original)
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        application.init_db()
        for table in original_tables:self.assertEqual([tuple(row) for row in self.rows(table)],before[table],table)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),digest)
        self.assertEqual(self.client.get(legacy).status_code,200)
        self.assertEqual(self.research().status_code,302)

    def test_oversized_input_and_evidence_limits_prevent_excessive_ai_inputs(self):
        with closing(store.connect(application.DB_PATH)) as conn:
            with self.assertRaisesRegex(store.WorkflowError,'24,000'):
                store.create_job(conn,1,'research','ai',{'brief':'x'*24001},True)
        for _ in range(11):self.add_quote()
        self.assertEqual(self.research(evidence_ids=[str(i) for i in range(1,12)]).status_code,400)
        self.assertEqual(self.post('/research/1/evidence',{'source_url':'https://example.com/'+'x'*2048,'quote':'Fictional','confirm':'yes'}).status_code,400)

    def test_policy_cli_requires_attestation_and_never_overwrites_review(self):
        output=Path(self.temp.name)/'operator-review.json'
        args=[sys.executable,'manage.py','policy-review','--reviewer','Synthetic reviewer','--contact','operator@example.com','--output',str(output)]
        response=subprocess.run(args,capture_output=True,text=True)
        self.assertNotEqual(response.returncode,0);self.assertFalse(output.exists())
        response=subprocess.run(args+['--i-have-verified-current-policies'],capture_output=True,text=True)
        self.assertEqual(response.returncode,0,response.stderr)
        before=output.read_bytes()
        response=subprocess.run(args+['--i-have-verified-current-policies'],capture_output=True,text=True)
        self.assertNotEqual(response.returncode,0);self.assertEqual(output.read_bytes(),before)
        self.assertIn('already exists',response.stderr)

    def test_queue_limit_and_not_before_foundation(self):
        for _ in range(20):self.assertEqual(self.research().status_code,302)
        self.assertEqual(self.research().status_code,400)
        with closing(store.connect(application.DB_PATH)) as conn:
            conn.execute('UPDATE p3_jobs SET not_before=?',(time.time()+86400,));conn.commit()
        self.assertFalse(self.work())

    def test_concurrent_claim_and_interrupted_lease_never_requeue(self):
        self.research();claimed=[]
        def claim():
            with closing(store.connect(application.DB_PATH)) as conn:
                job=store.claim(conn);claimed.append(job['id'] if job else None)
        workers=[threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(3)
        self.assertEqual(sorted(str(i) for i in claimed),['1','None'])
        with closing(store.connect(application.DB_PATH)) as conn:
            conn.execute('UPDATE p3_jobs SET lease_until=?',(time.time()-1,));conn.commit()
        self.assertFalse(self.work())
        self.assertEqual(self.rows('p3_jobs')[0]['status'],'Interrupted')
        self.assertEqual(self.rows('p3_jobs')[0]['attempts'],1)
        self.assertFalse(self.work())

    def test_migration_preserves_all_existing_records_and_saved_tasks(self):
        legacy=self.post('/agents/tasks/new',dict(agent_id='lead-research',lead_id='1',title='Existing task',mode='local')).location
        self.post(legacy+'/run')
        self.complete_research()
        tables=('users','leads','quotes','invoices','projects','agent_tasks','agent_events','p3_jobs','p3_events','p3_evidence')
        before={table:[tuple(row) for row in self.rows(table)] for table in tables}
        application.init_db();application.init_db()
        for table in tables:self.assertEqual([tuple(row) for row in self.rows(table)],before[table],table)
        self.assertEqual(self.client.get(legacy).status_code,200)

    def test_untrusted_quotes_and_results_are_escaped(self):
        self.post('/research/1/evidence',dict(source_url='https://example.com',quote='<script>alert(1)</script>',confirm='yes'))
        location=self.research(evidence_ids=['1']).location;self.work()
        response=self.client.get(location)
        self.assertNotIn(b'<script>alert',response.data)
        self.assertIn(b'Owner supplied',response.data)


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.conn=store.connect(str(Path(self.temp.name)/'test.db'))
        self.conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)');self.conn.execute('CREATE TABLE leads(id INTEGER PRIMARY KEY)');self.conn.execute('CREATE TABLE agents(id TEXT,availability TEXT,enabled INTEGER,description TEXT)')
        store.migrate(self.conn);self.conn.commit()
        self.path=Path(self.temp.name)/'policy.json';self.path.write_text(json.dumps(record()))
        self.env=patch.dict(os.environ,{'AGENCYOS_OSM_POLICY_FILE':str(self.path)});self.env.start()
    def tearDown(self):self.env.stop();self.conn.close();self.temp.cleanup()
    def test_policy_validation_expiry_and_missing_attestation(self):
        for changed in ({'reviewed':False},{'reviewed_at':'2020-01-01T00:00:00+00:00'},{'contact':''},{'policy_urls':[]},{'interval_seconds':0},{'daily_limit':1000},{'reviewed_at':'invalid'}):
            self.path.write_text(json.dumps(dict(record(),**changed)))
            with self.assertRaises(store.WorkflowError):discovery.policy()
    def test_real_api_query_parsing_caching_and_no_contact_invention(self):
        payload=discovery.search_payload('Canberra, ACT, Australia','plumbing',5)
        result={'elements':[{'type':'node','id':101,'tags':{'name':'Fictional Plumbing','craft':'plumber','website':'https://example.com','addr:city':'Fictional City'}},
                            {'type':'way','id':102,'tags':{'name':'Fictional No Contact','craft':'plumber','website':'javascript:alert(1)','email':'invalid'}},
                            {'type':'node','id':101,'tags':{'name':'Repeated'}}]}
        with patch('discovery.json_request',side_effect=[[{'lat':'-35.28','lon':'149.13'}],result]) as provider:
            rows=discovery.discover(self.conn,payload)
            self.assertEqual(provider.call_count,2)
            query=provider.call_args.args[2]['data'];self.assertIn('craft',query);self.assertIn('around:10000',query)
            self.assertEqual(rows[1]['data']['email'],'');self.assertEqual(rows[1]['data']['website'],'')
            self.assertEqual(rows[1]['data']['location'],'')
            self.assertEqual(len(rows),2)
            cached=discovery.discover(self.conn,payload)
            self.assertEqual(provider.call_count,2);self.assertEqual(rows,cached)
    def test_validation_injection_and_local_targeting(self):
        for args in (('','plumbing',5),('X','unknown',5),('X','plumbing',0),('X','custom',5,'','any','craft=plumber];out;')):
            with self.assertRaises(store.WorkflowError):discovery.search_payload(*args)
        payload=discovery.search_payload('Anywhere','plumbing',1,'fictional','not-listed')
        with patch('discovery.json_request',side_effect=[[{'lat':'1','lon':'2'}],{'elements':[{'type':'node','id':1,'tags':{'name':'Fictional','craft':'plumber'}}]}]):
            rows=discovery.discover(self.conn,payload)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['data']['website'],'')
    def test_unavailable_location_and_incomplete_source_fail(self):
        payload=discovery.search_payload('Anywhere','plumbing',1)
        with patch('discovery.json_request',return_value=[]):
            with self.assertRaisesRegex(store.WorkflowError,'not found'):discovery.discover(self.conn,payload)
        self.conn.execute('DELETE FROM p3_cache');self.conn.commit()
        with patch('discovery.json_request',side_effect=[[{'lat':'1','lon':'2'}],{'elements':[],'remark':'timeout'}]):
            with self.assertRaisesRegex(store.WorkflowError,'incomplete'):discovery.discover(self.conn,payload)
    def test_rate_reservations_and_http_backoff(self):
        from urllib.error import HTTPError
        store.reserve_call(self.conn,'test',2,2)
        with self.assertRaisesRegex(store.WorkflowError,'rate limit'):store.reserve_call(self.conn,'test',2,2)
        with patch('discovery.request.build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError(discovery.NOMINATIM,429,'too many',{},None)
            with self.assertRaisesRegex(store.WorkflowError,'HTTP 429'):discovery.json_request(self.conn,discovery.NOMINATIM,{'q':'Synthetic'},'nominatim',record())
        row=self.conn.execute("SELECT * FROM p3_usage WHERE service='nominatim'").fetchone()
        self.assertGreater(row['blocked_until'],time.time()+3000)
    def test_wire_request_identity_no_redirect_and_response_bounds(self):
        with patch('discovery.request.build_opener') as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value=b'[]'
            self.assertEqual(discovery.json_request(self.conn,discovery.NOMINATIM,{'q':'Fictional'},'nominatim',record()),[])
            req=opener.return_value.open.call_args.args[0]
            self.assertIn('operator@example.com',req.get_header('User-agent'))
            response.read.return_value=b'x'*2_000_001
            with self.assertRaisesRegex(store.WorkflowError,'size limit'):discovery.json_request(self.conn,discovery.OVERPASS,{'data':'query'},'overpass',record())


class WebsiteTest(unittest.TestCase):
    def test_public_url_and_private_dns_guard(self):
        for url in ('http://example.com','https://user:pass@example.com','https://example.com:123','file:///tmp/x'):
            with self.assertRaises(store.WorkflowError):web.normalise_origin(url)
        with patch.dict(os.environ,{},clear=True),patch('website_evidence.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('website_evidence.PinnedHTTPS') as transport:
            with self.assertRaisesRegex(store.WorkflowError,'Private'):web.public_get('https://example.com/',1024,'text/html')
            self.assertFalse(transport.called)
    def test_proxy_mode_fails_closed(self):
        with patch.dict(os.environ,{'HTTPS_PROXY':'https://proxy.example'}):
            with self.assertRaisesRegex(store.WorkflowError,'proxy'):web.public_get('https://example.com/',100,'text/html')
    def test_opt_in_robots_and_actual_observations(self):
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'0'}),patch('website_evidence.public_get') as get:
            with self.assertRaises(store.WorkflowError):web.inspect('https://example.com')
            self.assertFalse(get.called)
        page=b'<html lang="en"><title>Fictional Studio</title><h1>Fictional services</h1><script>Hidden text</script><meta name="description" content="Fictional description"></html>'
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('website_evidence.public_get',side_effect=[(200,b'User-agent: *\nAllow: /'),(200,page)]) as get:
            evidence=web.inspect('https://example.com/about')
            self.assertEqual(evidence['facts']['title'],'Fictional Studio')
            self.assertNotIn('Hidden text',evidence['facts']['visible_excerpt'])
            self.assertEqual(evidence['source_url'],'https://example.com/')
            self.assertEqual(len(evidence['content_hash']),64)
            self.assertEqual(get.call_count,2)
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('website_evidence.public_get',return_value=(200,b'User-agent: *\nDisallow: /')) as get:
            with self.assertRaisesRegex(store.WorkflowError,'Robots'):web.inspect('https://example.com')
            self.assertEqual(get.call_count,1)
    def test_no_redirect_following_and_tls_host_pinning(self):
        connection=MagicMock();response=connection.getresponse.return_value;response.status=302
        with patch.dict(os.environ,{},clear=True),patch('website_evidence.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('website_evidence.PinnedHTTPS',return_value=connection) as transport:
            with self.assertRaisesRegex(store.WorkflowError,'redirected'):web.public_get('https://example.com/',100,'text/html')
            self.assertEqual(transport.call_args.args[:2],('example.com','93.184.216.34'))
            connection.close.assert_called_once()

if __name__=='__main__':unittest.main()

"""Complete fictional agency workflow; all external responses are injected fixtures."""
import io
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
import app as application
import phase4
import production_ops
import sales_ai
from phase3_store import connect,WorkflowError
import test_phase11 as lifecycle_fixtures
import test_phase5 as sales_fixtures
import test_phase4 as discovery_fixtures


class ProductionWorkflowTest(unittest.TestCase):
    setUp=lifecycle_fixtures.LifecycleAcceptanceTest.setUp
    tearDown=lifecycle_fixtures.LifecycleAcceptanceTest.tearDown
    stage=discovery_fixtures.Phase4Test.stage
    sql=sales_fixtures.SalesTest.sql

    def new(self,**changes):
        return sales_fixtures.SalesTest.new(self,lead_id='2',**changes)

    def prepare_message(self):
        message=sales_fixtures.SalesTest.prepare_message(self)
        self.post(f"/sales/messages/{message['id']}/approve",dict(confirm='yes',mock_authorisation='yes'))
        self.assertTrue(self.work())
        self.assertEqual(self.rows('p5_messages')[-1]['status'],'Mock accepted')
        response=self.post(f"/sales/messages/{message['id']}/record",dict(kind='reply',text='Synthetic fixture: what does the scope include?',confirm='yes'))
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.work())
        classification=self.rows('p5_jobs')[-1]
        self.assertEqual(json.loads(classification['result_json'])['classification'],'question')
        self.post(f"/sales/jobs/{classification['id']}/decision",dict(decision='Prepare reply'))
        self.assertTrue(self.work())
        self.assertEqual(self.rows('p5_drafts')[-1]['kind'],'reply')
        return message

    def test_full_canberra_fixture_and_delivery_recovery(self):
        plan=dict(states=['ACT'],cities='Canberra',industries='Design',daily_leads='1',research_budget_cents='0',minimum_score='50',provider='licensed_csv')
        self.assertEqual(self.post('/launch/discovery',plan).status_code,302)
        body=discovery_fixtures.csv_data(name='Fictional Canberra Studio',state='ACT').replace(b',Sydney,',b',Canberra,').replace(b'https://studio.example/',b'https://canberra-fixture.example/')
        self.assertEqual(self.stage(body).status_code,302)
        self.assertEqual(self.post('/discovery/licensed/1/import',dict(confirm='yes')).status_code,302)
        for kind in ('qualification','research'):
            location=self.post('/agency/queue',dict(lead_id='2',kind=kind)).location
            self.assertTrue(phase4.worker_once(application.DB_PATH))
            self.assertEqual(self.post(location+'/decision',dict(decision='Approved')).status_code,302)
        location=self.post('/agency/queue',dict(lead_id='2',kind='audit',permission='yes')).location
        with patch.dict(os.environ,{'AGENCYOS_WEBSITE_FETCH':'1'}),patch('website_audit.public_get',side_effect=[(404,b''),(200,b'<html lang="en"><title>Fictional Canberra</title><meta name="description" content="Fixture"><meta name="viewport" content="width=device-width"></html>')]) as fetch,patch('website_audit.time.sleep'):
            self.assertEqual(self.post(location+'/decision',dict(decision='Queue audit',confirm='yes')).status_code,302)
            self.assertTrue(phase4.worker_once(application.DB_PATH))
            self.assertEqual(fetch.call_count,2)
        self.assertEqual(self.post(location+'/decision',dict(decision='Approved')).status_code,302)
        lifecycle_fixtures.LifecycleAcceptanceTest.test_authorized_fictional_lifecycle_to_verified_mock_payment_and_daily_summary(self)
        release=self.rows('p10_releases')[0]
        response=self.post(f"/launch/releases/{release['id']}/prepare",dict(customer_evidence='Fictional permission fixture only',target='aws_s3_sydney',confirm='yes'))
        self.assertEqual(response.status_code,200,response.data)
        self.assertFalse(response.json['public_execution_authorized'])
        handover=self.client.get(f"/launch/releases/{release['id']}/handover")
        import zipfile
        with zipfile.ZipFile(io.BytesIO(handover.data)) as archive:self.assertIn('index.html',archive.namelist())
        self.assertEqual(self.post(f"/websites/{release['site_id']}/rollback/{release['id']}",dict(confirm='yes')).status_code,302)
        self.assertEqual(self.rows('p10_events')[-1]['kind'],'rollback')
        dashboard=self.client.get('/launch')
        self.assertEqual(dashboard.status_code,200,dashboard.data)
        self.assertIn(b'not business revenue',dashboard.data)
        self.assertIn(b'not established',dashboard.data)
        self.assertEqual(len(self.rows('p5_ai_usage')),0)
        self.assertTrue(all(row['synthetic'] for row in self.rows('p7_invoices')))
        before=dict(self.rows('p6_site_versions')[0])
        with patch.dict(os.environ,sales_fixtures.CONFIG):
            sales_fixtures.SalesTest.configure_ai(self)
            self.assertEqual(self.post('/launch/flows/1/ai-assistance',dict(kind='qa-assist')).status_code,302)
            job=self.rows('p5_jobs')[-1]
            self.assertEqual(sales_fixtures.SalesTest.approve_ai(self,job).status_code,302)
            with patch('ai_drafts.request.build_opener') as transport:
                transport.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps(dict(subject='Fixture QA suggestion',body='Review spacing manually; no defect inferred.',evidence_ids=[]))}}]}).encode()
                self.assertTrue(self.work())
                self.assertEqual(transport.return_value.open.call_count,1)
        self.assertEqual(dict(self.rows('p6_site_versions')[0]),before)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Needs review')
        root=Path(self.temp.name);key=Fernet.generate_key()
        production_ops.backup(application.DB_PATH,root/'final.enc',key,Path(self.stage_tmp.name))
        production_ops.restore(root/'final.enc',root/'restored',key)
        with closing(sqlite3.connect(root/'restored'/'database.sqlite3')) as conn:
            self.assertEqual(conn.execute('SELECT status FROM p7_invoices').fetchone()[0],'Paid (test)')

    def test_ai_assistance_uses_shared_gate_and_research_budget(self):
        self.post('/leads',dict(business_name='Fictional second lead',email='prospect@example.com'))
        self.new();self.work()
        self.assertEqual(self.post('/launch/flows/1/ai-assistance',dict(kind='research-assist')).status_code,302)
        job=dict(self.rows('p5_jobs')[-1])
        self.assertEqual(job['status'],'Awaiting approval')
        with closing(connect(application.DB_PATH)) as conn,patch.dict(os.environ,sales_fixtures.CONFIG):
            with self.assertRaises(WorkflowError):sales_ai.approval(conn,job)
        self.assertEqual(self.post('/launch/flows/1/ai-assistance',dict(kind='qa-assist')).status_code,400)
        self.assertEqual(len(self.rows('p5_ai_usage')),0)
        self.post('/launch/discovery',dict(states=['ACT'],cities='Canberra',industries='',daily_leads='10',research_budget_cents='100',minimum_score='50',provider='licensed_csv'))
        with patch.dict(os.environ,sales_fixtures.CONFIG):
            sales_fixtures.SalesTest.configure_ai(self)
            self.assertEqual(self.client.get('/sales/1').status_code,200)
            self.assertEqual(sales_fixtures.SalesTest.approve_ai(self,job).status_code,302)
            with patch('ai_drafts.request.build_opener') as transport:
                transport.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps(dict(subject='Fixture synthesis',body='Saved information only.',evidence_ids=[]))}}]}).encode()
                self.assertTrue(self.work())
                self.assertEqual(transport.return_value.open.call_count,1)
        self.assertEqual(self.rows('p5_jobs')[-1]['status'],'Needs review')


for name in ('post','rows','work','accepted_quote','proposal_quote','approve_quote','accept','outreach','settings','package','configure_billing','draft','approve'):
    setattr(ProductionWorkflowTest,name,getattr(lifecycle_fixtures.LifecycleAcceptanceTest,name))

if __name__=='__main__':unittest.main()

"""Integrated synthetic lead-to-site/payment/operations lifecycle acceptance."""
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

import test_phase7 as billing_fixtures
import app as application
import phase7_billing as billing
import p8_ops
from phase3_store import connect


class LifecycleAcceptanceTest(unittest.TestCase):
    def setUp(self):
        billing_fixtures.BillingTest.setUp(self)
        self.stage_tmp=tempfile.TemporaryDirectory()
        self.old_root=application.app.config.get('AGENCYOS_STAGING_ROOT')
        application.app.config['AGENCYOS_STAGING_ROOT']=Path(self.stage_tmp.name)

    def tearDown(self):
        if self.old_root is None:application.app.config.pop('AGENCYOS_STAGING_ROOT',None)
        else:application.app.config['AGENCYOS_STAGING_ROOT']=self.old_root
        self.stage_tmp.cleanup()
        billing_fixtures.BillingTest.tearDown(self)
    post=billing_fixtures.BillingTest.post
    rows=billing_fixtures.BillingTest.rows
    work=billing_fixtures.BillingTest.work
    accepted_quote=billing_fixtures.BillingTest.accepted_quote
    proposal_quote=billing_fixtures.BillingTest.proposal_quote
    approve_quote=billing_fixtures.BillingTest.approve_quote
    accept=billing_fixtures.BillingTest.accept
    prepare_message=billing_fixtures.BillingTest.prepare_message
    outreach=billing_fixtures.BillingTest.outreach
    new=billing_fixtures.BillingTest.new
    settings=billing_fixtures.BillingTest.settings
    package=billing_fixtures.BillingTest.package
    configure_billing=billing_fixtures.BillingTest.configure_billing
    draft=billing_fixtures.BillingTest.draft
    approve=billing_fixtures.BillingTest.approve

    def test_authorized_fictional_lifecycle_to_verified_mock_payment_and_daily_summary(self):
        quote=self.accepted_quote()
        project_id=self.rows('projects')[-1]['id']
        flow_id=self.rows('p5_flows')[-1]['id']
        basis=self.post('/sales/contact-basis',dict(flow_id=str(flow_id),email='prospect@example.com',basis_type='consent',
            evidence_reference='Synthetic fixture only; no real consent record',attest='yes'))
        self.assertEqual(basis.status_code,302)

        self.assertEqual(self.post(f'/projects/{project_id}/website/generate',{'confirm':'yes','theme':'coastal'}).status_code,302)
        self.assertTrue(self.work())
        site=self.rows('p6_sites')[0]
        self.assertEqual(self.rows('p6_site_versions')[0]['status'],'Needs review')
        self.assertEqual(self.post(f"/websites/{site['id']}/approve/1",{'confirm':'yes'}).status_code,302)
        self.assertEqual(self.post(f"/websites/{site['id']}/stage/1",{'confirm':'yes'}).status_code,302)
        release=self.rows('p10_releases')[0]
        self.assertEqual(self.post(f"/websites/releases/{release['id']}/check",{}).status_code,302)
        self.assertEqual(self.rows('p10_checks')[0]['result'],'passed')

        self.configure_billing()
        invoice=self.approve(self.draft(quote))
        self.post(f"/invoices/{invoice['id']}/payment-link",{})
        link=self.rows('p7_payment_links')[-1]
        self.assertEqual(link['provider'],'mock')
        self.assertEqual(self.client.get(link['hosted_url']).status_code,200)
        event=dict(id='phase11-synthetic-payment',type='payment.succeeded',data={'object':{
            'id':'phase11-synthetic-transaction','invoice_id':invoice['id'],'amount':invoice['total_cents'],'currency':'aud'}})
        raw=json.dumps(event,sort_keys=True,separators=(',',':')).encode()
        response=self.client.post('/payments/webhook/mock',data=raw,content_type='application/json',
            headers={'X-AgencyOS-Signature':billing.sign_mock(event,'synthetic-webhook-secret')})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.rows('p7_invoices')[0]['status'],'Paid (test)')
        self.assertEqual(self.rows('p7_payments')[0]['source'],'provider_verified')

        now=time.time()
        with closing(connect(application.DB_PATH)) as conn,conn:
            conn.execute("INSERT INTO p8_summary_settings(user_id,timezone,local_time,enabled) VALUES(1,'UTC','00:00',1)")
            self.assertEqual(p8_ops.create_due_summaries(conn,now_epoch=now),1)
        summary=self.rows('p8_daily_summaries')[0]
        data=json.loads(summary['summary_json'])
        self.assertEqual(data['queues']['p7_invoices']['Paid (test)'],1)
        self.assertEqual(data['queues']['p7_payments']['provider_verified: Verified'],1)
        self.assertEqual(data['queues']['p10_releases']['Current'],1)
        page=self.client.get(f"/operations/summaries/{summary['id']}")
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Paid (test)',page.data)
        self.assertIn(b'provider_verified: Verified',page.data)
        self.assertIn(b'Current',page.data)
        self.assertEqual(self.rows('p7_payment_events')[0]['result'],'Applied')


if __name__=='__main__':unittest.main()

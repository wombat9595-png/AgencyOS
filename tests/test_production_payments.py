import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
import test_phase7 as fixtures
import phase7_billing as billing


class PaymentHardeningTest(unittest.TestCase):
    setUp=fixtures.BillingTest.setUp
    tearDown=fixtures.BillingTest.tearDown
    post=fixtures.BillingTest.post
    rows=fixtures.BillingTest.rows
    settings=fixtures.BillingTest.settings
    package=fixtures.BillingTest.package
    new=fixtures.BillingTest.new
    outreach=fixtures.BillingTest.outreach
    prepare_message=fixtures.BillingTest.prepare_message
    proposal_quote=fixtures.BillingTest.proposal_quote
    approve_quote=fixtures.BillingTest.approve_quote
    accept=fixtures.BillingTest.accept
    work=fixtures.BillingTest.work
    accepted_quote=fixtures.BillingTest.accepted_quote
    configure_billing=fixtures.BillingTest.configure_billing
    draft=fixtures.BillingTest.draft
    approve=fixtures.BillingTest.approve

    def submit(self,event,provider='mock'):
        raw=json.dumps(event,sort_keys=True,separators=(',',':')).encode()
        headers={'X-AgencyOS-Signature':billing.sign_mock(event,'synthetic-webhook-secret')}
        if provider=='stripe_test':
            timestamp=int(time.time())
            sig=hmac.new(b'whsec_fixture',str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
            headers={'Stripe-Signature':f't={timestamp},v1={sig}'}
        with patch.dict(os.environ,{'AGENCYOS_STRIPE_TEST_WEBHOOK_SECRET':'whsec_fixture'}):
            return self.client.post('/payments/webhook/'+provider,data=raw,content_type='application/json',headers=headers)

    def test_unconfigured_mock_webhook_cannot_use_known_old_default(self):
        event={'id':'forged-default','type':'payment.succeeded'}
        raw=json.dumps(event).encode()
        with patch.dict(os.environ,{'AGENCYOS_PAYMENT_WEBHOOK_SECRET':''}):
            result=self.client.post('/payments/webhook/mock',data=raw,content_type='application/json',headers={'X-AgencyOS-Signature':billing.sign_mock(event,'local-test-secret')})
        self.assertEqual(result.status_code,400)
        self.assertEqual(len(self.rows('p7_payment_events')),0)

    def test_changed_event_replay_rejected_without_duplicate_credit(self):
        self.configure_billing();invoice=self.approve(self.draft())
        event=dict(id='same-event',type='payment.succeeded',data={'object':{'id':'partial-tx','invoice_id':invoice['id'],'amount':100,'currency':'aud'}})
        self.assertEqual(self.submit(event).json['result'],'Applied')
        event['data']['object']['amount']=200
        self.assertEqual(self.submit(event).json['result'],'Rejected')
        self.assertEqual(len(self.rows('p7_payments')),1)
        self.assertEqual(self.rows('p7_payments')[0]['amount_cents'],100)

    def test_stripe_unpaid_live_and_duplicate_transaction_events_do_not_inflate_payment(self):
        self.configure_billing();invoice=self.approve(self.draft())
        event=dict(id='stripe-unpaid',type='checkout.session.completed',livemode=False,data={'object':{
            'id':'cs_test_fixture','payment_intent':'pi_test_fixture','invoice_id':invoice['id'],'amount_total':100,'currency':'aud','payment_status':'unpaid'}})
        self.assertEqual(self.submit(event,'stripe_test').json['result'],'Rejected')
        event['id']='stripe-live';event['livemode']=True;event['data']['object']['payment_status']='paid'
        self.assertEqual(self.submit(event,'stripe_test').json['result'],'Rejected')
        event['id']='stripe-paid';event['livemode']=False
        self.assertEqual(self.submit(event,'stripe_test').json['result'],'Applied')
        intent=dict(id='stripe-intent',type='payment_intent.succeeded',livemode=False,data={'object':{
            'id':'pi_test_fixture','invoice_id':invoice['id'],'amount_received':100,'currency':'aud','status':'succeeded'}})
        self.assertEqual(self.submit(intent,'stripe_test').json['result'],'Duplicate')
        self.assertEqual(len(self.rows('p7_payments')),1)

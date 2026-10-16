"""Phase 7 invoices and payment evidence use fictional records and local mock events."""
import hashlib
import hmac
import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_phase5 as fixtures
import app as application
import phase7_billing as billing
import payment_provider


class BillingTest(unittest.TestCase):
    post = fixtures.SalesTest.post
    rows = fixtures.SalesTest.rows
    settings = fixtures.SalesTest.settings
    package = fixtures.SalesTest.package
    new = fixtures.SalesTest.new
    outreach = fixtures.SalesTest.outreach
    prepare_message = fixtures.SalesTest.prepare_message
    proposal_quote = fixtures.SalesTest.proposal_quote
    approve_quote = fixtures.SalesTest.approve_quote
    accept = fixtures.SalesTest.accept
    work = fixtures.SalesTest.work

    def setUp(self):
        fixtures.SalesTest.setUp(self)
        self.bank_key = billing.Fernet.generate_key().decode()
        self.env_billing = patch.dict(os.environ, {
            'AGENCYOS_BANK_ENCRYPTION_KEY': self.bank_key,
            'AGENCYOS_PAYMENT_WEBHOOK_SECRET': 'synthetic-webhook-secret',
            'AGENCYOS_PAYMENT_PROVIDER': 'mock',
        })
        self.env_billing.start()

    def tearDown(self):
        self.env_billing.stop()
        fixtures.SalesTest.tearDown(self)

    def accepted_quote(self):
        quote = self.proposal_quote()
        self.approve_quote(quote)
        self.accept(quote)
        return quote

    def configure_billing(self, **updates):
        data = dict(business_name='Synthetic Example Studio Pty Ltd', business_abn='00 000 000 000',
                    business_address='1 Fictional Street, Sydney NSW', business_email='billing@example.invalid',
                    gst_mode='not_registered', terms='Synthetic test terms: 14 days', provider='mock')
        data.update(updates)
        response = self.post('/invoices/settings', data)
        self.assertEqual(response.status_code, 302)

    def draft(self, quote=None, cycle='one-off'):
        quote = quote or self.accepted_quote()
        response = self.post('/invoices/draft', {'quote_id': str(quote['id']), 'cycle': cycle})
        self.assertEqual(response.status_code, 302)
        return self.rows('p7_invoices')[-1]

    def approve(self, invoice):
        response = self.post(f"/invoices/{invoice['id']}/approve-test", {'confirm': 'yes'})
        self.assertEqual(response.status_code, 302)
        return self.rows('p7_invoices')[-1]

    def test_complete_synthetic_invoice_to_signed_payment_reconciliation(self):
        self.configure_billing()
        invoice = self.draft()
        self.assertEqual(invoice['status'], 'Draft')
        invoice = self.approve(invoice)
        self.assertEqual(invoice['status'], 'Approved (test)')
        self.assertTrue(invoice['invoice_number'].startswith('TEST-INV-'))
        pdf = self.client.get(f"/invoices/{invoice['id']}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, 'application/pdf')
        self.assertTrue(pdf.data.startswith(b'%PDF'))
        out = Path(application.APP_DIR) / 'output' / 'pdf' / 'AgencyOS-synthetic-invoice-example.pdf'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pdf.data)

        self.post(f"/invoices/{invoice['id']}/payment-link", {})
        link = self.rows('p7_payment_links')[-1]
        self.assertEqual(link['provider'], 'mock')
        self.assertEqual(self.client.get(link['hosted_url']).status_code, 200)
        checkout = self.post(link['hosted_url'], {'amount_cents': str(invoice['total_cents'] // 2)})
        self.assertEqual(checkout.status_code, 302)
        self.assertEqual(self.rows('p7_invoices')[-1]['status'], 'Partially paid')

        event = dict(id='synthetic-event-full', type='payment.succeeded', data={'object': {
            'id': 'synthetic-transaction-full', 'invoice_id': invoice['id'],
            'amount': invoice['total_cents'] - invoice['total_cents'] // 2, 'currency': 'aud'}})
        signature = billing.sign_mock(event, 'synthetic-webhook-secret')
        raw = json.dumps(event, sort_keys=True, separators=(',', ':')).encode()
        result = self.client.post('/payments/webhook/mock', data=raw, content_type='application/json',
                                  headers={'X-AgencyOS-Signature': signature})
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.json['result'], 'Applied')
        self.assertEqual(self.rows('p7_invoices')[-1]['status'], 'Paid (test)')
        duplicate = self.client.post('/payments/webhook/mock', data=raw, content_type='application/json',
                                     headers={'X-AgencyOS-Signature': signature})
        self.assertEqual(duplicate.json['result'], 'Duplicate')
        self.assertEqual(len(self.rows('p7_payments')), 2)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_invoice_and_payment_events_are_owner_scoped_and_signed(self):
        self.configure_billing()
        invoice = self.approve(self.draft())
        self.post(f"/invoices/{invoice['id']}/payment-link", {})
        token = self.rows('p7_payment_links')[-1]['token']
        with self.client.session_transaction() as session:
            session['user_id'] = 999
        self.assertEqual(self.client.get(f"/invoices/{invoice['id']}/pdf").status_code, 404)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        event = dict(id='bad-signature-event', type='payment.succeeded', data={'object': {
            'id':'bad-transaction','invoice_id':invoice['id'],'amount':invoice['total_cents'],'currency':'aud'}})
        raw = json.dumps(event, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(self.client.post('/payments/webhook/mock', data=raw, content_type='application/json',
                                          headers={'X-AgencyOS-Signature':'invalid'}).status_code, 400)
        self.assertEqual(len(self.rows('p7_payments')), 0)
        self.assertEqual(self.client.get(f'/payments/mock/{token}').status_code, 200)

    def test_gst_must_match_accepted_quote_and_duplicate_draft_is_blocked(self):
        self.configure_billing(gst_mode='registered_10')
        quote = self.accepted_quote()
        before = len(self.rows('p7_invoices'))
        self.post('/invoices/draft', {'quote_id': str(quote['id']), 'cycle':'one-off'})
        self.assertEqual(len(self.rows('p7_invoices')), before)
        self.configure_billing(gst_mode='not_registered')
        invoice = self.draft(quote)
        self.post('/invoices/draft', {'quote_id': str(quote['id']), 'cycle':'one-off'})
        self.assertEqual(len(self.rows('p7_invoices')), 1)
        self.assertEqual(invoice['currency'], 'AUD')

    def test_bank_configuration_is_encrypted_at_rest_and_absent_by_default(self):
        self.configure_billing(account_name='Synthetic Example', bsb='000-000', account_number='00000000')
        control = self.rows('p7_control')[0]
        self.assertNotIn('Synthetic Example', control['bank_ciphertext'])
        plain = billing.Fernet(self.bank_key.encode()).decrypt(control['bank_ciphertext'].encode())
        self.assertEqual(json.loads(plain)['account_number'], '00000000')
        self.assertNotIn(b'00000000', self.client.get('/invoices').data)

    def test_stripe_signature_timestamp_and_payload_validation(self):
        body = b'{"id":"evt_test","type":"payment_intent.succeeded"}'
        timestamp = int(time.time())
        expected = hmac.new(b'whsec_synthetic', str(timestamp).encode()+b'.'+body, hashlib.sha256).hexdigest()
        header = f't={timestamp},v1={expected}'
        self.assertTrue(billing.verify_stripe(body, header, 'whsec_synthetic', now=timestamp))
        self.assertFalse(billing.verify_stripe(body, header, 'wrong', now=timestamp))
        self.assertFalse(billing.verify_stripe(body, header, 'whsec_synthetic', now=timestamp+500))

    def test_live_stripe_key_is_rejected_without_network_call(self):
        self.configure_billing(provider='stripe_test')
        invoice = self.approve(self.draft())
        with patch.dict(os.environ, {'AGENCYOS_STRIPE_TEST_SECRET_KEY':'sk_live_must_never_be_used'}), \
             patch('payment_provider.urlopen', side_effect=AssertionError('no live provider calls')):
            self.post(f"/invoices/{invoice['id']}/payment-link", {})
        self.assertEqual(len(self.rows('p7_payment_links')),0)

    def test_stripe_test_checkout_adapter_uses_only_test_session_fields(self):
        from unittest.mock import MagicMock
        invoice={'id':4,'synthetic':1,'total_cents':12345,'currency':'AUD','invoice_number':'TEST-INV-2026-0004'}
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'id':'cs_test_123','url':'https://checkout.stripe.com/c/pay/cs_test_123'}).encode()
        with patch.dict(os.environ,{'AGENCYOS_STRIPE_TEST_SECRET_KEY':'sk_test_synthetic'}), patch('payment_provider.urlopen',return_value=response) as send:
            result=payment_provider.create_stripe_test_checkout(invoice,'http://127.0.0.1:5000/invoices','http://127.0.0.1:5000/invoices')
        request=send.call_args.args[0]
        self.assertEqual(result['provider_id'],'cs_test_123')
        self.assertEqual(request.get_header('Idempotency-key'),'agencyos-invoice-4')
        body=request.data.decode()
        self.assertIn('unit_amount%5D=12345',body)
        self.assertIn('metadata%5Bagencyos_invoice_id%5D=4',body)

    def test_reminders_are_local_drafts_and_owner_receipts_are_separate(self):
        self.configure_billing()
        invoice=self.approve(self.draft())
        self.post(f"/invoices/{invoice['id']}/reminder",{'kind':'due_soon'})
        reminder=self.rows('p7_reminders')[0]
        self.assertEqual(reminder['status'],'Draft')
        self.post(f"/invoices/{invoice['id']}/reconcile",{'amount_cents':str(invoice['total_cents']),'reference':'synthetic receipt evidence'})
        payment=self.rows('p7_payments')[0]
        self.assertEqual(payment['source'],'owner_reconciled')
        self.assertEqual(self.rows('p7_invoices')[0]['status'],'Owner reconciled (test)')
        self.assertEqual(self.client.get('/').status_code,200)

    def test_verified_refund_and_dispute_update_synthetic_invoice_state(self):
        self.configure_billing()
        invoice=self.approve(self.draft())
        paid=dict(id='paid-for-refund',type='payment.succeeded',data={'object':{
            'id':'txn-for-refund','invoice_id':invoice['id'],'amount':invoice['total_cents'],'currency':'aud'}})
        raw=json.dumps(paid,sort_keys=True,separators=(',',':')).encode()
        self.client.post('/payments/webhook/mock',data=raw,content_type='application/json',headers={'X-AgencyOS-Signature':billing.sign_mock(paid,'synthetic-webhook-secret')})
        self.assertEqual(self.rows('p7_invoices')[0]['status'],'Paid (test)')
        refund=dict(id='refund-event',type='charge.refunded',data={'object':{
            'id':'charge-for-refund','invoice_id':invoice['id'],'amount':invoice['total_cents'],
            'amount_refunded':invoice['total_cents'],'currency':'aud','status':'succeeded'}})
        raw=json.dumps(refund,sort_keys=True,separators=(',',':')).encode()
        response=self.client.post('/payments/webhook/mock',data=raw,content_type='application/json',headers={'X-AgencyOS-Signature':billing.sign_mock(refund,'synthetic-webhook-secret')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.rows('p7_invoices')[0]['status'],'Refunded (test)')


if __name__ == '__main__':
    unittest.main()

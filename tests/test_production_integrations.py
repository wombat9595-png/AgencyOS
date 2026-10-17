import base64
import json
import time
import unittest
from datetime import datetime,timezone,timedelta
from contextlib import closing
from unittest.mock import Mock
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
import app as application
import test_agencyos as fixtures
import discovery_preparation as discovery
import email_preparation as email
from phase3_store import connect,WorkflowError


class IntegrationPreparationTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def sender(self):
        records={('mail.agency.example','TXT'):['v=spf1 include:amazonses.com -all'],('_dmarc.agency.example','TXT'):['v=DMARC1; p=reject;'],('abc._domainkey.agency.example','CNAME'):['abc.dkim.amazonses.com.']}
        identity=dict(VerificationStatus='SUCCESS',DkimAttributes={'Status':'SUCCESS','Tokens':['abc']},MailFromAttributes={'MailFromDomain':'mail.agency.example','MailFromDomainStatus':'SUCCESS'})
        return email.check_sender('agency.example',identity,lambda name,kind:records.get((name,kind),[]))

    def test_sender_authentication_requires_provider_and_dns_evidence(self):
        self.assertTrue(self.sender()['ready'])
        result=email.check_sender('agency.example',{},lambda *a:[])
        self.assertFalse(result['ready'])
        self.assertFalse(result['checks']['dkim'])

    def test_ses_sdk_contract_is_simulator_only_and_defaults_to_no_requests(self):
        client=Mock();client.send_email.return_value={'MessageId':'synthetic-ses-id'}
        message=dict(sender='owner@agency.example',recipient='success@simulator.amazonses.com',subject='Synthetic only',body='Test body')
        with self.assertRaises(WorkflowError):email.SesSimulatorAdapter(client).submit(message,self.sender(),'https://agency.example/unsubscribe/fixture','Fictional identity/contact')
        self.assertFalse(client.send_email.called)
        adapter=email.SesSimulatorAdapter(client,allow_sandbox_requests=True)
        receipt=adapter.submit(message,self.sender(),'https://agency.example/unsubscribe/fixture','Fictional identity/contact')
        self.assertFalse(receipt['live'])
        self.assertIn(b'List-Unsubscribe-Post',client.send_email.call_args.kwargs['Content']['Raw']['Data'])
        message['recipient']='real@example.com'
        with self.assertRaises(WorkflowError):adapter.submit(message,self.sender(),'https://agency.example/unsubscribe/fixture','Fictional identity/contact')
        self.assertEqual(client.send_email.call_count,1)

    def test_sns_signature_topic_expiry_and_certificate_origin(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.now(timezone.utc)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic SNS fixture')])
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).sign(key,hashes.SHA256())
        envelope=dict(Type='Notification',TopicArn='arn:aws:sns:ap-southeast-2:000000000000:fixture',SignatureVersion='2',SigningCertURL='https://sns.ap-southeast-2.amazonaws.com/SimpleNotificationService-fixture.pem',MessageId='fixture-event',Timestamp=now.isoformat(),Message=json.dumps({'eventType':'Bounce'}))
        canonical=''.join(field+'\n'+envelope[field]+'\n' for field in ['Message','MessageId','Timestamp','TopicArn','Type']).encode()
        envelope['Signature']=base64.b64encode(key.sign(canonical,padding.PKCS1v15(),hashes.SHA256())).decode()
        loader=Mock(return_value=cert.public_bytes(serialization.Encoding.PEM))
        self.assertEqual(email.verify_sns(envelope,envelope['TopicArn'],loader)['eventType'],'Bounce')
        envelope['Message']='{}'
        with self.assertRaises(WorkflowError):email.verify_sns(envelope,envelope['TopicArn'],loader)
        envelope['SigningCertURL']='https://127.0.0.1/cert.pem';loader.reset_mock()
        with self.assertRaises(WorkflowError):email.verify_sns(envelope,envelope['TopicArn'],loader)
        self.assertFalse(loader.called)

    def test_one_click_unsubscribe_works_paused_without_login_and_is_idempotent(self):
        with closing(connect(application.DB_PATH)) as conn,conn:
            token=email.unsubscribe_token(conn,1,'recipient@example.invalid')
            conn.execute('UPDATE p4_control SET paused=1')
        self.assertEqual(self.client.get('/unsubscribe/'+token).status_code,200)
        self.assertEqual(len(self.rows('p5_suppressions')),0)
        with self.client.session_transaction() as session:session['user_id']=999
        for _ in range(2):
            self.assertEqual(self.client.post('/unsubscribe/'+token,data={'List-Unsubscribe':'One-Click'}).status_code,200)
        self.assertEqual(len(self.rows('p5_suppressions')),1)
        self.assertNotIn(token,json.dumps([dict(r) for r in self.rows('prep_unsubscribe')]))

    def test_abn_fixture_and_geographic_dataset_filters_never_infer_contact_consent(self):
        raw=b'<ABR><ABN>00000000000</ABN><MainEntity><NonIndividualName><NonIndividualNameText>Fictional ACT Company</NonIndividualNameText></NonIndividualName></MainEntity><BusinessAddress><AddressDetails><State>ACT</State><Postcode>2600</Postcode></AddressDetails></BusinessAddress></ABR>'
        candidate=discovery.parse_abn_fragment(raw)[0]
        self.assertEqual(candidate['state'],'ACT');self.assertEqual(candidate['city'],'');self.assertFalse(candidate['marketing_consent'])
        with self.assertRaises(WorkflowError):discovery.parse_abn_fragment(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><ABR/>')
        csv=b'source_id,source_url,observed_at,business_name,state,city,industry\nfixture,https://source.example/1,2020-01-01T00:00:00+00:00,Fictional,ACT,Canberra,Design\n'
        self.assertEqual(len(discovery.filter_authorized_csv(csv,discovery.DEFAULTS)['candidates']),1)
        plan=dict(discovery.DEFAULTS,cities=['Sydney'])
        self.assertEqual(discovery.filter_authorized_csv(csv,plan)['candidates'],[])

    def test_expired_consent_and_suppression_block_future_contact_readiness(self):
        with closing(connect(application.DB_PATH)) as conn,conn:
            conn.execute("INSERT INTO p5_contact_basis VALUES(1,'prospect@example.com','consent','Synthetic consent','2020','2000-01-01')")
            self.assertFalse(email.recipient_readiness(conn,1,'prospect@example.com')[0])
            conn.execute("UPDATE p5_contact_basis SET expires_on='2999-01-01'")
            self.assertTrue(email.recipient_readiness(conn,1,'prospect@example.com')[0])
            __import__('sales_email').suppress(conn,1,'prospect@example.com','Synthetic opt-out')
            self.assertFalse(email.recipient_readiness(conn,1,'prospect@example.com')[0])

"""Phase 9 contact eligibility evidence remains owner-attested and non-executing."""
import unittest

import test_phase5 as fixtures


class ContactEligibilityEvidenceTest(unittest.TestCase):
    setUp=fixtures.SalesTest.setUp
    tearDown=fixtures.SalesTest.tearDown
    post=fixtures.SalesTest.post
    rows=fixtures.SalesTest.rows
    settings=fixtures.SalesTest.settings
    package=fixtures.SalesTest.package
    new=fixtures.SalesTest.new

    def test_owner_can_record_normalized_basis_with_evidence_and_expiry(self):
        self.new()
        response=self.post('/sales/contact-basis',dict(flow_id='1',email='PROSPECT@EXAMPLE.COM',basis_type='consent',
            evidence_reference='Synthetic fixture: consent record #17',expires_on='2027-01-15',attest='yes'))
        self.assertEqual(response.status_code,302)
        item=self.rows('p5_contact_basis')[0]
        self.assertEqual(item['email'],'prospect@example.com')
        self.assertEqual(item['basis_type'],'consent')
        self.assertEqual(item['evidence_reference'],'Synthetic fixture: consent record #17')
        self.assertEqual(item['expires_on'],'2027-01-15')
        page=self.client.get('/sales/1')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'not independently verify legal basis',page.data)
        self.assertIn(b'no permission to send inferred',page.data)

    def test_contact_basis_requires_evidence_and_owner_attestation(self):
        self.new()
        for fields in (
            dict(flow_id='1',email='prospect@example.com',basis_type='consent',evidence_reference='',attest='yes'),
            dict(flow_id='1',email='prospect@example.com',basis_type='consent',evidence_reference='record',attest='no'),
            dict(flow_id='1',email='prospect@example.com',basis_type='unknown',evidence_reference='record',attest='yes'),
            dict(flow_id='1',email='prospect@example.com',basis_type='consent',evidence_reference='record',expires_on='not-a-date',attest='yes'),
        ):
            self.post('/sales/contact-basis',fields)
        self.assertEqual(len(self.rows('p5_contact_basis')),0)

    def test_contact_basis_route_is_scoped_to_owned_sales_workflow(self):
        self.new()
        response=self.post('/sales/contact-basis',dict(flow_id='999',email='prospect@example.com',basis_type='consent',evidence_reference='record',attest='yes'))
        self.assertEqual(response.status_code,404)
        self.assertEqual(len(self.rows('p5_contact_basis')),0)


if __name__=='__main__':
    unittest.main()

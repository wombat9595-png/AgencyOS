from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import app as application
from lead_finder import parse_csv, validate_lead
from ai_drafts import generate_draft, DraftError

class AgencyOSTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = application.DB_PATH
        application.DB_PATH = str(Path(self.temp.name) / 'test.db')
        application.app.config.update(TESTING=True, SECRET_KEY='test-only')
        application.init_db()
        self.client = application.app.test_client()
        self.post('/setup', {'username': 'owner', 'password': 'synthetic-password-123'})
        self.post('/login', {'username': 'owner', 'password': 'synthetic-password-123'})

    def tearDown(self):
        application.DB_PATH = self.old_path
        self.temp.cleanup()

    def post(self, path, data=None, **kwargs):
        with self.client.session_transaction() as session:
            session.setdefault('csrf_token', 'test-form-token')
            token = session['csrf_token']
        data = dict(data or {}, csrf_token=token)
        response = self.client.post(path, data=data, **kwargs)
        response.request.close()
        response.request.environ['wsgi.input'].close()
        return response

    def rows(self, table):
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute('SELECT * FROM ' + table).fetchall()

    def upload(self, text, source='Synthetic research'):
        return self.post('/lead-finder', {'source': source, 'csv_file': (io.BytesIO(text.encode()), 'leads.csv')}, content_type='multipart/form-data')

    def test_existing_workflows(self):
        for path in ('/', '/leads', '/outreach', '/quotes', '/invoices', '/projects', '/settings', '/lead-finder'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.post('/leads', {'business_name': 'Synthetic Studio', 'email': 'alex@example.com', 'website': 'https://example.com'})
        lead = self.rows('leads')[0]
        self.post('/quotes', {'client_name': 'Synthetic Studio', 'title': 'Website', 'amount': '1200.55', 'lead_id': str(lead['id'])})
        self.post('/invoices', {'client_name': 'Synthetic Studio', 'reference': 'TEST-1', 'amount': '100.50'})
        self.post('/projects', {'client_name': 'Synthetic Studio', 'project_name': 'Test site'})
        self.post('/quotes/1/status', {'status': 'Accepted'})
        self.post('/invoices/1/status', {'status': 'Paid'})
        self.post('/projects/1/status', {'status': 'Delivered'})
        self.assertEqual(self.rows('quotes')[0]['amount_cents'], 120055)
        self.assertEqual(self.rows('quotes')[0]['status'], 'Accepted')
        self.assertEqual(self.rows('invoices')[0]['status'], 'Paid')
        self.assertEqual(self.rows('projects')[0]['status'], 'Delivered')
        response = self.post('/outreach', {'lead_id': str(lead['id']), 'offer': 'a helpful website', 'tone': 'friendly'})
        self.assertIn(b'Subject: Quick idea for Synthetic Studio', response.data)
        self.assertIn(b'Synthetic Studio', self.client.get('/').data)
        self.post('/leads/1/delete')
        self.assertEqual(len(self.rows('leads')), 0)
        self.assertIsNone(self.rows('quotes')[0]['lead_id'])

    def test_authentication_and_csrf(self):
        self.assertEqual(self.client.post('/leads', data={'business_name': 'Forbidden'}).status_code, 400)
        self.post('/logout')
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/lead-finder').status_code, 302)
        response = self.post('/login', {'username': 'owner', 'password': 'wrong'})
        self.assertIn(b'Invalid username or password', response.data)
        self.assertEqual(self.post('/login', {'username': 'owner', 'password': 'synthetic-password-123'}).status_code, 302)
        self.assertEqual(self.client.get('/setup').status_code, 302)

    def test_preview_confirm_replay_and_validation(self):
        response = self.upload('business_name,contact_name,email,website,industry,location\nSynthetic One,Alex,alex@example.com,https://example.com,Design,Sydney\nBad,,invalid,javascript:alert(1),Design,Sydney\nSynthetic One,Alex,alex@example.com,https://www.example.com,Design,Sydney\n')
        preview = response.location
        self.assertEqual(len(self.rows('leads')), 0)
        page = self.client.get(preview)
        self.assertIn(b'2 valid', page.data)
        self.assertIn(b'1 rejected', page.data)
        self.assertIn(b'CSV row 1', page.data)
        result = self.post(preview, {'selected': ['1','2','3']}, follow_redirects=True)
        self.assertIn(b'1 imported, 1 rejected (invalid), 1 skipped', result.data)
        lead = self.rows('leads')[0]
        self.assertEqual(lead['location'], 'Sydney')
        self.assertEqual(lead['source'], 'Synthetic research')
        self.assertTrue(lead['created_at'])
        self.post(preview, {'selected': ['1']})
        self.assertEqual(len(self.rows('leads')), 1)

    def test_explicit_duplicate_review(self):
        self.post('/leads', {'business_name': 'Existing', 'email': 'same@example.com'})
        response = self.upload('business_name,email\nAnother,same@example.com\n')
        self.assertIn(b'Existing lead #1: email', self.client.get(response.location).data)
        self.post(response.location, {'selected': ['1'], 'allow_duplicate': ['1']})
        self.assertEqual(len(self.rows('leads')), 2)

    def test_duplicate_added_after_preview(self):
        response = self.upload('business_name\nLater\n')
        self.post('/leads', {'business_name': 'Later'})
        self.post(response.location, {'selected': ['1']})
        self.assertEqual(len(self.rows('leads')), 1)

    def test_search_filters_and_status(self):
        self.post('/leads', {'business_name': 'Synthetic 100%', 'industry': 'Design', 'location': 'Sydney', 'source': 'Research'})
        self.post('/leads', {'business_name': 'Other'})
        self.assertIn(b'Synthetic 100%', self.client.get('/leads?q=100%25&industry=Design&location=Sydney&source=Research').data)
        self.assertNotIn(b'<strong>Other</strong>', self.client.get('/leads?industry=Design').data)
        self.assertEqual(self.post('/leads/1/status', {'status': 'Interested'}).status_code, 302)
        self.assertEqual(self.rows('leads')[0]['status'], 'Interested')
        self.assertEqual(self.post('/leads/1/status', {'status': 'invalid'}).status_code, 400)
        self.assertEqual(self.post('/leads/999/status', {'status': 'New'}).status_code, 404)
        self.assertEqual(self.client.get("/leads?q=' OR 1=1 --").status_code, 200)

    def test_bad_uploads(self):
        for text in ('', 'email\na@example.com\n', 'business_name,business_name\nA,B\n', 'business_name,email\nA,a@example.com,extra\n', 'business_name,email\nA\n'):
            response = self.upload(text)
            self.assertIn(response.status_code, (200,302))
            if response.status_code == 302:
                self.assertIn(b'Rejected', self.client.get(response.location).data)
        self.assertEqual(len(self.rows('leads')), 0)
        response = self.post('/lead-finder', {'source': 'Test', 'csv_file': (io.BytesIO(b'\xff'), 'bad.csv')})
        self.assertIn(b'UTF-8', response.data)
        response = self.upload('business_name\n' + 'A\n' * 1001)
        self.assertIn(b'at most 1,000', response.data)
        response = self.upload('business_name\n' + 'A' * (2 * 1024 * 1024))
        self.assertEqual(response.status_code, 413)
        self.assertIn(b'too large', response.data)

    def test_expired_and_foreign_preview(self):
        response = self.upload('business_name\nSynthetic\n')
        with self.client.session_transaction() as session:
            session['user_id'] = 999
        self.assertEqual(self.client.get(response.location).status_code, 404)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.execute('UPDATE lead_imports SET created_at=0')
        self.assertEqual(self.post(response.location, {'selected': ['1']}).status_code, 302)
        self.assertEqual(len(self.rows('leads')), 0)

    def test_migration_preserves_legacy_records(self):
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            conn.execute('DROP TABLE leads')
            conn.execute("CREATE TABLE leads(id INTEGER PRIMARY KEY, business_name TEXT NOT NULL,contact_name TEXT DEFAULT '',email TEXT DEFAULT '',website TEXT DEFAULT '',industry TEXT DEFAULT '',status TEXT DEFAULT 'New',notes TEXT DEFAULT '',created_at TEXT NOT NULL)")
            conn.execute("INSERT INTO leads(id,business_name,created_at) VALUES(42,'Legacy','2024-01-01')")
            conn.execute("INSERT INTO quotes(lead_id,client_name,title,amount_cents,status,notes,created_at) VALUES(42,'Legacy','Legacy quote',25000,'Accepted','Keep','2024-01-01')")
            conn.execute("INSERT INTO invoices(client_name,reference,amount_cents,status,due_date,notes,created_at) VALUES('Legacy','OLD-1',25000,'Paid','','Keep','2024-01-01')")
            conn.execute("INSERT INTO projects(client_name,project_name,status,due_date,website_url,notes,created_at) VALUES('Legacy','Legacy site','Delivered','','','Keep','2024-01-01')")
        preserved = {table: [tuple(r) for r in self.rows(table)] for table in ('users','quotes','invoices','projects')}
        before = self.rows('users')[0]['password_hash']
        application.init_db(); application.init_db()
        lead = self.rows('leads')[0]
        self.assertEqual((lead['id'], lead['business_name'], lead['created_at']), (42,'Legacy','2024-01-01'))
        self.assertEqual(lead['location'], '')
        for table, records in preserved.items():
            self.assertEqual([tuple(r) for r in self.rows(table)], records)
        self.assertEqual(self.rows('users')[0]['password_hash'], before)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_missing_ai_configuration(self):
        self.post('/leads', {'business_name': 'Synthetic'})
        with patch.dict(os.environ, {}, clear=True):
            response = self.post('/outreach', {'lead_id': '1', 'draft_mode': 'ai', 'approve_ai': 'yes'})
        self.assertIn(b'AI drafting is not configured', response.data)
        self.assertNotIn(b'Subject: Quick idea', response.data)

    def test_ai_route_uses_selected_lead_and_stays_draft_only(self):
        self.post('/leads', {'business_name': 'Synthetic', 'location': 'Sydney'})
        with patch('app.generate_draft', return_value='Subject: Reviewed synthetic draft') as provider:
            response = self.post('/outreach', {'lead_id': '1', 'draft_mode': 'ai', 'approve_ai': 'yes', 'offer': 'Website design', 'tone': 'professional'})
        self.assertIn(b'Subject: Reviewed synthetic draft', response.data)
        self.assertIn(b'Not sent', response.data)
        self.assertEqual(provider.call_args.args[0]['location'], 'Sydney')
        self.assertEqual(provider.call_args.args[1:], ('Website design', 'professional'))

    def test_unselected_import_and_invalid_tone(self):
        response = self.upload('business_name\nSynthetic\n')
        result = self.post(response.location, {}, follow_redirects=True)
        self.assertIn(b'0 imported, 0 rejected (invalid), 1 skipped', result.data)
        self.assertEqual(len(self.rows('leads')), 0)
        self.post('/leads', {'business_name': 'Synthetic'})
        response = self.post('/outreach', {'lead_id': '1', 'tone': 'unsupported'})
        self.assertIn(b'Choose a supported tone', response.data)
        self.assertNotIn(b'Subject: Quick idea', response.data)

    def test_nonfinite_money_and_manual_validation(self):
        for amount in ('NaN','Infinity','-1','invalid'):
            self.post('/quotes', {'client_name': 'Synthetic', 'title': 'Test', 'amount': amount})
            self.post('/invoices', {'client_name': 'Synthetic', 'reference': 'Test', 'amount': amount})
        self.assertEqual(len(self.rows('quotes')), 0)
        self.assertEqual(len(self.rows('invoices')), 0)
        self.post('/leads', {'business_name': 'Invalid', 'website': 'javascript:alert(1)'})
        self.assertEqual(len(self.rows('leads')), 0)

    def test_escape_untrusted_csv(self):
        response = self.upload('business_name\n<script>alert(1)</script>\n')
        page = self.client.get(response.location)
        self.assertIn(b'&lt;script&gt;', page.data)
        self.assertNotIn(b'<script>alert', page.data)

    def test_sample_csv_and_empty_contact_fields(self):
        response = self.client.get('/lead-finder/sample.csv')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'location,source', response.data)
        rows = parse_csv(b'\xef\xbb\xbfbusiness name,location\nSynthetic,Sydney\n', 'Research', [])
        self.assertEqual(rows[0]['errors'], [])
        self.assertTrue(validate_lead({'business_name':'A','status':'Bogus'})[1])

class ProviderTest(unittest.TestCase):
    def test_mock_provider_success_and_errors(self):
        config = {'AGENCYOS_AI_PROVIDER':'openai-compatible','AGENCYOS_AI_API_KEY':'synthetic-key','AGENCYOS_AI_ENDPOINT':'https://provider.example/chat/completions','AGENCYOS_AI_MODEL':'test-model'}
        lead = {k: 'Synthetic' for k in ('business_name','contact_name','industry','location','website')}
        # Test the transport in isolation; Phase 5 grant enforcement has separate tests.
        with patch.dict(os.environ,config), patch('sales_ai.require_grant'), patch('ai_drafts.request.build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = json.dumps({'choices':[{'message':{'content':'Subject: Synthetic\nDraft'}}]}).encode()
            self.assertEqual(generate_draft(lead,'Offer','friendly'),'Subject: Synthetic\nDraft')
            req = opener.return_value.open.call_args.args[0]
            self.assertNotIn(b'synthetic-key',req.data)
            response.read.return_value = b'{}'
            with self.assertRaisesRegex(DraftError,'unexpected response'):
                generate_draft(lead,'Offer','friendly')
            from urllib.error import HTTPError, URLError
            opener.return_value.open.side_effect = HTTPError(config['AGENCYOS_AI_ENDPOINT'],401,'error',{},None)
            with self.assertRaisesRegex(DraftError,'HTTP 401'):
                generate_draft(lead,'Offer','friendly')
            opener.return_value.open.side_effect = URLError('synthetic-key')
            with self.assertRaisesRegex(DraftError,'could not be reached'):
                generate_draft(lead,'Offer','friendly')
        with patch.dict(os.environ,dict(config,AGENCYOS_AI_ENDPOINT='http://provider.example')):
            with self.assertRaisesRegex(DraftError,'HTTPS'):
                generate_draft(lead,'Offer','friendly')

if __name__ == '__main__':
    unittest.main()

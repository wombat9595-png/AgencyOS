"""Existing-account recovery using fictional records; no Mac credentials needed."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from werkzeug.security import check_password_hash,generate_password_hash
import app as application
import test_agencyos as fixtures
import owner_recovery as recovery

PASSWORD='Fictional-recovery-password-12345'


class OwnerRecoveryTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def reset(self,**changes):
        fields=dict(database=application.DB_PATH,password=PASSWORD,backup_root=Path(self.temp.name)/'private-backups',expected_owner=(1,'owner'))
        fields.update(changes);return recovery.reset_owner(**fields)

    def test_existing_owner_password_reset_preserves_records_and_other_accounts(self):
        self.post('/leads',dict(business_name='Fictional preserved client'))
        with closing(sqlite3.connect(application.DB_PATH)) as conn,conn:
            conn.execute("INSERT INTO users(username,password_hash,created_at) VALUES('CEO',?,'fixture')",(generate_password_hash('other-fictional-password'),))
            other=conn.execute('SELECT * FROM users WHERE id=2').fetchone()
            conn.execute("INSERT INTO projects(client_name,project_name,status,created_at) VALUES('Fictional client','Preserved project','Planning','fixture')")
        leads=[dict(r) for r in self.rows('leads')];projects=[dict(r) for r in self.rows('projects')]
        result=self.reset()
        self.assertEqual(result['username'],'owner');self.assertEqual(len(self.rows('users')),2)
        self.assertEqual([dict(r) for r in self.rows('leads')],leads);self.assertEqual([dict(r) for r in self.rows('projects')],projects)
        with closing(sqlite3.connect(application.DB_PATH)) as conn:self.assertEqual(conn.execute('SELECT * FROM users WHERE id=2').fetchone(),other)
        self.assertTrue(check_password_hash(self.rows('users')[0]['password_hash'],PASSWORD))
        self.assertNotIn(PASSWORD,json.dumps(result));self.assertEqual(len(self.rows('owner_recovery_events')),1)
        self.post('/logout')
        self.post('/login',dict(username='owner',password=PASSWORD))
        self.assertEqual(self.client.get('/launch').status_code,200)

    def test_ceo_is_recovered_when_it_is_the_actual_owner(self):
        with closing(sqlite3.connect(application.DB_PATH)) as conn,conn:conn.execute("UPDATE users SET username='CEO' WHERE id=1")
        result=self.reset(expected_owner=(1,'CEO'))
        self.assertEqual(result['username'],'CEO')
        self.post('/logout');self.post('/login',dict(username='CEO',password=PASSWORD))
        self.assertEqual(self.client.get('/launch').status_code,200)

    def test_cookie_from_another_account_does_not_block_valid_owner_login(self):
        self.reset()
        with self.client.session_transaction() as session:session['user_id']=999
        self.post('/login',dict(username='owner',password=PASSWORD))
        self.assertEqual(self.client.get('/launch').status_code,200)

    def test_old_password_and_old_logged_in_session_are_rejected(self):
        self.assertEqual(self.client.get('/launch').status_code,200)
        self.reset()
        self.assertEqual(self.client.get('/launch').status_code,302)
        self.post('/login',dict(username='owner',password='synthetic-password-123'))
        self.assertEqual(self.client.get('/launch').status_code,302)
        self.post('/login',dict(username='owner',password=PASSWORD))
        self.assertEqual(self.client.get('/launch').status_code,200)

    def test_login_throttle_is_cleared_by_local_recovery(self):
        for _ in range(6):self.post('/login',dict(username='owner',password='wrong'))
        self.assertTrue(self.rows('security_rate'));self.reset()
        self.assertEqual(len(self.rows('security_rate')),0)
        self.post('/login',dict(username='owner',password=PASSWORD))
        self.assertEqual(self.client.get('/launch').status_code,200)

    def test_encrypted_snapshot_contains_exact_pre_reset_accounts_and_records(self):
        before=self.rows('users')[0]['password_hash'];result=self.reset()
        blob=Path(result['backup']).read_bytes();self.assertNotIn(b'SQLite format',blob)
        raw=Fernet(Path(result['key_file']).read_bytes()).decrypt(blob)
        target=Path(self.temp.name)/'backup-check.sqlite3';target.write_bytes(raw)
        with closing(sqlite3.connect(target)) as conn:
            self.assertEqual(conn.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0],before)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(Path(result['backup']).stat().st_mode&0o777,0o600)
        self.assertEqual(Path(result['key_file']).stat().st_mode&0o777,0o600)

    def test_backup_failure_or_wrong_owner_never_changes_password(self):
        original=self.rows('users')[0]['password_hash']
        with patch('owner_recovery.backup_database',side_effect=OSError('Synthetic backup failure')):
            with self.assertRaises(OSError):self.reset()
        with self.assertRaises(ValueError):self.reset(expected_owner=(99,'CEO'))
        self.assertEqual(self.rows('users')[0]['password_hash'],original)

    def test_missing_empty_and_unrelated_databases_do_not_create_accounts(self):
        missing=Path(self.temp.name)/'missing.db'
        with self.assertRaises(ValueError):self.reset(database=missing)
        self.assertFalse(missing.exists())
        wrong=Path(self.temp.name)/'unrelated.db'
        with closing(sqlite3.connect(wrong)) as conn,conn:conn.execute('CREATE TABLE data(value TEXT)')
        before=wrong.read_bytes()
        with self.assertRaises(ValueError):self.reset(database=wrong)
        self.assertEqual(wrong.read_bytes(),before)
        with closing(sqlite3.connect(application.DB_PATH)) as conn,conn:conn.execute('DELETE FROM users')
        with self.assertRaisesRegex(ValueError,'no owner'):self.reset()
        self.assertEqual(len(self.rows('users')),0)

    def test_invalid_password_never_mutates_database(self):
        original=Path(application.DB_PATH).read_bytes()
        for value in ('short',' '*16,'long-password-with\nnewline',None):
            with self.assertRaises(ValueError):self.reset(password=value)
        self.assertEqual(Path(application.DB_PATH).read_bytes(),original)

    def test_legacy_phase2_schema_needs_no_application_migration(self):
        path=Path(self.temp.name)/'legacy.db'
        with closing(sqlite3.connect(path)) as conn,conn:
            conn.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,password_hash TEXT);CREATE TABLE leads(id INTEGER PRIMARY KEY,business_name TEXT);CREATE TABLE projects(id INTEGER PRIMARY KEY,project_name TEXT);")
            conn.execute("INSERT INTO users VALUES(7,'CEO',?)",(generate_password_hash('old-fictional-password'),))
            conn.execute("INSERT INTO leads VALUES(3,'Fictional original')")
        result=self.reset(database=path,expected_owner=(7,'CEO'))
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute('SELECT id,username FROM users').fetchall(),[(7,'CEO')])
            self.assertTrue(check_password_hash(conn.execute('SELECT password_hash FROM users').fetchone()[0],PASSWORD))
            self.assertEqual(conn.execute('SELECT * FROM leads').fetchall(),[(3,'Fictional original')])
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='p5_flows'").fetchone())

    def test_inventory_is_read_only_and_keeps_distinct_workspaces_visible(self):
        source=Path(application.DB_PATH);before=source.read_bytes()
        other=Path(self.temp.name)/'other.db';other.write_bytes(before)
        results=recovery.find_databases([self.temp.name])
        self.assertEqual(len(results),2);self.assertEqual(source.read_bytes(),before)
        self.assertTrue(all(r['username']=='owner' for r in results))
        self.assertTrue(all('password_hash' not in json.dumps(r) for r in results))


if __name__=='__main__':unittest.main()

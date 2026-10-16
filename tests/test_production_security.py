import json
import os
import sqlite3
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from flask import Flask
from cryptography.fernet import Fernet,InvalidToken
import app as application
import test_agencyos as fixtures
import production_security as security
import production_ops as ops
from phase3_store import connect
from static_safety import static_errors


class ProductionSecurityTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def test_login_throttle_is_durable_and_forwarded_headers_cannot_bypass(self):
        for _ in range(4):self.post('/login',{'username':'owner','password':'wrong'})
        result=self.post('/login',{'username':'owner','password':'wrong'},headers={'X-Forwarded-For':'8.8.8.8'})
        self.assertEqual(result.status_code,429)
        self.assertEqual(result.headers['Retry-After'],'900')
        self.assertNotIn('owner',json.dumps([dict(row) for row in self.rows('security_rate')]))

    def test_invalid_installation_session_cannot_read_shared_records(self):
        with self.client.session_transaction() as session:session['user_id']=999
        self.assertEqual(self.client.get('/leads').status_code,404)

    def test_sessions_expire_and_security_headers_apply(self):
        with self.client.session_transaction() as session:session['authenticated_at']=time.time()-29000
        self.assertEqual(self.client.get('/leads').status_code,302)
        result=self.client.get('/login')
        self.assertEqual(result.headers['X-Content-Type-Options'],'nosniff')
        self.assertIn("object-src 'none'",result.headers['Content-Security-Policy'])

    def test_strict_production_config_requires_secrets_and_explicit_host_database(self):
        with patch.dict(os.environ,{'AGENCYOS_ENV':'production','AGENCYOS_SECRET_KEY':'','AGENCYOS_SECRET_KEY_FILE':''}):
            with self.assertRaises(RuntimeError):security.configure(Flask('invalid'))
        config=dict(AGENCYOS_ENV='production',AGENCYOS_SECRET_KEY='s'*64,AGENCYOS_SECRET_KEY_FILE='',AGENCYOS_DB='/isolated/test.sqlite3',AGENCYOS_TRUSTED_HOSTS='agencyos.example.invalid')
        with patch.dict(os.environ,config):
            app=Flask('configured');security.configure(app)
            self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
            self.assertEqual(app.config['TRUSTED_HOSTS'],['agencyos.example.invalid'])

    def test_encrypted_backup_restores_into_new_directory_and_rejects_tampering(self):
        self.post('/leads',{'business_name':'Synthetic Backup Studio'})
        root=Path(self.temp.name);key=Fernet.generate_key();out=root/'snapshot.enc'
        report=ops.backup(application.DB_PATH,out,key)
        self.assertGreater(report['bytes'],0)
        self.assertNotIn(b'Synthetic Backup Studio',out.read_bytes())
        restored=root/'restore';ops.restore(out,restored,key)
        with closing(sqlite3.connect(restored/'database.sqlite3')) as conn:
            self.assertEqual(conn.execute('SELECT business_name FROM leads').fetchone()[0],'Synthetic Backup Studio')
        with self.assertRaises(ValueError):ops.restore(out,restored,key)
        with self.assertRaises(FileExistsError):ops.backup(application.DB_PATH,out,key)
        raw=out.read_bytes();out.write_bytes(raw[:-6]+b'xxxxxx')
        with self.assertRaises(InvalidToken):ops.restore(out,root/'tampered',key)
        self.assertFalse((root/'tampered').exists())

    def test_operational_alerts_are_deduplicated_and_resolve_after_backup(self):
        ops.collect_alerts(application.DB_PATH);ops.collect_alerts(application.DB_PATH)
        self.assertEqual(len(self.rows('ops_alerts')),1)
        ops.backup(application.DB_PATH,Path(self.temp.name)/'backup.enc',Fernet.generate_key())
        ops.collect_alerts(application.DB_PATH)
        self.assertIsNotNone(self.rows('ops_alerts')[0]['resolved_at'])

    def test_static_boundary_rejects_event_attributes_external_resources_and_refresh(self):
        for html in ('<IMG SRC=x ONLOAD=alert(1)>','<iframe srcdoc="<script>x</script>"></iframe>',
                     '<meta http-equiv="refresh" content="0;url=https://example.com">','<style>@import "https://example.com";</style>'):
            self.assertTrue(static_errors(html),html)
        self.assertEqual(static_errors('<a href="services.html">Services</a>'),[])

    def test_health_endpoints_do_not_expose_database_path(self):
        self.assertEqual(self.client.get('/readyz').status_code,200)
        self.assertEqual(self.client.get('/healthz').json,{'status':'alive'})
        self.assertNotIn(application.DB_PATH,self.client.get('/readyz').get_data(as_text=True))

    def test_crashed_local_worker_recovers_without_repeating_external_work(self):
        import p8_ops
        with closing(connect(application.DB_PATH)) as conn,conn:
            conn.execute("INSERT INTO agent_tasks(user_id,agent_id,title,mode,status,snapshot_json,created_at,updated_at,started_at) VALUES(1,'lead-research','Expired local fixture','local','Running',?,'2000','2000',?)",(json.dumps(dict(business_name='Fixture',website='',industry='',location='Canberra')),time.time()-600))
        self.assertTrue(p8_ops.worker_once(application.DB_PATH))
        task=self.rows('agent_tasks')[0]
        self.assertEqual(task['status'],'Awaiting review')
        self.assertEqual(task['recovery_count'],1)
        self.assertTrue(task['run_token'])

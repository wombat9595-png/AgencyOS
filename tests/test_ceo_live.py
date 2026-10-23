"""CEO live page and the AI budget alert. No network, nothing sent."""
from contextlib import closing
from datetime import date,datetime
import os
import sqlite3
import time
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
import app as application
import autosend
import ceo_live
import test_agencyos as fixtures
import test_autosend
from test_autosend import WED_10AM



class CeoLiveTest(unittest.TestCase):
    for _name in ('setUp','tearDown','setUp_base','tearDown_base','post','rows','conn','connect_gmail','add','fake_send','tick','switch_on'):
        locals()[_name]=getattr(test_autosend.AutoSendTest,_name)
    def test_page_shows_status_numbers_and_the_feed(self):
        with self.conn() as conn:
            self.switch_on(conn)
            self.add(conn,'Fictional Builds','hello@fictionalbuilds.example');self.add(conn,'Fictional Pipes','hi@pipes.example')
            conn.execute("INSERT INTO prospects(owner_id,source_id,name,created_at) VALUES(1,'noemail','No Email Co','x')");conn.commit()
            self.tick(conn)
        with patch('autosend.now_local',return_value=WED_10AM):
            page=self.client.get('/ceo').get_data(as_text=True)
        self.assertIn('Auto-send is ON',page);self.assertIn('Next email at about',page)
        self.assertIn('CEO emailed',page);self.assertIn('Fictional Builds',page)
        self.assertIn('leads found',page);self.assertIn('have no email address',page)
        self.assertIn('Watch your CEO work',self.client.get('/business').get_data(as_text=True))
        with self.conn() as conn:
            n=ceo_live.leads(conn,1)
        self.assertEqual((n['total'],n['with_email'],n['emailed'],n['left'],n['ready']),(3,2,1,1,1))

    def test_finish_date_follows_the_warm_up(self):
        with self.conn() as conn:
            conn.execute('INSERT OR REPLACE INTO team_settings(owner_id,daily_drafts) VALUES(1,60)');conn.commit()
            d=date(2026,10,26)
            self.assertEqual(ceo_live.finish_date(conn,1,20,d),d)
            self.assertEqual(ceo_live.finish_date(conn,1,140+30,d),date(2026,11,2))  # a week of 20, then 30 on day 8

    def test_budget_alert_emails_once_a_month(self):
        sent=[]
        with self.conn() as conn:
            conn.execute('INSERT OR REPLACE INTO writer_settings(owner_id,ai_enabled,cap_cents) VALUES(1,1,500)');conn.commit()
            status=dict(enabled=True,ready=False,reason='',cap_cents=500,spent_cents=120,key_saved=True)
            with patch('smart_writer.ai_status',return_value=status):
                self.assertFalse(ceo_live.budget_alert(conn,1,send=lambda *a:sent.append(a)))
            status['spent_cents']=500
            with patch('smart_writer.ai_status',return_value=status),patch('pitch.ping',return_value=False):
                self.assertTrue(ceo_live.budget_alert(conn,1,send=lambda *a:sent.append(a),today=date(2026,10,23)))
                self.assertFalse(ceo_live.budget_alert(conn,1,send=lambda *a:sent.append(a),today=date(2026,10,29)))
                self.assertTrue(ceo_live.budget_alert(conn,1,send=lambda *a:sent.append(a),today=date(2026,11,2)))
        self.assertEqual(len(sent),2)
        _,_,to,subject,body=sent[0]
        self.assertIn('A$5.00',subject);self.assertIn(ceo_live.ANTHROPIC_BILLING,body);self.assertIn('/night-shift',body)


if __name__=='__main__':
    unittest.main()

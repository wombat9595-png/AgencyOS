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
        self.assertIn('leads found',page);self.assertIn('have no website and no email',page)
        self.assertNotIn('You emailed',page)
        self.assertIn('authuser=benji.price.webdesign@gmail.com#sent',page);self.assertIn('#all/',page)  # Gmail buttons and a link to the exact email  # an auto-send shows once, as "CEO emailed"
        self.assertIn('Watch your CEO work',self.client.get('/business').get_data(as_text=True))
        with self.conn() as conn:
            n=ceo_live.leads(conn,1)
        self.assertEqual((n['total'],n['with_email'],n['emailed'],n['left'],n['ready'],n['no_site']),(3,2,1,1,1,1))

    def test_feed_shows_each_thing_once_and_approved_drafts_are_explained(self):
        with self.conn() as conn:
            self.add(conn,'Fictional Pipes','hi@pipes.example')
            conn.execute("UPDATE prospects SET stage='Approved',gmail_draft_id='d1'");pid=conn.execute('SELECT id FROM prospects').fetchone()[0]
            for _ in range(2):conn.execute("INSERT INTO prospect_log(owner_id,prospect_id,on_date,action,detail,created_at) VALUES(1,?,'2026-10-23','approved','','2026-10-23T02:50:00+00:00')",(pid,))
            conn.commit()
            items=ceo_live.feed(conn,1)
        self.assertEqual([i['what'] for i in items],['You approved (in Gmail Drafts)'])
        page=self.client.get('/ceo').get_data(as_text=True)
        self.assertIn('1 emails you approved are sitting in Gmail Drafts',page)

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


    def test_inspector_reads_a_few_websites_a_minute_between_shifts(self):
        import night_shift
        with self.conn() as conn:
            for i in range(7):conn.execute("INSERT INTO prospects(owner_id,source_id,name,website,created_at) VALUES(1,?,?,?,'x')",('w'+str(i),'Site Co '+str(i),'https://site'+str(i)+'.example'))
            conn.execute('INSERT OR REPLACE INTO night_shift_settings(owner_id,enabled,next_beat) VALUES(1,0,0)');conn.commit()
            night_shift._LAST_INSPECT[0]=0.0
            page=lambda url:(200,'',b'<a href="/contact-us">Contact</a>') if url.endswith('example/') else (200,'',b'Email us: hello@site0.example')
            with patch('lead_engine._get',side_effect=page):
                self.assertEqual(night_shift.inspect(conn,1,clock=lambda:1000.0),0)  # shifts off: the Inspector rests
                conn.execute('UPDATE night_shift_settings SET enabled=1');conn.commit()
                self.assertEqual(night_shift.inspect(conn,1,clock=lambda:1000.0),5)
                self.assertEqual(night_shift.inspect(conn,1,clock=lambda:1030.0),0)  # not again within the minute
                self.assertEqual(night_shift.inspect(conn,1,clock=lambda:1061.0),2)
            self.assertEqual(conn.execute("SELECT email FROM prospects WHERE source_id='w0'").fetchone()[0],'hello@site0.example')  # found on the Contact page


if __name__=='__main__':
    unittest.main()

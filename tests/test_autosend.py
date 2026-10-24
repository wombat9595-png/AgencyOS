"""CEO auto-send: off by default, the daily limit, the sending hours, never twice, and opt-outs. No network, nothing sent."""
from contextlib import closing
from datetime import datetime
import os
import sqlite3
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet
import app as application
import autosend
import gmail_agent as gmail
import lead_engine
import test_agencyos as fixtures

TZ=ZoneInfo('Australia/Sydney')
WED_10AM=datetime(2026,10,21,10,0,tzinfo=TZ)
QUOTED='\n\nOn Wed, 21 Oct 2026 at 10:00, Benji Price <benji.price.webdesign@gmail.com> wrote:\n> If you would rather not hear from me, just reply "no thanks" and I will not contact you again.'


class AutoSendTest(unittest.TestCase):
    setUp_base=fixtures.AgencyOSTest.setUp
    tearDown_base=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def setUp(self):
        self.key=patch.dict(os.environ,AGENCYOS_GMAIL_KEY=Fernet.generate_key().decode(),AGENCYOS_GMAIL_KEY_FILE='')
        self.key.start()
        self.setUp_base()
        self.sent=[]

    def tearDown(self):
        self.tearDown_base()
        self.key.stop()

    def conn(self):
        conn=sqlite3.connect(application.DB_PATH);conn.row_factory=sqlite3.Row
        return closing(conn)

    def connect_gmail(self,conn,send=True,polling=1,last_sync=None):
        scope=gmail.READ+' '+gmail.COMPOSE+(' '+gmail.SEND if send else '')
        token=dict(access_token='synthetic',refresh_token='synthetic',expires_at=time.time()+3600,scope=scope)
        conn.execute('INSERT OR REPLACE INTO gmail_accounts(owner_id,email,token_cipher,connected_at,polling,last_sync) VALUES(1,?,?,?,?,?)',
          (gmail.ACCOUNT,gmail.seal(token),'fixture',polling,time.time() if last_sync is None else last_sync));conn.commit()

    def add(self,conn,name,email,suburb='Manly',body=None):
        s=lead_engine.settings(conn,1)
        cur=conn.execute("INSERT INTO prospects(owner_id,source_id,name,suburb,email,reason,score,created_at) VALUES(1,?,?,?,?,'none',80,?)",('t-'+name+email,name,suburb,email,'2026-10-20T00:00:00+00:00'))
        p=conn.execute('SELECT * FROM prospects WHERE id=?',(cur.lastrowid,)).fetchone()
        subject,text=lead_engine.draft(p,s,'first')
        conn.execute("UPDATE prospects SET draft_subject=?,draft_body=?,draft_kind='first',draft_source='rules',ceo_status='ready' WHERE id=?",(subject,body or text,p['id']))
        conn.commit()
        return p['id']

    def fake_send(self,conn,owner,email,subject,body):
        self.sent.append((email,subject,body));return 'gmail-'+str(len(self.sent))

    def tick(self,conn,at=WED_10AM,spaced=True):
        if spaced:conn.execute('UPDATE autosend_settings SET last_attempt=0');conn.commit()
        with patch('lead_engine.today',return_value=at.date()):
            return autosend.tick(conn,1,at=at,send=self.fake_send)

    def switch_on(self,conn):
        self.connect_gmail(conn);autosend.switch(conn,1,True,confirmed=True)

    def stage(self,conn,pid):
        return conn.execute('SELECT stage FROM prospects WHERE id=?',(pid,)).fetchone()[0]

    def test_off_by_default_and_sends_nothing(self):
        with self.conn() as conn:
            self.connect_gmail(conn);self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            self.assertFalse(autosend.settings(conn,1)['enabled'])
            result=self.tick(conn)
        self.assertEqual(result['reason'],'Auto-send is off.');self.assertEqual(self.sent,[])
        page=self.client.get('/gmail').get_data(as_text=True)
        self.assertIn('Let the CEO send first emails: OFF',page);self.assertIn('Turn auto-send ON',page)

    def test_switching_on_turns_shifts_on_and_keeps_a_days_batch_ready(self):
        import team
        with self.conn() as conn:
            conn.execute('INSERT OR REPLACE INTO night_shift_settings(owner_id,enabled) VALUES(1,0)')
            conn.execute("INSERT INTO night_shift_runs(owner_id,local_date,started_at,source,counts_json,finished_at) VALUES(1,?,'x','night','{\"mockups\": 20}','y')",(team.now_local().date().isoformat(),));conn.commit()
            self.assertEqual(team.plan(conn,1)['drafts'],0)  # auto-send off: 20 already drafted today, so no more
            self.switch_on(conn)
            self.assertEqual(conn.execute('SELECT enabled FROM night_shift_settings WHERE owner_id=1').fetchone()[0],1)
            for i in range(5):self.add(conn,'Fictional Trade '+str(i),'hi@trade'+str(i)+'.example')
            self.assertEqual(team.plan(conn,1)['drafts'],15)  # auto-send on: top the ready pile back up to the day's 20

    def test_switching_on_needs_the_send_permission_inbox_checking_and_a_tick(self):
        with self.conn() as conn:
            self.connect_gmail(conn,send=False)
            with self.assertRaises(Exception):autosend.switch(conn,1,True,confirmed=True)
            self.connect_gmail(conn,polling=0)
            with self.assertRaises(Exception):autosend.switch(conn,1,True,confirmed=True)
            self.connect_gmail(conn)
            with self.assertRaises(Exception):autosend.switch(conn,1,True,confirmed=False)
        self.post('/gmail/autosend',dict(enable='yes',confirm='yes'))
        with self.conn() as conn:self.assertTrue(autosend.settings(conn,1)['enabled'])
        self.post('/gmail/autosend',dict(enable='no'))
        with self.conn() as conn:self.assertFalse(autosend.settings(conn,1)['enabled'])

    def test_every_day_6am_to_10pm_sydney(self):
        self.assertTrue(autosend.in_window(datetime(2026,10,21,6,0,tzinfo=TZ)))
        self.assertTrue(autosend.in_window(datetime(2026,10,24,10,0,tzinfo=TZ)))  # Saturday
        self.assertTrue(autosend.in_window(datetime(2026,10,25,21,59,tzinfo=TZ)))  # Sunday night
        self.assertFalse(autosend.in_window(datetime(2026,10,21,5,59,tzinfo=TZ)))
        self.assertFalse(autosend.in_window(datetime(2026,10,21,22,0,tzinfo=TZ)))
        self.assertFalse(autosend.in_window(datetime(2026,10,24,3,0,tzinfo=TZ)))
        # 7 pm UTC is 6 am next day in Sydney: the window follows Sydney time, whatever the clock's zone.
        self.assertTrue(autosend.in_window(datetime(2026,10,20,19,0,tzinfo=ZoneInfo('UTC'))))
        with self.conn() as conn:
            self.switch_on(conn);self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            self.assertIn('Outside sending hours',self.tick(conn,at=datetime(2026,10,24,23,0,tzinfo=TZ))['reason'])
            self.assertEqual(self.sent,[])
            self.assertTrue(self.tick(conn,at=datetime(2026,10,24,10,0,tzinfo=TZ))['sent'])  # Saturday morning sends
        self.assertEqual(len(self.sent),1)

    def test_cap_warms_up_and_spacing_follows_it(self):
        self.assertEqual(autosend.gap(20).total_seconds(),25*60)
        self.assertEqual(autosend.gap(60).total_seconds(),16*60)
        self.assertEqual(autosend.gap(500).total_seconds(),5*60)
        with self.conn() as conn:
            conn.execute('INSERT OR REPLACE INTO team_settings(owner_id,daily_drafts) VALUES(1,60)')
            conn.execute("INSERT INTO prospects(owner_id,source_id,name,created_at) VALUES(1,'old','Old Lead','x')")
            conn.execute("INSERT INTO prospect_log(owner_id,prospect_id,on_date,action,detail,created_at) VALUES(1,last_insert_rowid(),'2026-10-12','sent','','x')");conn.commit()
            self.assertEqual(autosend.daily_cap(conn,1,WED_10AM.date()),35)  # day 10 of sending: a week of 20, then +5 a day
            conn.execute("UPDATE prospect_log SET on_date='2026-10-01'");conn.commit()
            self.assertEqual(autosend.daily_cap(conn,1,WED_10AM.date()),50)  # never past the free Gmail safe limit, even with 60 set

    def test_five_bounces_in_a_day_switch_it_off(self):
        with self.conn() as conn:
            self.switch_on(conn)
            for i in range(5):
                conn.execute("INSERT INTO autosend_log(owner_id,prospect_id,business,email,business_key,local_date,sent_at,subject,status) VALUES(1,0,?,?,?,?,?,'s','Sent')",
                  ('B'+str(i),'b'+str(i)+'@x.example','k'+str(i),WED_10AM.date().isoformat(),'2026-10-20T23:00:00+00:00'))
            for i in range(95):  # a big week, so the rate stays low and only the daily count trips
                conn.execute("INSERT INTO autosend_log(owner_id,prospect_id,business,email,business_key,local_date,sent_at,subject,status) VALUES(1,0,?,?,?,'2026-10-19','x','s','Sent')",('O'+str(i),'o'+str(i)+'@y.example','o'+str(i)))
            conn.commit()
            for i in range(4):self.incoming(conn,'mailer-daemon@googlemail.com','Failed: b'+str(i)+'@x.example',subject='Undeliverable')
            with patch('autosend.now_local',return_value=WED_10AM):self.tick(conn)
            self.assertTrue(autosend.settings(conn,1)['enabled'])  # 4 today, 4 in 100: keeps going, cap held at 20
            self.incoming(conn,'mailer-daemon@googlemail.com','Failed: b4@x.example',subject='Undeliverable')
            with patch('autosend.now_local',return_value=WED_10AM):self.tick(conn)
            self.assertFalse(autosend.settings(conn,1)['enabled'])

    def test_bounces_hold_the_cap_and_too_many_switch_it_off(self):
        with self.conn() as conn:
            self.switch_on(conn)
            for i in range(12):self.add(conn,'Fictional Trade '+str(i),'hi@trade'+str(i)+'.example')
            for _ in range(12):self.tick(conn)
            self.assertEqual(len(self.sent),12)
            self.incoming(conn,'mailer-daemon@googlemail.com','Address not found. Your message wasn\'t delivered to hi@trade0.example because the address couldn\'t be found.',subject='Delivery Status Notification (Failure)')
            self.tick(conn)
            self.assertEqual(conn.execute("SELECT status FROM autosend_log WHERE email='hi@trade0.example'").fetchone()[0],'Bounced')
            self.assertEqual(conn.execute("SELECT stage FROM prospects WHERE email='hi@trade0.example'").fetchone()[0],'No reply')
            self.assertEqual(autosend.daily_cap(conn,1,WED_10AM.date()),20)  # 1 in 12 bounced: the cap is held at 20
            self.assertFalse(autosend.settings(conn,1)['enabled'])  # and over 5 in 100 switches it off
            self.assertIn('bounced',autosend.settings(conn,1)['note'])

    def test_at_most_20_a_day_spaced_out_and_logged(self):
        with self.conn() as conn:
            self.switch_on(conn)
            for i in range(25):self.add(conn,'Fictional Trade '+str(i),'hi@trade'+str(i)+'.example')
            self.assertTrue(self.tick(conn)['sent'])
            self.assertIn('25 minutes',self.tick(conn,spaced=False)['reason'])  # straight after: wait
            for _ in range(30):self.tick(conn)
            self.assertEqual(len(self.sent),20)
            self.assertIn("Today's 20 are sent",self.tick(conn)['reason'])
            self.assertEqual(autosend.sent_today(conn,1,WED_10AM.date()),20)
            thursday=datetime(2026,10,22,9,0,tzinfo=TZ)
            self.assertTrue(self.tick(conn,at=thursday)['sent'])  # a new day, a new 20
        with patch('autosend.now_local',return_value=WED_10AM):
            page=self.client.get('/gmail').get_data(as_text=True)
        self.assertIn("Today's log: 20 of 20 sent",page);self.assertIn('Fictional Trade 0',page)

    def test_never_the_same_business_twice(self):
        with self.conn() as conn:
            self.switch_on(conn)
            first=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            self.assertTrue(self.tick(conn)['sent'])
            self.assertEqual(self.stage(conn,first),'Contacted')
            same_email=self.add(conn,'Fictional Builds Pty Ltd','hello@fictionalbuilds.example',suburb='Dee Why')
            same_domain=self.add(conn,'FB Renovations','jobs@fictionalbuilds.example',suburb='Mosman')
            same_name=self.add(conn,'Fictional Builds','other@gmail.com')
            two_on_gmail=self.add(conn,'Other Trade','other.trade@gmail.com',suburb='Bondi')
            for _ in range(6):self.tick(conn)
            sent_to=[e for e,_,_ in self.sent]
            self.assertEqual(sent_to,['hello@fictionalbuilds.example','other.trade@gmail.com'])  # gmail.com is shared, not one business
            for pid in (same_email,same_domain,same_name):
                row=conn.execute('SELECT ceo_status,ceo_note FROM prospects WHERE id=?',(pid,)).fetchone()
                self.assertEqual(row['ceo_status'],'held');self.assertIn('Not auto-sent',row['ceo_note'])
            # Follow-ups are never auto-sent, even when they are drafted and passed.
            conn.execute("UPDATE prospects SET draft_kind='followup1',ceo_status='ready' WHERE id=?",(first,));conn.commit()
            self.tick(conn)
        self.assertEqual(len(self.sent),2)
        self.assertEqual(len(self.rows('autosend_log')),2)

    def test_every_email_has_the_name_and_no_thanks_opt_out(self):
        with self.conn() as conn:
            self.switch_on(conn)
            good=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            body=conn.execute('SELECT draft_body FROM prospects WHERE id=?',(good,)).fetchone()[0]
            no_optout=self.add(conn,'Fictional Pipes','hi@pipes.example',body=body.replace('Fictional Builds','Fictional Pipes').split('\n\nIf you would rather')[0])
            no_name=self.add(conn,'Fictional Paint','hi@paint.example',body=body.replace('Fictional Builds','Fictional Paint').replace('Benji Price','B. P.'))
            for _ in range(4):self.tick(conn)
            self.assertEqual([e for e,_,_ in self.sent],['hello@fictionalbuilds.example'])
            for _,_,text in self.sent:
                self.assertIn('Benji Price',text);self.assertIn('no thanks',text)
            for pid in (no_optout,no_name):self.assertEqual(conn.execute('SELECT ceo_status FROM prospects WHERE id=?',(pid,)).fetchone()[0],'held')

    def incoming(self,conn,sender,body,subject='Re: Website for you?',n=[0]):
        n[0]+=1
        conn.execute("INSERT INTO gmail_mail(owner_id,external_id,thread_id,sender,content_cipher,intent_json,received_at,direction) VALUES(1,?,?,?,?,'{}',?,'incoming')",
          ('m'+str(n[0]),'t'+str(n[0]),sender,gmail.seal(dict(subject=subject,body=body)),'2026-10-21T01:00:00+00:00'));conn.commit()

    def test_opt_out_replies_stop_all_future_emails_even_with_auto_send_off(self):
        with self.conn() as conn:
            self.connect_gmail(conn)
            no=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            colleague=self.add(conn,'Fictional Builds North','north@fictionalbuilds.example',suburb='Mona Vale')
            yes=self.add(conn,'Fictional Pipes','hi@pipes.example')
            self.incoming(conn,'hello@fictionalbuilds.example','No thanks mate, all good.'+QUOTED)
            self.incoming(conn,'hi@pipes.example','Yes please, send it over!'+QUOTED)  # the quoted "no thanks" is ours, not theirs
            self.tick(conn)  # auto-send is off: opt-outs are still handled
            self.assertEqual(self.stage(conn,no),'Do not contact');self.assertEqual(self.stage(conn,colleague),'Do not contact')
            self.assertEqual(self.stage(conn,yes),'New')
            self.assertTrue(conn.execute("SELECT 1 FROM p5_suppressions WHERE email='hello@fictionalbuilds.example'").fetchone())
            self.switch_on(conn)
            for _ in range(3):self.tick(conn)
        self.assertEqual([e for e,_,_ in self.sent],['hi@pipes.example'])
        for text in ('Please unsubscribe me','Not interested, thanks','Stop emailing us','Please take me off your list','Don’t contact me again'):
            self.assertTrue(autosend.is_opt_out(text),text)
        for text in ('Yes please','How much would it cost?','Sounds good, call me Monday'+QUOTED):
            self.assertFalse(autosend.is_opt_out(text),text)

    def test_stops_sending_when_the_inbox_check_is_not_working(self):
        with self.conn() as conn:
            self.switch_on(conn);self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            self.connect_gmail(conn,last_sync=time.time()-3*3600)
            self.assertIn('inbox check',self.tick(conn)['reason'])
            self.connect_gmail(conn,send=False)
            self.assertIn('send permission',self.tick(conn)['reason'])
            conn.execute("UPDATE p4_control SET paused=1");conn.commit()
            self.connect_gmail(conn)
            self.assertIn('paused',self.tick(conn)['reason'])
        self.assertEqual(self.sent,[])

    def test_a_gmail_problem_switches_it_off_and_nothing_is_retried(self):
        with self.conn() as conn:
            self.switch_on(conn);pid=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            def broken(*args):raise OSError('network down')
            conn.execute('UPDATE autosend_settings SET last_attempt=0');conn.commit()
            result=autosend.tick(conn,1,at=WED_10AM,send=broken)
            self.assertFalse(result['sent']);self.assertIn('Switched itself off',result['reason'])
            self.assertFalse(autosend.settings(conn,1)['enabled'])
            self.assertEqual(conn.execute('SELECT status FROM autosend_log').fetchone()[0],'Outcome unknown')
            autosend.switch(conn,1,True,confirmed=True)
            self.tick(conn)
            self.assertEqual(self.sent,[])  # that business is never tried again
            self.assertEqual(conn.execute('SELECT ceo_status FROM prospects WHERE id=?',(pid,)).fetchone()[0],'held')


if __name__=='__main__':
    unittest.main()

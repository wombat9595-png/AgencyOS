"""The 35-minute updates. Only reads the app's own logs; no network, nothing sent."""
from datetime import datetime,timedelta,timezone
import json
import unittest
from unittest.mock import patch
import night_shift
import test_autosend
import updates
from test_autosend import WED_10AM

END=datetime.fromtimestamp((int(WED_10AM.timestamp())//updates.EVERY)*updates.EVERY,timezone.utc)  # a slot boundary
JUST_AFTER=END+timedelta(minutes=1)


def at(minutes_before_end):return (END-timedelta(minutes=minutes_before_end)).isoformat()


class UpdatesTest(unittest.TestCase):
    for _name in ('setUp','tearDown','setUp_base','tearDown_base','post','rows','conn','connect_gmail','add','fake_send','tick','switch_on'):
        locals()[_name]=getattr(test_autosend.AutoSendTest,_name)

    def log(self,conn,pid,action,when,detail=''):
        conn.execute('INSERT INTO prospect_log(owner_id,prospect_id,on_date,action,detail,created_at) VALUES(1,?,?,?,?,?)',(pid,'2026-10-21',action,detail,when))

    def write(self,conn,now=JUST_AFTER):
        with patch('autosend.now_local',return_value=WED_10AM):return updates.tick(conn,1,now=now)

    def latest(self,conn):
        r=conn.execute('SELECT * FROM activity_updates ORDER BY slot DESC LIMIT 1').fetchone()
        return r['headline'],json.loads(r['lines_json'])

    def test_a_busy_half_hour_reads_as_plain_updates(self):
        with self.conn() as conn:
            builds=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example',suburb='Manly')
            pipes=self.add(conn,'Fictional Pipes','hi@pipes.example',suburb='Dee Why')
            gone=self.add(conn,'Fictional Gone','old@gone.example')
            self.log(conn,builds,'auto_sent',at(20),'Website for Fictional Builds?');self.log(conn,builds,'sent',at(20))  # one email, logged twice
            self.log(conn,pipes,'replied',at(10));self.log(conn,gone,'bounced',at(5))
            self.log(conn,pipes,'auto_sent',at(60))  # before this note's window: not counted
            conn.execute("INSERT INTO prospects(owner_id,source_id,name,website,email,site_check,checked_at,created_at) VALUES(1,'n1','Fictional Tiles','https://tiles.example','info@tiles.example',?,?,?)",
              (json.dumps({'email':'info@tiles.example'}),at(3),at(30)))
            conn.execute("INSERT INTO prospects(owner_id,source_id,name,website,site_check,checked_at,created_at) VALUES(1,'n2','Fictional Paint','https://paint.example','{}',?,?)",(at(3),at(30)))
            conn.execute("INSERT INTO night_shift_runs(owner_id,local_date,started_at,finished_at,source,counts_json) VALUES(1,'2026-10-21',?,?,'timer',?)",
              (at(25),at(24),json.dumps({'drafts':12,'ceo_ready':10,'ceo_held':2})))
            conn.commit()
            self.assertTrue(self.write(conn))
            headline,lines=self.latest(conn)
        self.assertEqual(headline,'1 reply, 1 email sent, 1 bounce')
        text='\n'.join(lines)
        self.assertIn('1 business wrote back: Fictional Pipes (Dee Why).',text)
        self.assertIn('The CEO emailed 1 business: Fictional Builds (Manly).',text)
        self.assertNotIn('You emailed',text)
        self.assertIn('1 email bounced: Fictional Gone (Manly). That address will not be used again.',text)
        self.assertIn('The Scout added 2 new leads.',text)
        self.assertIn('The team checked 2 websites and found 1 new email address on them.',text)
        self.assertIn('drafted 12, the CEO passed 10 and held 2.',text)

    def test_a_quiet_half_hour_says_so_and_why(self):
        with self.conn() as conn:
            self.write(conn)
            headline,lines=self.latest(conn)
        self.assertEqual(headline,'Quiet: nothing new happened')
        self.assertIn('Auto-send is off, so the CEO is not emailing anyone.',lines)
        self.assertTrue(any('Inbox checking is off' in l for l in lines))  # a missing source is named, not guessed

    def test_paused_is_named(self):
        with self.conn() as conn:
            conn.execute('UPDATE p4_control SET paused=1 WHERE id=1');conn.commit()
            self.write(conn)
            self.assertIn('AgencyOS is paused',' '.join(self.latest(conn)[1]))

    def test_once_per_35_minutes_even_after_a_restart_and_no_gaps(self):
        with self.conn() as conn:
            pid=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            self.assertTrue(self.write(conn))
            self.assertFalse(self.write(conn,now=JUST_AFTER+timedelta(minutes=20)))  # same slot, e.g. AgencyOS restarted
            self.log(conn,pid,'replied',END.isoformat());conn.commit()  # right on the boundary: belongs to the next note only
            self.assertTrue(self.write(conn,now=JUST_AFTER+timedelta(minutes=35)))
            rows=conn.execute('SELECT period_start,period_end,headline FROM activity_updates ORDER BY slot').fetchall()
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['period_end'],rows[1]['period_start'])
        self.assertEqual([r['headline'] for r in rows],['Quiet: nothing new happened','1 reply'])

    def test_after_the_mac_sleeps_one_catch_up_note_not_a_flood(self):
        with self.conn() as conn:
            self.write(conn)
            self.write(conn,now=JUST_AFTER+timedelta(hours=3))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM activity_updates').fetchone()[0],2)
            self.assertIn('AgencyOS was closed or the Mac was asleep',self.latest(conn)[1][0])
            self.write(conn,now=JUST_AFTER+timedelta(days=3))
            r=conn.execute('SELECT period_start,period_end FROM activity_updates ORDER BY slot DESC LIMIT 1').fetchone()
        self.assertLessEqual(datetime.fromisoformat(r['period_end'])-datetime.fromisoformat(r['period_start']),updates.CATCH_UP)

    def test_old_notes_are_tidied_after_30_days(self):
        with self.conn() as conn:
            self.write(conn)
            self.write(conn,now=JUST_AFTER+timedelta(days=31))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM activity_updates').fetchone()[0],1)

    def test_updates_page_badge_and_ceo_live(self):
        with self.conn() as conn:
            pid=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example')
            self.log(conn,pid,'replied',at(5));conn.commit()
            self.write(conn)
        home=self.client.get('/business').get_data(as_text=True)
        self.assertIn('Updates <b class="count">1</b>',home)
        ceo=self.client.get('/ceo').get_data(as_text=True)
        self.assertIn('Latest update',ceo);self.assertIn('Fictional Builds',ceo)
        page=self.client.get('/updates').get_data(as_text=True)
        self.assertIn('What happened',page);self.assertIn('1 reply',page);self.assertIn('new</span>',page)
        self.assertNotIn('<b class="count">',self.client.get('/business').get_data(as_text=True))  # opening Updates marks them read

    def test_the_worker_writes_them(self):
        import app as application
        with patch('night_shift.due',return_value=False),patch('night_shift.inspect',return_value=0),patch('pitch.detect_replies'),patch('autosend.tick'),patch('lead_engine.sync_gmail'):
            night_shift.worker_tick(application.DB_PATH)
        with self.conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM activity_updates').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()

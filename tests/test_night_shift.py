"""Night shift, playbook, Writer, story mock-ups and Google Profile Care. No network, nothing sent, no AI called."""
from contextlib import closing
from datetime import date,datetime,timedelta
import json
import os
import sqlite3
import unittest
from unittest.mock import patch
import app as application
import client_plans
import lead_engine
import night_shift
import playbook
import smart_writer
import test_agencyos as fixtures
from test_lead_engine import GEO,fake_get

TODAY=date(2026,10,19)
OSM={'elements':[
 {'type':'node','id':11,'tags':{'name':'Fictional Builds','craft':'builder','email':'hi@fictional-builds.example','phone':'0400 111 222','addr:suburb':'Mona Vale'}},
 {'type':'node','id':12,'tags':{'name':'Old Site Plumbing','craft':'builder','website':'http://oldsite.example','phone':'0400 000 002','addr:suburb':'Newport'}},
 {'type':'node','id':13,'tags':{'name':'Good Site Plumbing','craft':'builder','website':'https://goodsite.example','email':'jobs@goodsite.example'}},
]}
SETTINGS=dict(name='Benji Price',business='Benji Price Web Design',email='benji.price.webdesign@gmail.com',phone='',area='',daily_target=10)


class NightShiftTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def conn(self):
        conn=sqlite3.connect(application.DB_PATH);conn.row_factory=sqlite3.Row
        return closing(conn)

    def shift(self):
        self.post('/night-shift/beats',dict(trade='Builders',town='Mona Vale NSW',radius='10'))
        with patch('lead_engine.http_json',side_effect=[GEO,OSM]),patch('lead_engine._get',side_effect=fake_get),patch('lead_engine.today',return_value=TODAY):
            return self.post('/night-shift/run')

    def prospect(self,name):
        return next(r for r in self.rows('prospects') if r['name']==name)

    def test_rule_drafts_follow_the_playbook(self):
        p=dict(id=1,name='Fictional Builds',trade='Builders',suburb='Mona Vale',email='hi@x.example',phone='',website='',reason='none',site_check='',touches=0)
        for touches,kind in ((0,'first'),(1,'followup1'),(2,'followup2')):
            subject,body=lead_engine.draft(dict(p,touches=touches),SETTINGS,kind)
            self.assertEqual(playbook.review(subject,body,p,SETTINGS,kind),[],kind)
        self.assertIn('missing the "no thanks" opt-out (Spam Act)',playbook.review('Hi','Hi Fictional Builds team, we guarantee results',p,SETTINGS))
        self.assertEqual(playbook.story_for('Builders')['demo'],'builder-real')
        self.assertEqual(playbook.story_for('Beauty salons')['demo'],'salon')
        self.assertIsNone(playbook.story_for('Plumbers'))

    def test_shift_finds_checks_and_drafts_then_home_shows_the_queue(self):
        response=self.shift()
        self.assertEqual(response.status_code,302);self.assertTrue(response.headers['Location'].endswith('/business#ready'))
        run=self.rows('night_shift_runs')[0];counts=json.loads(run['counts_json'])
        self.assertEqual(run['source'],'manual');self.assertTrue(run['finished_at'])
        self.assertEqual(counts['found'],3);self.assertEqual(counts['checked'],2);self.assertEqual(counts['drafts'],1);self.assertEqual(counts['ai_drafts'],0)
        built=self.prospect('Fictional Builds')
        self.assertEqual(built['draft_kind'],'first');self.assertEqual(built['draft_source'],'rules');self.assertIn('no thanks',built['draft_body'])
        self.assertEqual(self.prospect('Old Site Plumbing')['draft_body'],'')  # phone only: email only, so no draft and no call script
        self.assertEqual(self.prospect('Good Site Plumbing')['draft_body'],'')  # site is fine, nothing drafted
        with patch('lead_engine.today',return_value=TODAY):
            home=self.client.get('/business').data.decode()
        self.assertIn('Ready for you',home);self.assertIn('Fictional Builds',home);self.assertIn('Bare dirt to finished house (real time-lapse) mock-up',home)
        self.assertIn('Last shift',home);self.assertIn('Run a shift now',home)
        self.assertEqual(self.rows('night_shift_settings')[0]['next_beat'],0)  # one beat, rotation wraps

    def test_approve_and_skip_from_home_come_back_home(self):
        self.shift();p=self.prospect('Fictional Builds')
        response=self.post(f'/find-customers/{p["id"]}/approve',dict(subject=p['draft_subject'],body=p['draft_body'],next='home'))
        self.assertTrue(response.headers['Location'].endswith('/business#ready'))
        self.assertEqual(self.prospect('Fictional Builds')['stage'],'Approved')
        response=self.post(f'/find-customers/{p["id"]}/sent',dict(next='home'))
        self.assertTrue(response.headers['Location'].endswith('/business#ready'))
        self.assertEqual(self.prospect('Fictional Builds')['touches'],1)
        self.assertIsNone(smart_writer.stored(self.prospect('Fictional Builds')))  # the old draft is not reused for the follow-up

    def test_shift_runs_every_two_hours_day_and_night_and_not_when_paused(self):
        with self.conn() as conn:
            owner=conn.execute('SELECT id FROM users').fetchone()[0]
            at=night_shift.now_local()
            self.assertTrue(night_shift.due(conn,owner,at))
            conn.execute('INSERT INTO team_settings(owner_id,tiles_per_night) VALUES(?,0)',(owner,));conn.commit()  # map sweep off
            night_shift.run(conn,owner,on=at.date())
            self.assertFalse(night_shift.due(conn,owner,at+timedelta(minutes=30)))
            self.assertTrue(night_shift.due(conn,owner,at+timedelta(hours=2)))
            conn.execute('UPDATE p4_control SET paused=1 WHERE id=1');conn.commit()
            self.assertFalse(night_shift.due(conn,owner,at+timedelta(hours=2)))
        self.assertIn('No search areas set and the map sweep is off',self.rows('night_shift_runs')[0]['notes'])

    def test_worker_tick_runs_the_shift(self):
        with patch('night_shift.now_local',return_value=datetime(2026,10,19,3,0,tzinfo=night_shift.TZ)),patch('sweep.run',return_value=(0,0,[])):
            self.assertTrue(night_shift.worker_tick(application.DB_PATH))
            self.assertFalse(night_shift.worker_tick(application.DB_PATH))
        self.assertEqual(len(self.rows('night_shift_runs')),1)

    def test_writer_ai_is_off_by_default_and_capped(self):
        self.shift()
        with self.conn() as conn:
            owner=conn.execute('SELECT id FROM users').fetchone()[0];s=lead_engine.settings(conn,owner)
            p=conn.execute("SELECT * FROM prospects WHERE name='Fictional Builds'").fetchone()
            ask=lambda prompt:('Subject: Your pool photos\nHi Fictional Builds team,\n\nYour Mona Vale builds look great, but the site hides them on a phone. I can make you a free mock-up. Reply "yes".',900,120)
            self.assertFalse(smart_writer.ai_status(conn,owner)['ready'])
            self.assertEqual(smart_writer.write(conn,owner,p,s,ask=ask),'rules')
            conn.execute('INSERT INTO writer_settings VALUES(?,1,500)',(owner,))
            with patch.dict(os.environ,{'AGENCYOS_ZERO_COST':'1','ANTHROPIC_API_KEY':'test-key','AGENCYOS_ANTHROPIC_KEY_FILE':''}):
                # A key inherited from the environment never lifts the free-only lock.
                self.assertIn('no Anthropic API key is saved',smart_writer.ai_status(conn,owner)['reason'])
            with patch.dict(os.environ,{'AGENCYOS_ZERO_COST':'0','ANTHROPIC_API_KEY':'test-key'}):
                self.assertTrue(smart_writer.ai_status(conn,owner)['ready'])
                self.assertEqual(smart_writer.write(conn,owner,p,s,ask=ask),'ai')
                body=conn.execute("SELECT draft_body FROM prospects WHERE id=?",(p['id'],)).fetchone()[0]
                self.assertIn('pool photos',conn.execute("SELECT draft_subject FROM prospects WHERE id=?",(p['id'],)).fetchone()[0])
                self.assertIn('no thanks',body);self.assertIn('Benji Price Web Design',body)
                hype=lambda prompt:('Subject: We guarantee more customers\nHi Fictional Builds team, guaranteed results!',900,40)
                self.assertEqual(smart_writer.write(conn,owner,p,s,ask=hype),'rules')
                conn.execute('UPDATE writer_usage SET output_tokens=100000000');conn.commit()
                self.assertFalse(smart_writer.ai_status(conn,owner)['ready'])
                self.assertIn('cap is used up',smart_writer.ai_status(conn,owner)['reason'])
            usage=conn.execute('SELECT * FROM writer_usage').fetchone()
            self.assertEqual(usage['calls'],2)
        self.assertIn('Tick to confirm',self.post('/writer/settings',dict(ai_enabled='1',cap='5')).data.decode())

    def test_story_mockup_is_personalised_and_downloads_as_one_file(self):
        self.shift();p=self.prospect('Fictional Builds')
        page=self.client.get(f'/find-customers/{p["id"]}/story').data.decode()
        self.assertIn('Fictional Builds',page);self.assertNotIn('Northline',page);self.assertNotIn('made-up business',page)
        self.assertIn('/static/motion/real/builder/f_',page);self.assertIn('tel:0400111222',page);self.assertIn('hi@fictional-builds.example',page)
        download=self.client.get(f'/find-customers/{p["id"]}/story?download=1')
        self.assertIn('attachment; filename="fictional-builds-story-mockup.html"',download.headers['Content-Disposition'])
        packed=download.data.decode()
        self.assertNotIn('../../kit',packed);self.assertNotIn('REAL_MEDIA',packed);self.assertNotIn('/static/',packed)
        self.assertIn('data:image/jpeg;base64,',packed);self.assertIn('BUILD_FRAMES={list:[',packed)
        self.client.get('/find-customers/1/story')  # plumbers (no story) fall back to the one-page mock-up
        with self.conn() as conn:
            conn.execute("UPDATE prospects SET trade='Plumbers' WHERE id=?",(p['id'],));conn.commit()
        self.assertTrue(self.client.get(f'/find-customers/{p["id"]}/story').headers['Location'].endswith('/mockup'))

    def test_google_profile_care_adds_49_and_drafts_posts(self):
        self.post('/clients/add',dict(client_name='Sample Salon',contact_email='owner@example.com',plan='Care',billing='monthly',started_on='2026-10-01'))
        client=self.rows('plan_clients')[0]
        self.assertEqual(client_plans.monthly_value(client),6900)
        self.post(f'/clients/{client["id"]}/profile-care',dict(on='1'))
        client=self.rows('plan_clients')[0]
        self.assertEqual(client_plans.monthly_value(client),6900+4900)
        posts=self.rows('profile_posts');self.assertEqual(len(posts),3)
        self.assertTrue(all('Sample Salon' in p['text'] for p in posts))
        home=self.client.get('/business').data.decode()
        self.assertIn('Google post',home);self.assertIn('Review request',home)
        response=self.post(f'/clients/posts/{posts[0]["id"]}/approve',dict(text=posts[0]['text'],next='home'))
        self.assertTrue(response.headers['Location'].endswith('/business#ready'))
        self.assertEqual(self.rows('profile_posts')[0]['status'],'Approved')
        with self.conn() as conn:
            self.assertEqual(client_plans.ensure_profile_posts(conn,client['owner_id']),0)  # never doubles up in a month
        self.assertIn('Remove Google Profile Care',self.client.get('/clients').data.decode())

    def test_night_shift_page_and_beats(self):
        page=self.client.get('/night-shift').data.decode()
        self.assertIn('Six agents, one playbook',page);self.assertIn('Rules only (free)',page)
        self.assertIn('Pick a trade',self.post('/night-shift/beats',dict(trade='Nope',town='X',radius='10')).data.decode())
        self.post('/night-shift/beats',dict(trade='Beauty salons',town='Manly NSW',radius='5'))
        self.assertIn('Cut, curls and colour',self.client.get('/night-shift').data.decode())
        beat=self.rows('night_shift_beats')[0]
        self.post(f'/night-shift/beats/{beat["id"]}/remove');self.assertEqual(self.rows('night_shift_beats'),[])
        self.post('/night-shift/toggle',dict(enabled='0'));self.assertEqual(self.rows('night_shift_settings')[0]['enabled'],0)


    def test_api_key_saved_privately_lifts_the_lock_for_the_writer_only(self):
        import tempfile
        folder=tempfile.mkdtemp();path=os.path.join(folder,'anthropic.secret')
        with patch.dict(os.environ,{'AGENCYOS_ZERO_COST':'1','AGENCYOS_ANTHROPIC_KEY_FILE':path,'ANTHROPIC_API_KEY':''}):
            self.assertIn('does not look like',self.post('/writer/key',dict(key='hello')).data.decode())
            self.assertFalse(os.path.exists(path))
            self.post('/writer/key',dict(key='sk-ant-test-0123456789abcdef'))
            self.assertEqual(oct(os.stat(path).st_mode&0o777),'0o600')
            page=self.client.get('/night-shift').data.decode()
            self.assertIn('saved privately on this Mac',page);self.assertNotIn('sk-ant-test',page)
            with self.conn() as conn:
                owner=conn.execute('SELECT id FROM users').fetchone()[0]
                conn.execute('INSERT INTO writer_settings VALUES(?,1,500)',(owner,));conn.commit()
                with patch.dict('sys.modules',{'anthropic':object()}):
                    self.assertTrue(smart_writer.ai_status(conn,owner)['ready'])
            self.post('/writer/key',dict(remove='yes'));self.assertFalse(os.path.exists(path))

    def test_signature_packages_are_added_once_for_owners_already_set_up(self):
        self.post('/business/configure',{'confirm':'yes'})
        with self.conn() as conn:
            conn.execute("DELETE FROM p5_packages WHERE name LIKE 'Signature%'");conn.commit()
        self.client.get('/business');self.client.get('/business')
        names=[p['name'] for p in self.rows('p5_packages')]
        self.assertEqual(names.count('Signature Website'),1);self.assertEqual(names.count('Signature Website (founding)'),1)


if __name__=='__main__':
    unittest.main()

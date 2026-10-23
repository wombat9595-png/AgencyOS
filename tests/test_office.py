"""Office and the shared brain: states come from local records only; nothing is sent."""
import unittest
from contextlib import closing
import sqlite3
import app as application
import brain
import test_agencyos as fixtures


class OfficeTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post

    def sql(self,query,args=()):
        with closing(sqlite3.connect(application.DB_PATH)) as conn,conn:
            conn.execute(query,args)

    def state(self,sample='0'):
        response=self.client.get('/office/state?sample='+sample)
        self.assertEqual(response.status_code,200)
        return {s['key']:s for s in response.get_json()['sectors']},response.get_json()

    def test_page_has_no_words_in_the_scene_and_is_linked(self):
        page=self.client.get('/office')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'office.js',page.data)
        self.assertIn(b'href="/office"',self.client.get('/business').data)
        js=open(application.APP_DIR+'/static/office.js').read() if hasattr(application,'APP_DIR') else ''
        self.assertNotIn('<text',js)

    def test_empty_agency_is_real_and_scout_waits_for_the_owner(self):
        sectors,snap=self.state()
        self.assertFalse(snap['sample'])
        self.assertEqual(sectors['find']['agents'][0]['state'],'waiting')
        self.assertEqual([a['state'] for a in sectors['inbox']['agents']],['asleep','asleep'])
        self.assertEqual(sectors['money']['agents'][0]['state'],'idle')
        self.assertTrue(sectors['find']['url'].startswith('/'))

    def test_sample_is_labelled(self):
        _,snap=self.state('1')
        self.assertTrue(snap['sample'])
        self.assertIn(b'Sample',self.client.get('/office?sample=1').data)

    def test_real_records_drive_agents(self):
        owner=self.client.get('/office/state').status_code and 1
        stamp=brain.datetime.now(brain.timezone.utc).isoformat()
        for i in range(3):
            self.sql("INSERT INTO prospects(owner_id,source_id,name,email,score,stage,created_at) VALUES(?,?,?,?,?,?,?)",(owner,'s'+str(i),'Fictional '+str(i),'a'+str(i)+'@example.test',70,'New',stamp))
        sectors,_=self.state()
        self.assertEqual(sectors['find']['agents'][0]['state'],'working')
        self.assertEqual(sectors['find']['agents'][0]['items'],3)
        self.assertEqual(sectors['outreach']['agents'][0]['state'],'waiting')

    def test_idle_agents_help_check_websites_and_home_shows_new_order(self):
        stamp=brain.datetime.now(brain.timezone.utc).isoformat()
        for i in range(2):
            self.sql("INSERT INTO prospects(owner_id,source_id,name,website,score,stage,created_at) VALUES(1,?,?,?,40,'New',?)",('w'+str(i),'Fictional site '+str(i),'https://site'+str(i)+'.example.test',stamp))
        sectors,snap=self.state()
        self.assertIn('Builder',snap['helpers']);self.assertIn('Carer',snap['helpers']);self.assertEqual(snap['unchecked'],2)
        builder=sectors['websites']['agents'][1]
        self.assertEqual((builder['state'],builder['why']),('working','helping the Checker find emails on websites'))
        self.assertNotIn('Scout',snap['helpers'])
        page=self.client.get('/business').get_data(as_text=True)
        order=[page.index(s) for s in ('Watch your CEO work','Money and leads','Ready for you','What matters now','Talk to your CEO','Your agents right now','Where do I go to')]
        self.assertEqual(order,sorted(order))
        self.assertIn('Helping out:',page)
        self.sql('UPDATE p4_control SET paused=1 WHERE id=1')
        self.assertEqual(self.state()[1]['helpers'],[])

    def test_pause_puts_everyone_to_rest(self):
        self.sql('UPDATE p4_control SET paused=1 WHERE id=1')
        sectors,snap=self.state()
        self.assertTrue(snap['paused'])
        self.assertTrue(all(a['state']=='off' for s in sectors.values() for a in s['agents']))

    def test_ceo_reports_what_agents_are_doing(self):
        page=self.client.get('/business?ask=What%27s+everyone+working+on%3F')
        self.assertIn(b'Find customers: Scout needs you to pick a trade and suburb',page.data)


if __name__=='__main__':
    unittest.main()

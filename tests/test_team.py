"""The agent team: org chart, CEO review, teaching and learning, the map sweep, phone page and pings. No network, nothing sent."""
from contextlib import closing
from datetime import date,datetime
import json
import sqlite3
import unittest
from unittest.mock import patch
import app as application
import lead_engine
import night_shift
import smart_writer
import sweep
import team
import test_agencyos as fixtures
from test_lead_engine import GEO,fake_get
from test_night_shift import OSM

TODAY=date(2026,10,21)
TILE={'elements':[
 {'type':'node','id':901,'tags':{'name':'No Site Sparkies','craft':'electrician','phone':'0400 900 901','email':'jobs@nosite.example','addr:suburb':'Manly'}},
 {'type':'node','id':902,'tags':{'name':'Corner Cuts','shop':'hairdresser','phone':'0400 900 902'}},
 {'type':'node','id':903,'tags':{'name':'Mystery Shop','shop':'kiosk'}},
]}
READY=dict(enabled=True,ready=True,reason='On.',cap_cents=2000,spent_cents=0,key_saved=True)


class TeamTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def conn(self):
        conn=sqlite3.connect(application.DB_PATH);conn.row_factory=sqlite3.Row
        return closing(conn)

    def owner(self,conn):
        return conn.execute('SELECT id FROM users').fetchone()[0]

    def shift(self,tiles=0):
        with self.conn() as conn:
            conn.execute('INSERT OR REPLACE INTO team_settings(owner_id,tiles_per_night) VALUES(?,?)',(self.owner(conn),tiles));conn.commit()
        self.post('/night-shift/beats',dict(trade='Builders',town='Mona Vale NSW',radius='10'))
        with patch('lead_engine.http_json',side_effect=[GEO,OSM]),patch('lead_engine._get',side_effect=fake_get),patch('lead_engine.today',return_value=TODAY):
            return self.post('/night-shift/run')

    def prospect(self,name):
        return next(r for r in self.rows('prospects') if r['name']==name)

    def test_team_page_shows_nine_agents_and_their_playbooks(self):
        page=self.client.get('/team').get_data(as_text=True)
        for name in ('CEO','Chief of Staff','Growth Manager','Sales Manager','Delivery Manager','Scout','Inspector','SEO Checker','Writer','Deliverability Guard','Designer',
                     'Chaser','Reply Handler','Closer','Site Builder','Client Care','Bookkeeper'):self.assertIn(name,page)
        self.assertIn('Teach',page);self.assertIn('Quote helper',page);self.assertIn('Sydney (first)',page);self.assertIn('every business with no website in Australia',page)
        self.assertEqual(len(team.AGENTS),17);self.assertEqual(len(team.WORKERS),12)
        self.assertEqual({a[3] for a in team.AGENTS if a[0] in team.WORKERS},{'growth','sales','delivery'})
        self.assertIn('href="/team"',self.client.get('/business').get_data(as_text=True))

    def test_ceo_passes_rule_drafts_and_holds_what_you_taught_it_to_block(self):
        self.shift()
        p=self.prospect('Fictional Builds')
        self.assertEqual(p['ceo_status'],'ready');self.assertEqual(p['ceo_note'],'Checked by the CEO')
        run=json.loads(self.rows('night_shift_runs')[0]['counts_json'])
        self.assertEqual(run['ceo_ready'],1);  # phone-only leads get no draft: email only
        self.assertEqual(run['ceo_held'],0)
        # Teach the Writer a banned word that the template uses: the CEO now holds that draft back.
        self.post('/team/teach',dict(agent='writer',lesson='Never call the mock-up free',avoid='free one-page'))
        with self.conn() as conn:
            owner=self.owner(conn)
            self.assertEqual(team.ceo_review(conn,owner,[p['id']]),dict(ready=0,held=1,fixed=0));conn.commit()
        p=self.prospect('Fictional Builds')
        self.assertEqual(p['ceo_status'],'held');self.assertIn('you taught the team not to',p['ceo_note'])
        with self.conn() as conn:self.assertNotIn(p['id'],[r['id'] for r in lead_engine.queue(conn,self.owner(conn))])

    def test_yes_edits_and_no_reasons_are_stored_and_learned(self):
        self.shift()
        p=self.prospect('Fictional Builds')
        body=p['draft_body'].replace('Worth a look?','Keen to see it?')
        self.post(f'/find-customers/{p["id"]}/approve',dict(subject=p['draft_subject'],body=body,next='phone'))
        fb=self.rows('team_feedback')[0]
        self.assertEqual((fb['verdict'],fb['edited'],fb['agent']),('yes',1,'writer'));self.assertIn('Keen to see it?',fb['final'])
        with self.conn() as conn:
            owner=self.owner(conn)
            self.assertIn('THEIR BUSINESS',team.coaching(conn,owner,'Builders'))
            self.assertNotIn('Fictional Builds',team.coaching(conn,owner,'Builders'))
        # Three "too long" no's make it a standing rule and the rules Writer switches to the short email.
        with self.conn() as conn:
            owner=self.owner(conn)
            for i in range(3):
                conn.execute("INSERT INTO prospects(owner_id,source_id,name,trade,suburb,email,reason,score,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (owner,'t:'+str(i),'Test Co '+str(i),'Plumbers','Manly','t'+str(i)+'@x.example','none',85,'2026-10-21'))
            conn.commit()
        ids=[r['id'] for r in self.rows('prospects') if r['name'].startswith('Test Co')]
        for pid in ids:
            response=self.post(f'/find-customers/{pid}/redo',dict(reason='too_long',next='phone'))
            self.assertTrue(response.headers['Location'].endswith('/m'))
        self.assertEqual(self.prospect('Test Co 0')['ceo_status'],'redo')
        with self.conn() as conn:
            owner=self.owner(conn);l=team.learned(conn,owner)
            self.assertTrue(l['short']);self.assertEqual(l['reasons'],{'too_long':3});self.assertIn('too long',l['rules'][0])
            self.assertNotIn(ids[0],[r['id'] for r in lead_engine.queue(conn,owner,limit=50)])
            p=conn.execute('SELECT * FROM prospects WHERE id=?',(ids[0],)).fetchone()
            smart_writer.write(conn,owner,p,lead_engine.settings(conn,owner),short=team.learned(conn,owner)['short'])
            p=conn.execute('SELECT * FROM prospects WHERE id=?',(ids[0],)).fetchone()
            normal=lead_engine.draft(p,lead_engine.settings(conn,owner),'first')[1]
        self.assertLess(len(p['draft_body'].split()),len(normal.split())-15)
        self.assertIn('no thanks',p['draft_body'])

    def test_not_a_fit_drops_the_business_and_the_trade_after_three(self):
        with self.conn() as conn:
            owner=self.owner(conn)
            for i in range(4):
                conn.execute("INSERT INTO prospects(owner_id,source_id,name,trade,suburb,email,reason,score,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (owner,'c:'+str(i),'Cafe '+str(i),'Cafes','Manly','c'+str(i)+'@x.example','none',85,'2026-10-21'))
            conn.commit()
        for r in [r for r in self.rows('prospects') if r['name'] in ('Cafe 0','Cafe 1','Cafe 2')]:
            self.post(f'/find-customers/{r["id"]}/redo',dict(reason='bad_fit'))
        self.assertEqual(self.prospect('Cafe 0')['stage'],'Skipped')
        with self.conn() as conn:
            owner=self.owner(conn)
            self.assertEqual(team.learned(conn,owner)['bad_trades'],['Cafes'])
            conn.execute('INSERT INTO team_settings(owner_id,tiles_per_night) VALUES(?,0)',(owner,));conn.commit()
            with patch('lead_engine.today',return_value=TODAY):night_shift.run(conn,owner,on=TODAY)
        self.assertEqual(self.prospect('Cafe 3')['draft_body'],'')  # the Writer skips the trade Benji keeps rejecting

    def test_ai_ceo_asks_for_a_fix_and_the_writer_redoes_it(self):
        self.shift()
        p=self.prospect('Fictional Builds')
        good='Subject: Quick idea for Fictional Builds\nHi Fictional Builds team,\n\nI noticed you do not have a website yet. Can I make you a free mock-up?'
        with self.conn() as conn,patch('smart_writer.ai_status',return_value=READY):
            owner=self.owner(conn)
            conn.execute("UPDATE prospects SET draft_source='ai' WHERE id=?",(p['id'],))
            asks=[]
            out=team.ceo_review(conn,owner,[p['id']],ask=lambda prompt:(asks.append(prompt) or 'FIX: mention they build in Mona Vale',100,10),
              write_ask=lambda prompt:(asks.append(prompt) or good,100,50))
            conn.commit()
        self.assertEqual(out,dict(ready=1,held=0,fixed=1))
        self.assertIn('The CEO asked for this change: mention they build in Mona Vale',asks[1])
        p=self.prospect('Fictional Builds')
        self.assertEqual(p['draft_source'],'ai');self.assertIn('I noticed you do not have a website',p['draft_body']);self.assertIn('no thanks',p['draft_body'])
        self.assertEqual(self.rows('writer_usage')[0]['calls'],2)

    def test_sweep_cuts_sydney_into_squares_and_finds_no_website_businesses(self):
        squares=sweep.tiles(sweep.REGIONS[0])
        self.assertEqual(len(squares),165);self.assertEqual(sweep.REGIONS[0][1],'Sydney')
        q=sweep.tile_query(squares[0])
        self.assertIn('[!"website"]',q);self.assertIn('"craft"~"^(',q);self.assertIn('plumber',q);self.assertIn('hairdresser',q)
        sleeps=[]
        with self.conn() as conn,patch('lead_engine.http_json',side_effect=[TILE,{'elements':[]}]):
            owner=self.owner(conn)
            found,searched,notes=sweep.run(conn,owner,2,sleep=sleeps.append)
            self.assertEqual((found,searched,notes),(2,2,[]));self.assertEqual(sleeps,[2.0])
            prog=sweep.progress(conn,owner)
            self.assertEqual((prog[0]['done'],prog[0]['found']),(2,2));self.assertEqual(len(prog),len(sweep.REGIONS)+len(sweep.CATCH_ALL))
            states=sweep.by_state(conn,owner)
            self.assertEqual([r['name'] for r in states],['Sydney (first)']+list(sweep.STATES))
            self.assertEqual(states[0]['found'],2)
            self.assertEqual(sweep.next_tiles(conn,owner,1)[0][1],2)
        sparky=self.prospect('No Site Sparkies')
        self.assertEqual((sparky['trade'],sparky['suburb'],sparky['reason']),('Electricians','Manly','none'))
        self.assertEqual(self.prospect('Corner Cuts')['suburb'],'Sydney')
        self.assertFalse([r for r in self.rows('prospects') if r['name']=='Mystery Shop'])
        with self.conn() as conn,patch('lead_engine.http_json',side_effect=[TILE]):
            self.assertEqual(sweep.run(conn,self.owner(conn),1,sleep=sleeps.append)[0],0)  # never added twice

    def test_the_sweep_covers_every_state_and_territory_after_sydney(self):
        self.assertEqual(sweep.REGIONS[0][0],'sydney')
        self.assertEqual({r[2] for r in sweep.REGIONS},set(sweep.STATES))
        self.assertEqual([c[2] for c in sweep.CATCH_ALL],list(sweep.STATES))
        self.assertEqual(len(sweep.jobs(sweep.CATCH_ALL[0])),len(lead_engine.TRADES))
        q=sweep.state_query('WA','Plumbers')
        self.assertIn('area["ISO3166-2"="AU-WA"]',q);self.assertIn('"craft"="plumber"',q);self.assertIn('[!"website"]',q)
        self.assertEqual(sum(len(sweep.jobs(r)) for r in sweep.plan()),1863)
        self.assertEqual(sweep.plan(False),sweep.REGIONS[:1])
        with self.conn() as conn:
            owner=self.owner(conn)
            for r in sweep.plan():
                for i in range(len(sweep.jobs(r))):conn.execute("INSERT INTO sweep_tiles VALUES(?,?,?,'x',0)",(owner,r[0],i))
            conn.execute("DELETE FROM sweep_tiles WHERE region='state-nt' AND idx=0");conn.commit()
            self.assertEqual(sweep.next_tiles(conn,owner,5),[(sweep.CATCH_ALL[-1],0,('trade','Plumbers'))])
            with patch('lead_engine.http_json',side_effect=lead_engine.WorkflowError('The map service sent back too much data. Try a smaller radius.')):
                found,searched,notes=sweep.run(conn,owner,1)
            self.assertEqual(searched,1);self.assertIn('too big for one search',notes[0])  # a huge state search never blocks the sweep

    def test_sweep_stops_politely_when_the_map_is_busy(self):
        with self.conn() as conn,patch('lead_engine.http_json',side_effect=lead_engine.WorkflowError('busy')):
            found,searched,notes=sweep.run(conn,self.owner(conn),5)
        self.assertEqual((found,searched),(0,0));self.assertIn('busy',notes[0])
        self.assertEqual(self.rows('sweep_tiles'),[])

    def test_phone_buzz_rules(self):
        self.shift()
        sent=[]
        send=lambda conn,owner,title,message,click='':sent.append((title,message,click)) or True
        with self.conn() as conn:
            owner=self.owner(conn)
            at=datetime(2026,10,21,7,30,tzinfo=team.TZ)
            self.assertFalse(team.notify(conn,owner,at.replace(hour=6),send))  # too early
            self.assertTrue(team.notify(conn,owner,at,send))
            self.assertFalse(team.notify(conn,owner,at.replace(hour=11),send))  # pile has not grown
            self.assertNotIn('Fictional',sent[0][0]+sent[0][1])  # no business names on the public ntfy server
            self.assertEqual(sent[0][2],'')
            team._save(conn,owner,phone_url='https://benjis-laptop.tail1234.ts.net',last_ping_count=0,pings_today=1,ping_day='2026-10-21',last_ping_at=at.isoformat())
            self.assertFalse(team.notify(conn,owner,at.replace(hour=9),send))  # within 3 hours
            self.assertTrue(team.notify(conn,owner,at.replace(hour=12),send))
            self.assertEqual(sent[-1][2],'https://benjis-laptop.tail1234.ts.net/m')
            team._save(conn,owner,pings_today=3,last_ping_count=0)
            self.assertFalse(team.notify(conn,owner,at.replace(hour=18),send))  # three a day is the limit

    def test_phone_page_yes_and_home_screen_files(self):
        self.shift()
        page=self.client.get('/m').get_data(as_text=True)
        self.assertIn('Yes or no',page);self.assertIn('Fictional Builds',page);self.assertIn('No, because',page);self.assertIn('manifest.webmanifest',page)
        p=self.prospect('Fictional Builds')
        response=self.post(f'/find-customers/{p["id"]}/approve',dict(subject=p['draft_subject'],body=p['draft_body'],next='phone'))
        self.assertTrue(response.headers['Location'].endswith('/m'))
        self.assertEqual(self.prospect('Fictional Builds')['stage'],'Approved')
        self.assertEqual(self.rows('team_feedback')[0]['edited'],0)
        with self.client.session_transaction() as s:s.clear()
        manifest=self.client.get('/manifest.webmanifest');self.assertEqual(manifest.json['start_url'],'/m')
        self.assertIn('Nothing is cached',self.client.get('/sw.js').get_data(as_text=True))
        self.assertEqual(self.client.get('/m').status_code,302)  # the queue itself needs a login

    def test_settings_only_take_a_private_tailscale_address(self):
        ok=self.post('/team/settings',dict(tiles_per_night='30',daily_drafts='20',all_australia='0',pings='1',phone_url='https://Benjis-Laptop.tail1234.ts.net/'))
        self.assertEqual(ok.status_code,302)
        row=self.rows('team_settings')[0]
        self.assertEqual((row['tiles_per_night'],row['daily_drafts'],row['all_australia'],row['phone_url']),(30,20,0,'https://benjis-laptop.tail1234.ts.net'))
        bad=self.post('/team/settings',dict(tiles_per_night='30',daily_drafts='20',all_australia='1',pings='1',phone_url='https://my-site.example.com'),follow_redirects=True)
        self.assertIn('Tailscale',bad.get_data(as_text=True))
        self.assertEqual(self.rows('team_settings')[0]['phone_url'],'https://benjis-laptop.tail1234.ts.net')

    def test_airtasker_quote_keeps_contact_details_off_the_platform(self):
        page=self.post('/team/airtasker',dict(task='Need a Shopify store for my candle business in Penrith')).get_data(as_text=True)
        self.assertIn('an online shop',page);self.assertIn('free one-page mock-up',page)
        quote=team.airtasker_quote('Need a website for my salon bookings',dict(name='Benji Price'))
        self.assertEqual(team.airtasker_problems(quote),[]);self.assertIn('booking website',quote)
        self.assertTrue(team.airtasker_problems('Call me on 0400 123 456'));self.assertTrue(team.airtasker_problems('see www.mysite.com.au'))

    def test_ai_budget_is_paced_through_the_month(self):
        self.assertAlmostEqual(smart_writer.paced_cents(2000,date(2026,10,1)),2000/31+400)
        self.assertEqual(smart_writer.paced_cents(2000,date(2026,10,31)),2000)
        self.assertEqual(smart_writer.DEFAULT_CAP_CENTS,2000)

    def test_seo_checker_notes_google_basics(self):
        bare=lead_engine.seo_notes('<html><title>Home</title></html>','<html><title>home</title></html>')
        self.assertEqual(bare,['no_description','no_h1','no_tap_to_call','no_local_schema','thin_title'])
        html='<title>Manly Plumbing | Plumber in Manly</title><meta name="description" content="Local plumber in Manly for blocked drains"><h1>Hi</h1><a href="tel:0400">Call</a><script type="application/ld+json">{"@type":"LocalBusiness"}</script>'
        self.assertEqual(lead_engine.seo_notes(html,html.casefold()),[])


if __name__=='__main__':
    unittest.main()

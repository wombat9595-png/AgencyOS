"""Call Mode, Get paid, proposals, Studio, publish pack and client growth. No network, nothing sent."""
from contextlib import closing
from datetime import date,datetime,timedelta
import io
import os
import sqlite3
import unittest
import zipfile
from unittest.mock import patch
from cryptography.fernet import Fernet
import app as application
import getpaid
import lead_engine
import phone
import pitch
import test_agencyos as fixtures
from test_lead_engine import GEO,OSM,fake_get

TODAY=date(2026,10,21)
SETTINGS=dict(name='Benji Price',business='Benji Price Web Design',email='benji.price.webdesign@gmail.com',phone='0400 123 456',area='Northern Beaches',daily_target=10)


class VipTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def conn(self):
        conn=sqlite3.connect(application.DB_PATH);conn.row_factory=sqlite3.Row
        return closing(conn)

    def leads(self):
        with patch('lead_engine.http_json',side_effect=[GEO,OSM]),patch('lead_engine._get',side_effect=fake_get),patch('lead_engine.today',return_value=TODAY):
            self.post('/find-customers/search',dict(trade='Plumbers',town='Penrith NSW',radius='10'))
        return {r['name']:r for r in self.rows('prospects')}

    def test_grades_and_calling_hours(self):
        base=dict(reason='none',trade='Builders',phone='0400 000 000',email='',stage='New')
        self.assertEqual(phone.grade(base),'A')
        self.assertEqual(phone.grade(dict(base,reason='ok',trade='Cafes',phone='')),'C')
        tz=phone.TZ
        self.assertTrue(phone.calling_window(datetime(2026,10,21,10,0,tzinfo=tz))[0])
        self.assertFalse(phone.calling_window(datetime(2026,10,21,20,30,tzinfo=tz))[0])
        self.assertFalse(phone.calling_window(datetime(2026,10,24,17,30,tzinfo=tz))[0])  # Saturday after 5
        self.assertFalse(phone.calling_window(datetime(2026,10,25,11,0,tzinfo=tz))[0])  # Sunday
        self.assertFalse(phone.calling_window(datetime(2026,12,25,11,0,tzinfo=tz))[0])
        self.assertIn(date(2026,4,3),phone.national_holidays(2026))  # Good Friday 2026

    def test_call_mode_logs_calls_and_offers_the_one_two(self):
        leads=self.leads()
        with patch('lead_engine.today',return_value=TODAY):
            page=self.client.get('/calls').get_data(as_text=True)
            self.assertIn('Call Mode',page);self.assertIn('Old Site Plumbing',page);self.assertIn('They said',page)
            self.assertIn('word of mouth',page)
            pid=leads['Old Site Plumbing']['id']
            response=self.post(f'/calls/{pid}/log',dict(outcome='no_answer'))
            self.assertIn('just='+str(pid),response.headers['Location'])
            page=self.client.get(response.headers['Location']).get_data(as_text=True)
            self.assertIn('Just tried calling',page);self.assertIn('Reply STOP',page)
            p=[r for r in self.rows('prospects') if r['id']==pid][0]
            self.assertEqual(p['stage'],'Contacted');self.assertEqual(p['next_on'],(TODAY+timedelta(days=2)).isoformat())
            self.post(f'/calls/{pid}/log',dict(outcome='callback',callback_on=(TODAY+timedelta(days=5)).isoformat(),note='Ask for Dave'))
            p=[r for r in self.rows('prospects') if r['id']==pid][0]
            self.assertEqual(p['next_on'],(TODAY+timedelta(days=5)).isoformat());self.assertIn('Ask for Dave',p['notes'])
            board=self.client.get('/calls').get_data(as_text=True)
            self.assertIn('2 / 5',board)
            with self.conn() as conn:
                b=phone.scoreboard(conn,1,TODAY)
            self.assertEqual((b['calls'],b['talks']),(2,1))
            self.assertIn('scoreboard',self.client.get('/business').get_data(as_text=True))

    def test_one_two_and_objections_are_personal(self):
        p=dict(id=1,name='Fictional Builds',trade='Builders',suburb='Mona Vale',email='hi@x.example',phone='0400 111 222',website='',reason='none',site_check='',touches=0,stage='New',score=80)
        kit=phone.one_two(p,SETTINGS,'https://benji.pages.dev/p/abc/')
        self.assertIn('no thanks',kit['body']);self.assertIn('Benji Price Web Design',kit['body']);self.assertIn('https://benji.pages.dev/p/abc/',kit['text'])
        self.assertTrue(kit['sms'].startswith('sms:0400111222'))
        answers=dict((k,a) for k,_s,a in phone.objections(p,SETTINGS))
        self.assertIn('Fictional Builds',answers['who']);self.assertNotIn('{',''.join(answers.values()))

    def test_get_paid_bank_details_deposit_pdf_and_money_in(self):
        key=Fernet.generate_key().decode()
        with patch.dict(os.environ,{'AGENCYOS_BANK_ENCRYPTION_KEY':key}):
            self.assertIn('your bank details',self.client.get('/get-paid').get_data(as_text=True))
            r=self.post('/get-paid/details',dict(business_name='Benji Price Web Design',business_abn='12 345 678 901',business_email='benji.price.webdesign@gmail.com',gst_mode='not_registered',
              account_name='B Price',bsb='062-000',account_number='12345678'))
            self.assertEqual(r.status_code,302)
            control=self.rows('p7_control')[0]
            self.assertNotIn('12345678',control['bank_ciphertext']);self.assertTrue(control['bank_ciphertext'])
            page=self.client.get('/get-paid').get_data(as_text=True)
            self.assertNotIn('12345678',page);self.assertIn('Saved and encrypted',page)
            self.post('/get-paid/new',dict(client_name='Fictional Builds',client_email='hi@fictional.example',package='Signature (founding)',kind='deposit'))
            bill=self.rows('bills')[0]
            self.assertEqual((bill['number'],bill['total_cents'],bill['gst_cents']),('INV-0001',95000,0))
            pdf=self.client.get('/get-paid/'+str(bill['id'])+'/pdf').get_data()
            self.assertTrue(pdf.startswith(b'%PDF'))
            import base64,re as _re,zlib
            text=pdf
            for stream in _re.findall(rb'stream\r?\n(.*?)endstream',pdf,_re.S):
                try:text+=zlib.decompress(base64.a85decode(stream.strip().removesuffix(b'~>')))
                except (ValueError,zlib.error):pass
            self.assertIn(b'062-000',text);self.assertIn(b'12345678',text);self.assertIn(b'INV-0001',text);self.assertIn(b'12 345 678 901',text)
            self.post('/get-paid/'+str(bill['id'])+'/paid',dict())
            self.assertEqual(self.rows('bills')[0]['status'],'Ready')
            self.post('/get-paid/'+str(bill['id'])+'/paid',dict(confirm='yes'))
            self.assertEqual(self.rows('bills')[0]['status'],'Paid')
            import first_sale
            with self.conn() as conn:
                self.assertEqual(first_sale.metrics(conn,1)['owner_bank_cents'],95000)
            # Monthly with GST registered: 10% on top.
            self.post('/get-paid/details',dict(business_name='Benji Price Web Design',gst_mode='registered_10'))
            self.post('/get-paid/new',dict(client_name='Fictional Builds',package='Care',kind='monthly',profile_care='yes'))
            b2=[b for b in self.rows('bills') if b['number']=='INV-0002'][0]
            self.assertEqual((b2['amount_cents'],b2['gst_cents'],b2['total_cents']),(11800,1180,12980))
            r=self.post('/get-paid/links',dict(card_link='https://evil.example/pay'))
            self.assertEqual(self.rows('pay_settings'),[])
            self.post('/get-paid/links',dict(card_link='https://buy.stripe.com/test_abc123'))
            self.assertEqual(self.rows('pay_settings')[0]['card_link'],'https://buy.stripe.com/test_abc123')

    def test_bad_bank_details_are_refused(self):
        with patch.dict(os.environ,{'AGENCYOS_BANK_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            self.post('/get-paid/details',dict(business_name='X',gst_mode='not_registered',account_name='B',bsb='12',account_number='1'))
            self.assertEqual(self.rows('p7_control')[0]['bank_ciphertext'],'')

    def test_proposal_video_studio_and_publish_pack(self):
        leads=self.leads();pid=leads['Old Site Plumbing']['id']
        with patch('lead_engine.today',return_value=TODAY):
            self.post('/night-shift/beats',dict(trade='Builders',town='Mona Vale NSW',radius='10'))
            proposal=self.client.get(f'/pitch/{pid}/proposal').get_data(as_text=True)
            self.assertIn('Old Site Plumbing',proposal);self.assertIn('A$1,900',proposal);self.assertIn('Not secure',proposal);self.assertIn('noindex',proposal)
            self.assertIn('Shift + Command + 5',self.client.get(f'/pitch/{pid}/video').get_data(as_text=True))
            self.assertIn('Publish pack',self.client.get('/studio').get_data(as_text=True))
            home=self.client.get('/studio/site').get_data(as_text=True)
            self.assertIn('tell your story',home);self.assertIn('websites-for-builders-mona-vale',home)
            self.assertIn('Mona Vale',self.client.get('/studio/site/websites-for-builders-mona-vale').get_data(as_text=True))
            self.post('/studio/settings',dict(booking_url='https://calendar.app.google/abc123',site_url='https://benji-web.pages.dev'))
            self.post(f'/find-customers/{pid}/approve',dict(subject='Quick idea for Old Site Plumbing',body='Hi there, a message for Old Site Plumbing. Reply no thanks to stop.'))
            self.assertEqual([r for r in self.rows('prospects') if r['id']==pid][0]['variant'],'Quick idea for {name}')
            blob=self.client.get('/studio/pack.zip').get_data()
        z=zipfile.ZipFile(io.BytesIO(blob));names=z.namelist()
        self.assertIn('index.html',names);self.assertIn('websites-for-builders-mona-vale/index.html',names)
        self.assertIn('demos/builder/index.html',names);self.assertIn('kit/motion.js',names)
        self.assertIn('Disallow: /p/',z.read('robots.txt').decode())
        previews=[n for n in names if n.startswith('p/') and n.endswith('/index.html')]
        self.assertTrue(previews)
        slug=[r for r in self.rows('public_links') if r['ref_id']==pid][0]['slug']
        self.assertIn('p/'+slug+'/site.html',names);self.assertGreaterEqual(len(slug),12)
        with application.app.test_request_context(),self.conn() as conn:
            self.assertEqual(pitch.preview_url(conn,1,pid),'https://benji-web.pages.dev/p/'+slug+'/')
        with patch('lead_engine.today',return_value=TODAY):
            self.assertIn('/p/'+slug+'/',self.client.get('/calls').get_data(as_text=True))
            self.assertIn('calendar.app.google/abc123',self.client.get('/find-customers').get_data(as_text=True))

    def test_replies_stop_follow_ups_and_ping(self):
        leads=self.leads();p=leads['Fictional Pipes']
        sent=[]
        with self.conn() as conn:
            conn.execute("UPDATE prospects SET stage='Contacted',touches=1,next_on='2026-10-25' WHERE id=?",(p['id'],))
            conn.execute("INSERT INTO gmail_mail(owner_id,external_id,thread_id,sender,content_cipher,intent_json,received_at,direction) VALUES(1,'m1','t1','hello@fictional-pipes.example','x','{}','2099-01-01T00:00:00+00:00','incoming')")
            conn.commit()
            with patch('lead_engine.today',return_value=TODAY):
                self.assertEqual(pitch.detect_replies(conn,1,send=lambda c,o,t,m:sent.append(t)),1)
                self.assertEqual(pitch.detect_replies(conn,1,send=lambda c,o,t,m:sent.append(t)),0)
        row=[r for r in self.rows('prospects') if r['id']==p['id']][0]
        self.assertTrue(row['replied_at']);self.assertEqual(row['next_on'],TODAY.isoformat());self.assertEqual(sent,['Fictional Pipes replied'])
        with patch('pitch.urlrequest.urlopen') as opened:
            with self.conn() as conn:self.assertFalse(pitch.ping(conn,1,'t','m'))
            opened.assert_not_called()

    def test_growth_reviews_testimonials_referrals_and_portal(self):
        self.post('/clients/add',dict(client_name='Fictional Builds',contact_email='hi@fb.example',plan='Care',billing='monthly',started_on='2026-09-01'))
        clients=self.rows('plan_clients')
        self.assertTrue(clients,'client add route changed')
        cid=clients[0]['id']
        self.post('/studio/review-link',dict(review_url='https://g.page/r/benji/review'))
        self.post(f'/studio/clients/{cid}/stage',dict(site_stage='Live',site_url='https://fictionalbuilds.example'))
        page=self.client.get('/studio').get_data(as_text=True)
        self.assertIn('g.page/r/benji/review',page);self.assertIn('Time to ask for a review',page)
        self.post(f'/studio/clients/{cid}/quote',dict(testimonial='Phone has not stopped ringing.'))
        self.assertEqual(self.rows('client_growth')[0]['testimonial'],'')
        self.post(f'/studio/clients/{cid}/quote',dict(testimonial='Phone has not stopped ringing.',ok='yes'))
        self.assertIn('Phone has not stopped ringing.',self.client.get('/studio/site').get_data(as_text=True))
        leads=self.leads();lead=leads['Old Site Plumbing']
        self.post('/studio/referral',dict(client_id=cid,prospect_id=lead['id']))
        with self.conn() as conn:
            conn.execute("UPDATE prospects SET stage='Customer' WHERE id=?",(lead['id'],));conn.commit()
        self.assertIn('1 free month owed',self.client.get('/studio').get_data(as_text=True))
        blob=self.client.get('/studio/pack.zip').get_data()
        z=zipfile.ZipFile(io.BytesIO(blob));portal=[n for n in z.namelist() if n.startswith('c/')]
        self.assertEqual(len(portal),1);self.assertIn('Fictional Builds',z.read(portal[0]).decode())

    def test_subject_lines_learn_a_winner(self):
        with self.conn() as conn:
            for i in range(60):
                variant=lead_engine.SUBJECTS[i%3];stage='Interested' if (i%3==2 and i%2==0) else 'Contacted'
                conn.execute("INSERT INTO prospects(owner_id,source_id,name,stage,touches,variant,created_at) VALUES(1,?,?,?,1,?,'x')",('s'+str(i),'Biz '+str(i),stage,variant))
            conn.commit()
            self.assertEqual(lead_engine.best_subject(conn,1),lead_engine.SUBJECTS[2])
            s=lead_engine.settings(conn,1)
        self.assertEqual(lead_engine.subject_for(dict(id=7,name='Acme'),s),'Made Acme a free website preview')
        self.assertEqual(lead_engine.subject_for(dict(id=4,name='Acme'),dict(best_subject='')),'Quick idea for Acme')
        self.assertIn('Made {name} a free website preview',self.client.get('/calls').get_data(as_text=True).replace('…','{name}'))

    def test_settings_form_keeps_new_columns(self):
        self.post('/calls/settings',dict(call_target='8'))
        self.post('/find-customers/settings',dict(name='Benji Price',business='Benji Price Web Design',email='benji.price.webdesign@gmail.com',phone='',area='Northern Beaches',daily_target='12'))
        row=self.rows('prospect_settings')[0]
        self.assertEqual((row['call_target'],row['daily_target'],row['area']),(8,12,'Northern Beaches'))


if __name__=='__main__':
    unittest.main()

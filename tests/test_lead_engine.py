"""Find customers: fictional OpenStreetMap results and websites; no network, nothing sent."""
from datetime import date
import json
import unittest
from unittest.mock import patch
import lead_engine
import test_agencyos as fixtures

TODAY=date(2026,10,17)
GEO=[{'lat':'-33.75','lon':'150.69','display_name':'Penrith, New South Wales, Australia'}]
OSM={'elements':[
 {'type':'node','id':1,'tags':{'name':'Fictional Pipes','craft':'plumber','phone':'02 4700 0001','email':'hello@fictional-pipes.example','addr:suburb':'Penrith'}},
 {'type':'node','id':2,'tags':{'name':'Old Site Plumbing','craft':'plumber','website':'http://oldsite.example','phone':'0400 000 002','addr:suburb':'Emu Plains'}},
 {'type':'way','id':3,'tags':{'name':'Facebook Only Drains','craft':'plumber','contact:facebook':'https://www.facebook.com/fodrains','addr:suburb':'Penrith'}},
 {'type':'node','id':4,'tags':{'name':'Good Site Plumbing','craft':'plumber','website':'https://goodsite.example','email':'jobs@goodsite.example'}},
 {'type':'node','id':5,'tags':{'craft':'plumber'}},
]}
OLD='<html><head><title>Old Site</title></head><body>&copy; 2015 Old Site Plumbing</body></html>'.encode()
GOOD='<html><head><meta name="viewport" content="width=device-width"><title>Good</title></head><body>© 2026</body></html>'.encode()


def fake_get(url,timeout=8):
    if url.startswith('https://oldsite.example'):raise OSError('no tls')
    if url.startswith('http://oldsite.example'):return 200,'',OLD
    if url=='https://goodsite.example/':return 301,'https://www.goodsite.example/',b''
    if url=='https://www.goodsite.example/':return 200,'',GOOD
    raise OSError('unexpected '+url)


class LeadEngineTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def search(self,osm=OSM):
        with patch('lead_engine.http_json',side_effect=[GEO,osm]) as fetch,patch('lead_engine._get',side_effect=fake_get),patch('lead_engine.today',return_value=TODAY):
            response=self.post('/find-customers/search',dict(trade='Plumbers',town='Penrith NSW',radius='10'))
        return response,fetch

    def prospect(self,name):
        return next(r for r in self.rows('prospects') if r['name']==name)

    def page(self):
        with patch('lead_engine.today',return_value=TODAY):
            return self.client.get('/find-customers').data.decode()

    def test_find_scores_and_checks_websites(self):
        response,fetch=self.search()
        self.assertEqual(response.status_code,302)
        self.assertIn('craft',fetch.call_args_list[1].args[1].decode())
        self.assertEqual(len(self.rows('prospects')),4)  # the unnamed one is ignored
        self.assertEqual(self.prospect('Fictional Pipes')['reason'],'none')
        self.assertEqual(self.prospect('Facebook Only Drains')['reason'],'facebook')
        old=self.prospect('Old Site Plumbing');check=json.loads(old['site_check'])
        self.assertEqual(old['reason'],'not_mobile');self.assertIn('not_secure',check['findings']);self.assertIn('old',check['findings'])
        good=self.prospect('Good Site Plumbing')
        self.assertEqual(good['reason'],'ok');self.assertEqual(good['score'],20)
        page=self.page()
        self.assertIn('Fictional Pipes',page);self.assertNotIn('Call script',page)
        self.assertIn('OpenStreetMap contributors',page)
        # Searching again adds nobody twice; the geocode is cached.
        with patch('lead_engine.http_json',side_effect=[OSM]),patch('lead_engine._get',side_effect=fake_get):
            self.post('/find-customers/search',dict(trade='Plumbers',town='penrith  nsw',radius='10'))
        self.assertEqual(len(self.rows('prospects')),4)

    def test_email_flow_with_follow_ups_and_opt_out(self):
        self.search();pid=self.prospect('Fictional Pipes')['id']
        refused=self.post(f'/find-customers/{pid}/approve',dict(subject='Hi',body='A message with no way to unsubscribe at all.'))
        self.assertEqual(refused.status_code,400)
        subject,body=lead_engine.draft(self.prospect('Fictional Pipes'),dict(name='Benji Price',business='Benji Price Web Design',email='b@example.com',phone='',area=''))
        self.assertIn('no thanks',body);self.assertIn('Benji Price Web Design',body)
        with patch('lead_engine.today',return_value=TODAY):
            self.post(f'/find-customers/{pid}/approve',dict(subject=subject,body=body))
            self.assertIn('mailto:hello%40fictional-pipes.example',self.page())
            self.post(f'/find-customers/{pid}/sent')
        p=self.prospect('Fictional Pipes')
        self.assertEqual((p['stage'],p['touches'],p['next_on']),('Contacted',1,'2026-10-21'))
        self.assertEqual(lead_engine.draft(p,dict(name='B',business='X',email='b@example.com',phone='',area=''))[0],'Re: Website for Fictional Pipes?')
        later=date(2026,10,21)
        with patch('lead_engine.today',return_value=later):
            self.assertIn('Follow-up 1 due',self.client.get('/find-customers').data.decode())
            self.post(f'/find-customers/{pid}/approve',dict(subject='Re: x',body='Following up, reply no thanks to stop.'))
            self.post(f'/find-customers/{pid}/sent')
        for day in (date(2026,10,27),):
            with patch('lead_engine.today',return_value=day):
                self.post(f'/find-customers/{pid}/approve',dict(subject='Re: x',body='Last note, reply no thanks to stop.'))
                self.post(f'/find-customers/{pid}/sent')
        self.assertEqual(self.prospect('Fictional Pipes')['touches'],3)
        with patch('lead_engine.today',return_value=date(2026,11,4)):
            self.client.get('/find-customers')
        self.assertEqual(self.prospect('Fictional Pipes')['stage'],'No reply')

    def test_interested_becomes_customer(self):
        self.search();pid=self.prospect('Old Site Plumbing')['id']
        with patch('lead_engine.today',return_value=TODAY):
            self.post(f'/find-customers/{pid}/interested')
            self.assertIn('Make them a customer',self.page())
            response=self.post(f'/find-customers/{pid}/customer')
        self.assertEqual(response.status_code,302)
        lead=self.rows('leads')[0]
        self.assertEqual((lead['business_name'],lead['status'],lead['source']),('Old Site Plumbing','Interested','Find customers'))
        self.assertEqual(self.prospect('Old Site Plumbing')['stage'],'Customer')
        self.assertEqual(self.post(f'/find-customers/{pid}/customer').status_code,400)

    def test_do_not_contact_is_never_re_added(self):
        self.search();pid=self.prospect('Fictional Pipes')['id']
        self.post(f'/find-customers/{pid}/do_not_contact')
        self.search()
        self.assertEqual([r['stage'] for r in self.rows('prospects') if r['name']=='Fictional Pipes'],['Do not contact'])
        self.assertNotIn('id="p'+str(pid)+'"',self.page())

    def test_manual_add_and_home_and_ceo(self):
        home=self.client.get('/business').data.decode()
        self.assertIn('Find your first local businesses',home)
        with patch('lead_engine._get',side_effect=OSError('offline')):
            self.post('/find-customers/add',dict(name='Van Seen Electrical',trade='Electricians',suburb='Penrith',phone='0400 000 009',email='jobs@vanseen.example',website='https://vanseen.example'))
        p=self.prospect('Van Seen Electrical')
        self.assertEqual(p['reason'],'down')
        self.assertEqual(self.post('/find-customers/add',dict(name='Van Seen Electrical',suburb='Penrith')).status_code,400)
        with patch('lead_engine.today',return_value=TODAY):
            home=self.client.get('/business').data.decode()
            self.assertIn('to contact today',home)
            answer=self.client.get('/business?ask=How are the leads going?').data.decode()
        self.assertIn('Found 1 businesses',answer)

    def test_settings_feed_drafts(self):
        self.assertEqual(self.post('/find-customers/settings',dict(name='Benji',business='',email='x',daily_target='10')).status_code,400)
        self.post('/find-customers/settings',dict(name='Benji Price',business='Price Web Co',email='benji@example.com',phone='0400 111 222',area='Penrith NSW',daily_target='15'))
        self.search()
        page=self.page()
        self.assertIn('Price Web Co',page);self.assertIn('based in Penrith NSW',page);self.assertIn('0 of 15',page)

    def test_approved_email_goes_to_gmail_drafts_and_is_noticed_when_sent(self):
        import os,time,sqlite3,base64
        from contextlib import closing
        from cryptography.fernet import Fernet
        import gmail_agent as gmail,app as application
        with patch.dict(os.environ,AGENCYOS_GMAIL_KEY=Fernet.generate_key().decode(),AGENCYOS_GMAIL_KEY_FILE=''):
            self.search();pid=self.prospect('Fictional Pipes')['id']
            with closing(sqlite3.connect(application.DB_PATH)) as conn:
                token=dict(access_token='synthetic',refresh_token='synthetic',expires_at=time.time()+3600,scope=gmail.READ+' '+gmail.COMPOSE)
                conn.execute('INSERT INTO gmail_accounts(owner_id,email,token_cipher,connected_at) VALUES(1,?,?,?)',(gmail.ACCOUNT,gmail.seal(token),'fixture'));conn.commit()
            calls=[]
            def google(url,token=None,data=None,form=False):
                calls.append((url,data))
                if url.endswith('/drafts'):return {'id':'draft-1'}
                if '/messages?' in url:return {'messages':[{'id':'m1'}]} if len(calls)>2 else {}
                raise AssertionError('unexpected '+url)
            with patch('gmail_agent.google_request',side_effect=google),patch('lead_engine.today',return_value=TODAY):
                self.post(f'/find-customers/{pid}/approve',dict(subject='Website for Fictional Pipes?',body='Hi there, a message. Reply no thanks to stop.'))
                self.assertEqual(self.prospect('Fictional Pipes')['gmail_draft_id'],'draft-1')
                raw=base64.urlsafe_b64decode(calls[0][1]['message']['raw']).decode()
                self.assertIn('To: hello@fictional-pipes.example',raw);self.assertNotIn('send',calls[0][0])
                self.assertIn('Open Gmail Drafts',self.page())  # page load checks Sent: nothing yet
                self.assertEqual(self.prospect('Fictional Pipes')['stage'],'Approved')
                self.page()  # now Gmail shows it sent
            p=self.prospect('Fictional Pipes')
            self.assertEqual((p['stage'],p['touches'],p['gmail_draft_id']),('Contacted',1,''))
            self.assertFalse(any('send' in url for url,_ in calls))

    def test_free_mockup_is_one_tap(self):
        self.search();p=self.prospect('Old Site Plumbing')
        with patch('lead_engine.today',return_value=TODAY):
            page=self.client.get(f'/find-customers/{p["id"]}/mockup').data.decode()
            download=self.client.get(f'/find-customers/{p["id"]}/mockup?download=1')
        self.assertIn('Old Site Plumbing',page);self.assertIn('Blocked drains',page);self.assertIn('Emu Plains',page)
        self.assertIn('tel:0400000002',page);self.assertIn('Free mock-up made for',page);self.assertIn('How it works',page)
        self.assertIn('attachment; filename="old-site-plumbing-mockup.html"',download.headers['Content-Disposition'])
        self.assertIn('Free mock-up',self.page())
        self.assertEqual(self.client.get('/find-customers/9999/mockup').status_code,400)

    def test_check_site_never_follows_to_bad_scheme(self):
        result=lead_engine.check_site('https://x.example',get=lambda url,timeout=8:(302,'file:///etc/passwd',b''))
        self.assertEqual(result['findings'],['down'])


if __name__=='__main__':
    unittest.main()

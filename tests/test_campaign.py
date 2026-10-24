"""The 30-day plan: batches, the extras each email carries, today's videos and what's working. No network, nothing sent."""
from datetime import date
import unittest
from unittest.mock import patch
import autosend
import campaign
import lead_engine
import test_autosend


class CampaignTest(unittest.TestCase):
    for _name in ('setUp','tearDown','setUp_base','tearDown_base','post','rows','conn','add','switch_on'):
        locals()[_name]=getattr(test_autosend.AutoSendTest,_name)

    def lead(self,conn,name,trade,suburb,score=80,**extra):
        cols=dict(owner_id=1,source_id='c-'+name,name=name,trade=trade,suburb=suburb,email=name.lower().replace(' ','')+'@x.example',
                  reason='old',score=score,created_at='2026-10-20T00:00:00+00:00',**extra)
        cur=conn.execute('INSERT INTO prospects('+','.join(cols)+') VALUES('+','.join('?'*len(cols))+')',tuple(cols.values()))
        return conn.execute('SELECT * FROM prospects WHERE id=?',(cur.lastrowid,)).fetchone()

    def mark(self,conn,p):
        lead_engine.mark_sent(conn,1,p,date(2026,10,20));conn.commit()

    def test_batches_finish_one_trade_in_one_area_first(self):
        with self.conn() as conn:
            a=self.lead(conn,'Manly Pipes','Plumbers','Manly',60);b=self.lead(conn,'Manly Drains','Plumbers','Manly',55)
            c=self.lead(conn,'Top Sparks','Electricians','Mona Vale',99);d=self.lead(conn,'Dee Why Pipes','Plumbers','Dee Why',90)
            names=lambda rows:[p['name'] for p in campaign.order(conn,1,rows)]
            self.assertEqual(names([a,b,c,d])[0],'Top Sparks')  # nothing sent yet: start with the best lead's batch
            self.mark(conn,a)
            self.assertEqual(names([b,c,d]),['Manly Drains','Dee Why Pipes','Top Sparks'])  # same trade and area, then same trade
            with patch('campaign.BATCH_SIZE',1):
                self.assertEqual(names([b,c,d])[0],'Dee Why Pipes')  # batch full: next area, same trade
            self.assertEqual(campaign.batch_now(conn,1),dict(trade='Plumbers',suburb='Manly',sent=1,size=50))

    def test_auto_send_picks_in_batch_order(self):
        with self.conn() as conn:
            first=self.add(conn,'Fictional Builds','hello@fictionalbuilds.example',suburb='Manly')
            self.add(conn,'Other Area Builds','hi@otherarea.example',suburb='Penrith')
            conn.execute("UPDATE prospects SET score=95 WHERE id!=?",(first,));conn.commit()
            self.mark(conn,conn.execute('SELECT * FROM prospects WHERE id=?',(first,)).fetchone())
            self.add(conn,'Second Manly Builds','yo@secondmanly.example',suburb='Manly')
            self.assertEqual(autosend.candidates(conn,1)[0]['name'],'Second Manly Builds')

    def test_first_line_names_the_problem_and_no_links(self):
        with self.conn() as conn:
            p=self.lead(conn,'Old Co','Plumbers','Manly',website='http://old.example',site_check='{"findings":["not_secure"],"year":0}')
            s=lead_engine.settings(conn,1)
            _,body=lead_engine.draft(p,s,'first',proof='"Great job" (Fictional Builds)')
        first=body.split('\n\n')[1]
        self.assertTrue(first.startswith('I had a look at old.example and browsers flag it as "Not secure"'),first)
        self.assertIn('A recent client said: "Great job" (Fictional Builds)',body)
        self.assertNotIn('http',body.split('\n\nCheers,')[0])

    def test_preview_link_goes_in_follow_up_one_only_when_online(self):
        with self.conn() as conn:
            p=self.lead(conn,'Old Co','Plumbers','Manly',touches=1)
            s=lead_engine.settings(conn,1)
            _,offline=lead_engine.draft(p,s,'followup1')
            _,online=lead_engine.draft(p,s,'followup1',preview='https://benji.example/p/abc/')
            with patch('pitch.preview_url',return_value='https://benji.example/p/abc/'):
                self.assertEqual(campaign.extras(conn,1,p,'followup1')['preview'],'https://benji.example/p/abc/')
                self.assertEqual(campaign.extras(conn,1,p,'first')['preview'],'')
        self.assertNotIn('http',offline.split('\n\nCheers,')[0]);self.assertIn('still stands',offline)
        self.assertIn('have a look: https://benji.example/p/abc/',online)

    def test_videos_today_and_results(self):
        with self.conn() as conn:
            for i in range(5):self.lead(conn,'Due '+str(i),'Plumbers','Manly',50+i,stage='Contacted',touches=1,next_on='2026-10-24',variant='Website for {name}?')
            self.lead(conn,'Later','Plumbers','Manly',99,stage='Contacted',touches=1,next_on='2026-11-30')
            self.lead(conn,'Keen','Electricians','Manly',70,stage='Interested',touches=1,replied_at='2026-10-22')
            videos=campaign.videos_today(conn,1,on=date(2026,10,23))
            self.assertEqual([p['name'] for p in videos],['Due 4','Due 3','Due 2'])
            r=campaign.results(conn,1)
        self.assertEqual(r['total'],7);self.assertFalse(r['ready'])
        self.assertEqual({t['name']:t['rate'] for t in r['trades']},{'Plumbers':0.0,'Electricians':100.0})
        self.assertEqual(r['subjects'][0]['name'],'Website for (business)?')

    def test_ceo_live_shows_the_plan(self):
        with self.conn() as conn:
            self.mark(conn,self.lead(conn,'Manly Pipes','Plumbers','Manly'))
        page=self.client.get('/ceo').data.decode()
        self.assertIn("This week's plan",page);self.assertIn('Now emailing: Plumbers in Manly',page);self.assertIn("What's working",page)


if __name__=='__main__':
    unittest.main()

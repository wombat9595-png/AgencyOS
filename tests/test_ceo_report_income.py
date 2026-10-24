"""CEO report card, Money in, and the daily warm-up. Local records only; nothing is sent."""
from datetime import date
import unittest
import ceo_report
import income
import team
import test_autosend


class ReportAndIncomeTest(unittest.TestCase):
    for _name in ('setUp','tearDown','setUp_base','tearDown_base','post','rows','conn','connect_gmail','add'):
        locals()[_name]=getattr(test_autosend.AutoSendTest,_name)

    def log(self,conn,pid,day,action):
        conn.execute("INSERT INTO prospect_log(owner_id,prospect_id,on_date,action,detail,created_at) VALUES(1,?,?,?,'','x')",(pid,day,action))

    def test_report_counts_the_last_14_days_and_gives_a_verdict(self):
        with self.conn() as conn:
            ids=[self.add(conn,'Fictional Co '+str(i),'hi'+str(i)+'@co'+str(i)+'.example') for i in range(30)]
            for i,pid in enumerate(ids):self.log(conn,pid,'2026-10-2'+str(i%4),'auto_sent')
            self.log(conn,ids[0],'2026-10-22','replied');self.log(conn,ids[1],'2026-10-22','bounced');self.log(conn,ids[2],'2026-10-23','opted_out')
            self.log(conn,ids[3],'2026-10-01','auto_sent')  # outside the 14 days
            conn.execute("UPDATE prospects SET ceo_status='held',ceo_note='Held back: no business name; too long' WHERE id=?",(ids[4],))
            conn.execute("UPDATE prospects SET website='https://a.example',checked_at='2026-10-20' WHERE id=?",(ids[5],))
            conn.execute("UPDATE prospects SET website='https://b.example' WHERE id=?",(ids[6],));conn.commit()
            r=ceo_report.report(conn,1,date(2026,10,24))
        t=r['totals']
        self.assertEqual((t['sent'],t['ceo'],t['replied'],t['bounced'],t['opted_out']),(30,30,1,1,1))
        self.assertEqual(len(r['daily']),14);self.assertEqual(r['daily'][-1]['day'],'2026-10-24')
        self.assertEqual(dict(r['held']),{'no business name':1,'too long':1})
        self.assertEqual((r['leads']['checked'],r['leads']['unchecked']),(1,1))
        self.assertEqual(r['verdict'][0],'watch')  # 3.3% bounces is over the 3% line
        self.assertIn('Sent 30 emails in 14 days',r['verdict'][1])
        page=self.client.get('/ceo/report').get_data(as_text=True)
        self.assertIn('How your CEO is doing',page);self.assertIn('Leads checked',page)

    def test_report_says_plainly_when_nothing_was_sent(self):
        with self.conn() as conn:
            level,text=ceo_report.report(conn,1,date(2026,10,24))['verdict']
        self.assertEqual(level,'bad');self.assertIn('no emails went out',text)

    def test_money_in_is_zero_until_a_payment_is_recorded_and_counts_each_payment_once(self):
        with self.conn() as conn:
            s=income.summary(conn,1,date(2026,10,24))
            self.assertEqual((s['last']['label'],s['last']['cents'],s['any']),('September 2026',0,False))
            conn.execute("INSERT INTO bills(owner_id,number,client_name,kind,description,amount_cents,total_cents,issued_on,due_on,status,paid_on,paid_reference,created_at) VALUES(1,'INV-1','Fictional Builds','deposit','Deposit',40000,40000,'2026-09-01','2026-09-08','Paid','2026-09-05','REF1','x')")
            conn.execute("INSERT INTO bills(owner_id,number,client_name,kind,description,amount_cents,total_cents,issued_on,due_on,status,created_at) VALUES(1,'INV-2','Fictional Builds','balance','Balance',40000,40000,'2026-09-20','2026-09-27','Ready','x')")
            cid=conn.execute("INSERT INTO plan_clients(owner_id,client_name,plan,billing,started_on,next_due_on,created_at) VALUES(1,'Fictional Builds','Care','monthly','2026-09-01','2026-11-01','x')").lastrowid
            conn.execute("INSERT INTO plan_payments(owner_id,client_id,amount_cents,bank_reference,received_on,recorded_at) VALUES(1,?,6900,'REF2','2026-10-02','x')",(cid,))
            conn.execute("INSERT INTO plan_payments(owner_id,client_id,amount_cents,bank_reference,received_on,recorded_at) VALUES(1,?,40000,'REF1','2026-09-05','x')",(cid,))  # same money as INV-1
            conn.commit()
            s=income.summary(conn,1,date(2026,10,24))
        self.assertEqual((s['last']['cents'],s['this']['cents'],s['year']),(40000,6900,46900))
        page=self.client.get('/income').get_data(as_text=True)
        self.assertIn('Money in',page);self.assertIn('A$',page)

    def test_old_default_limit_moves_up_to_50_once(self):
        with self.conn() as conn:
            conn.execute('ALTER TABLE team_settings DROP COLUMN daily_ramp')
            conn.execute('INSERT OR REPLACE INTO team_settings(owner_id,daily_drafts) VALUES(1,25)');conn.commit()
            team.migrate(conn)
            self.assertEqual(team.settings(conn,1)['daily_drafts'],50)
            conn.execute('UPDATE team_settings SET daily_drafts=25');team.migrate(conn)
            self.assertEqual(team.settings(conn,1)['daily_drafts'],25)  # Benji's own choice later stays


if __name__=='__main__':
    unittest.main()

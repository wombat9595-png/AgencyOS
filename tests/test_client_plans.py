"""Care and Autopilot monthly plans with fictional clients; no payment, email or network."""
from datetime import date
import unittest
from unittest.mock import patch
import client_plans
import test_agencyos as fixtures

TODAY=date(2026,10,17)


class ClientPlansTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post
    rows=fixtures.AgencyOSTest.rows

    def add(self,name='Fictional Plumbing Co',plan='Care',billing='monthly',started='2026-10-01'):
        with patch('client_plans.today',return_value=TODAY):
            return self.post('/clients/add',dict(client_name=name,contact_email='owner@example.com',plan=plan,billing=billing,started_on=started))

    def request(self,text='Swap the hero photo',size='small',client_id=1,on=TODAY):
        with patch('client_plans.today',return_value=on),patch('client_plans.stamp',return_value=on.isoformat()+'T00:00:00+00:00'):
            return self.post('/clients/requests',dict(client_id=client_id,source='email',request=text,size=size))

    def test_add_pay_and_count_real_money(self):
        self.assertEqual(self.add().status_code,302)
        with patch('client_plans.today',return_value=TODAY):
            page=self.client.get('/clients').data.decode()
        self.assertIn('Fictional Plumbing Co',page);self.assertIn('A$69',page);self.assertIn('Overdue',page)
        refused=self.post('/clients/1/payment',dict(amount='69.00',bank_reference='REF-1'))
        self.assertEqual(refused.status_code,400);self.assertEqual(len(self.rows('plan_payments')),0)
        with patch('client_plans.today',return_value=TODAY):
            self.post('/clients/1/payment',dict(amount='69.00',bank_reference='REF-1',confirm='yes'))
            self.assertEqual(self.post('/clients/1/payment',dict(amount='69.00',bank_reference='REF-1',confirm='yes')).status_code,400)
        self.assertEqual([r['amount_cents'] for r in self.rows('plan_payments')],[6900])
        self.assertEqual(self.rows('plan_clients')[0]['next_due_on'],'2026-11-01')
        home=self.client.get('/business?ask=How much money have we made?').data.decode()
        self.assertIn('A$69.00',home)

    def test_yearly_billing_spreads_value_and_advances_a_year(self):
        self.add(plan='Autopilot',billing='yearly',started='2026-01-31')
        with patch('client_plans.today',return_value=TODAY):
            self.post('/clients/1/payment',dict(amount='1490',bank_reference='YEAR-1',confirm='yes'))
        self.assertEqual(self.rows('plan_clients')[0]['next_due_on'],'2027-01-31')
        with patch('client_plans.today',return_value=TODAY):
            from contextlib import closing
            import sqlite3,app as application
            with closing(sqlite3.connect(application.DB_PATH)) as conn:
                conn.row_factory=sqlite3.Row
                self.assertEqual(client_plans.summary(conn,1)['monthly_cents'],12417)

    def test_month_end_dates_clamp(self):
        self.assertEqual(client_plans.add_months(date(2026,1,31),1),date(2026,2,28))
        self.assertEqual(client_plans.add_months(date(2026,12,15),1),date(2027,1,15))

    def test_care_allowance_drafts_the_right_reply(self):
        self.add()
        for n in range(5):self.request('Small change '+str(n))
        self.request('One more small change');self.request('New bookings page',size='quote')
        replies=[r['reply'] for r in self.rows('plan_requests')]
        self.assertIn('change 1 of 5',replies[0]);self.assertIn('change 5 of 5',replies[4])
        self.assertIn('used the 5 small changes',replies[5]);self.assertIn('quick quote',replies[6])
        self.assertTrue(all(r.startswith('Hi Fictional,') for r in replies))
        self.assertIn(b'change requests from monthly clients',self.client.get('/business').data)

    def test_autopilot_is_unlimited_and_approval_never_sends(self):
        self.add(plan='Autopilot')
        for n in range(7):self.request('Change '+str(n))
        self.assertNotIn('used the',self.rows('plan_requests')[-1]['reply'])
        with patch('smtplib.SMTP',side_effect=AssertionError('No email')):
            self.post('/clients/requests/1/approve',dict(reply='Edited reply'))
            self.post('/clients/requests/1/done')
        row=self.rows('plan_requests')[0];self.assertEqual((row['status'],row['reply']),('Done','Edited reply'))

    def test_notice_ends_plan_after_30_days(self):
        self.add()
        with patch('client_plans.today',return_value=TODAY):
            self.assertEqual(self.post('/clients/1/cancel',dict()).status_code,400)
            self.post('/clients/1/cancel',dict(confirm='yes'))
        self.assertEqual(self.rows('plan_clients')[0]['ends_on'],'2026-11-16')
        self.assertEqual(self.request(on=date(2026,11,17)).status_code,400)
        with patch('client_plans.today',return_value=date(2026,11,17)):
            self.assertIn(b'Ended',self.client.get('/clients').data)

    def test_other_owner_clients_are_hidden(self):
        self.add()
        with patch('client_plans.today',return_value=TODAY):
            self.assertEqual(self.post('/clients/999/payment',dict(amount='69',bank_reference='X',confirm='yes')).status_code,400)
        self.assertEqual(self.request(client_id=999).status_code,400)

    def test_packages_are_care_and_autopilot_with_no_lock_in(self):
        self.post('/business/configure',{'confirm':'yes'})
        packages={p['name']:dict(p) for p in self.rows('p5_packages')}
        self.assertEqual({k:(v['price_cents'],v['cycle']) for k,v in packages.items()},
          {'Care Plan':(6900,'monthly'),'Care Website':(80000,'one-off'),'Autopilot Website':(140000,'one-off'),'Autopilot Plan':(14900,'monthly')})
        self.assertIn("No lock-in",packages['Care Plan']['scope']);self.assertIn("30 days' notice",packages['Autopilot Plan']['scope'])


if __name__=='__main__':
    unittest.main()

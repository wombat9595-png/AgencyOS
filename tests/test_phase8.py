"""Phase 8 orchestration and wall-clock scheduling use local synthetic records."""
import json
import os
import sqlite3
import subprocess
import sys
import threading
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import app as application
import p8_ops
import test_agent_center as fixtures


class OperationsTest(unittest.TestCase):
    post=fixtures.AgentCenterTest.post
    rows=fixtures.AgentCenterTest.rows
    create=fixtures.AgentCenterTest.create

    def setUp(self):
        fixtures.AgentCenterTest.setUp(self)

    def tearDown(self):
        fixtures.AgentCenterTest.tearDown(self)

    def sql(self,query,args=()):
        with closing(sqlite3.connect(application.DB_PATH)) as conn, conn:
            return conn.execute(query,args)

    def test_operations_dashboard_shows_all_phase_queues_worker_and_costs(self):
        response=self.client.get('/operations')
        self.assertEqual(response.status_code,200)
        for text in (b'Phase 3',b'Phase 4',b'Phase 5',b'Phase 8',b'P5 AI RESERVED TODAY',b'Work enabled'):
            self.assertIn(text,response.data)

    def test_wall_clock_schedule_validates_timezone_and_weekdays(self):
        bad=self.post('/operations/schedules',{'lead_id':'1','local_time':'09:15','timezone':'Mars/Olympus','weekdays':['0']})
        self.assertEqual(bad.status_code,302)
        self.assertEqual(len(self.rows('p8_schedules')),0)
        empty=self.post('/operations/schedules',{'lead_id':'1','local_time':'09:15','timezone':'Australia/Sydney'})
        self.assertEqual(empty.status_code,302)
        self.assertEqual(len(self.rows('p8_schedules')),0)
        response=self.post('/operations/schedules',{'lead_id':'1','local_time':'09:15','timezone':'Australia/Sydney','weekdays':['0','2','4']})
        self.assertEqual(response.status_code,302)
        schedule=self.rows('p8_schedules')[0]
        self.assertEqual(schedule['timezone'],'Australia/Sydney')
        self.assertEqual(json.loads(schedule['weekdays_json']),[0,2,4])
        self.assertGreater(schedule['next_run_utc'],0)
        with closing(__import__('phase3_store').connect(application.DB_PATH)) as conn:
            p8_ops.migrate(conn)
        self.assertEqual(len(self.rows('p8_schedules')),1)

    def test_due_schedule_enqueues_once_and_worker_completes_reviewable_local_task(self):
        self.post('/operations/schedules',{'lead_id':'1','local_time':'09:15','timezone':'Australia/Sydney','weekdays':['0','1','2','3','4','5','6']})
        now=datetime.now(timezone.utc).timestamp()
        self.sql('UPDATE p8_schedules SET next_run_utc=?',(now-60,))
        with closing(__import__('phase3_store').connect(application.DB_PATH)) as conn:
            self.assertEqual(p8_ops.create_scheduled_tasks(conn,now_epoch=now),1)
        self.assertEqual(self.rows('p8_schedule_runs')[0]['task_id'],self.rows('agent_tasks')[-1]['id'])
        task=self.rows('agent_tasks')[-1]
        self.assertEqual(task['mode'],'local')
        self.assertEqual(task['status'],'Queued')
        self.assertTrue(p8_ops.worker_once(application.DB_PATH))
        self.assertEqual(self.rows('agent_tasks')[-1]['status'],'Awaiting review')
        self.assertIn('No website was fetched',self.rows('agent_tasks')[-1]['result'])
        self.assertFalse(p8_ops.worker_once(application.DB_PATH))
        self.assertEqual(len(self.rows('p8_schedule_runs')),1)

    def test_schedule_queue_pressure_skips_occurrence_instead_of_flooding(self):
        self.post('/operations/schedules',{'lead_id':'1','local_time':'09:15','timezone':'Australia/Sydney','weekdays':['0','1','2','3','4','5','6']})
        now=datetime.now(timezone.utc).timestamp()
        self.sql('UPDATE p8_schedules SET next_run_utc=?',(now-60,))
        snapshot=json.dumps({'business_name':'Synthetic Bakery','website':'https://example.com','industry':'Bakery','location':'Sydney'})
        for i in range(50):
            self.sql("INSERT INTO agent_tasks(user_id,agent_id,lead_id,title,instructions,mode,status,snapshot_json,created_at,updated_at) VALUES(1,'lead-research',1,?,'','local','Queued',?,?,?)",(f'Pending {i}',snapshot,datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat()))
        with closing(__import__('phase3_store').connect(application.DB_PATH)) as conn:
            self.assertEqual(p8_ops.create_scheduled_tasks(conn,now_epoch=now),0)
        self.assertEqual(len(self.rows('p8_schedule_runs')),0)
        self.assertEqual(len(self.rows('agent_tasks')),50)
        self.assertEqual(self.rows('p8_schedule_events')[0]['kind'],'queue_pressure')
        self.assertGreater(self.rows('p8_schedules')[0]['next_run_utc'],now)

    def test_pause_blocks_schedules_and_worker_leaves_ai_task_for_approved_manual_path(self):
        self.create(mode='local')
        self.sql('UPDATE p4_control SET paused=1')
        self.assertFalse(p8_ops.worker_once(application.DB_PATH))
        self.assertEqual(self.rows('agent_tasks')[-1]['status'],'Queued')
        self.sql('UPDATE p4_control SET paused=0')
        self.assertTrue(p8_ops.worker_once(application.DB_PATH))
        with patch.dict(os.environ,fixtures.CONFIG):
            response=self.create(mode='ai')
            self.post(response.location+'/approve-ai',{'confirm_ai':'yes'})
        self.assertFalse(p8_ops.worker_once(application.DB_PATH))
        self.assertEqual(self.rows('agent_tasks')[-1]['status'],'Queued')

    def test_concurrent_phase8_workers_claim_a_local_task_only_once(self):
        self.create(mode='local')
        results=[]
        barrier=threading.Barrier(2)
        def run():
            barrier.wait()
            results.append(p8_ops.worker_once(application.DB_PATH))
        workers=[threading.Thread(target=run) for _ in range(2)]
        [worker.start() for worker in workers]
        [worker.join(10) for worker in workers]
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(self.rows('agent_tasks')[0]['status'],'Awaiting review')

    def test_phase8_cli_worker_uses_selected_database_and_stops_heartbeat(self):
        self.create(mode='local')
        env=dict(os.environ,AGENCYOS_DB=application.DB_PATH,AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0')
        result=subprocess.run([sys.executable,'manage.py','worker','--phase8'],cwd=application.APP_DIR,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Processed one task',result.stdout)
        self.assertEqual(self.rows('agent_tasks')[0]['status'],'Awaiting review')
        with closing(__import__('phase3_store').connect(application.DB_PATH)) as conn:
            self.assertFalse(__import__('runtime_status').status(conn,application.DB_PATH,'8')['selected_worker_connected'])

    def test_local_daily_summary_is_durable_unique_and_owner_scoped(self):
        now=datetime(2026,10,16,10,0,tzinfo=timezone.utc).timestamp()
        self.sql("INSERT INTO p8_summary_settings(user_id,timezone,local_time,enabled) VALUES(1,'Australia/Sydney','18:00',1)")
        with closing(__import__('phase3_store').connect(application.DB_PATH)) as conn:
            self.assertEqual(p8_ops.create_due_summaries(conn,now_epoch=now),1)
            self.assertEqual(p8_ops.create_due_summaries(conn,now_epoch=now),0)
        summary=self.rows('p8_daily_summaries')[0]
        data=json.loads(summary['summary_json'])
        self.assertEqual(summary['local_date'],'2026-10-16')
        self.assertIn('p5_jobs',data['queues'])
        self.assertIn('phase5_ai_reserved_cents',data['usage'])
        with self.client.session_transaction() as session: session['user_id']=999
        self.assertEqual(self.client.get(f"/operations/summaries/{summary['id']}").status_code,404)

    def test_dst_gap_wall_time_is_skipped_to_next_real_occurrence(self):
        before=datetime(2026,10,3,15,0,tzinfo=timezone.utc).timestamp()
        next_run=p8_ops.next_wall_time('02:30','Australia/Sydney',[6],after=before)
        local=datetime.fromtimestamp(next_run,timezone.utc).astimezone(p8_ops._zone('Australia/Sydney'))
        self.assertEqual(local.date().isoformat(),'2026-10-11')
        self.assertEqual(local.strftime('%H:%M'),'02:30')


if __name__=='__main__':
    unittest.main()

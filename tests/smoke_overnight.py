"""Accelerated fictional night: real concurrent workers, restart, recovery and pause."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as application
import test_agencyos as fixtures
from phase3_store import connect,stamp
import production_ops

parser=argparse.ArgumentParser();parser.add_argument('--artifacts',required=True);args=parser.parse_args()
out=Path(args.artifacts).resolve();out.mkdir(parents=True,exist_ok=True)
fixture=fixtures.AgencyOSTest();fixture.setUp()
processes=[];logs=[];result={'passed':False,'synthetic':True,'simulation':'Accelerated workload; not a long-duration reliability certification'}
try:
    fixture.post('/leads',dict(business_name='Fictional Night Studio',website='https://night.example/',location='Canberra ACT'))
    env=dict(os.environ,AGENCYOS_DB=application.DB_PATH,AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0',AGENCYOS_OSM_POLICY_FILE='')
    def sql(query,args=()):
        with closing(connect(application.DB_PATH)) as conn,conn:return conn.execute(query,args).fetchall()
    snapshot=json.dumps(dict(business_name='Fictional Night Studio',website='https://night.example/',industry='Design',location='Canberra ACT'))
    for i in range(20):
        sql("INSERT INTO agent_tasks(user_id,agent_id,lead_id,title,instructions,mode,status,snapshot_json,created_at,updated_at) VALUES(1,'lead-research',1,?,'Review saved fixture','local','Queued',?,?,?)",(f'Night fixture {i}',snapshot,stamp(),stamp()))
    sql("UPDATE agent_tasks SET status='Running',started_at=0,run_token='dead-process' WHERE id=1")
    sql("INSERT INTO agent_tasks(user_id,agent_id,lead_id,title,instructions,mode,status,snapshot_json,created_at,updated_at) VALUES(1,'lead-research',1,'Paid request must remain untouched','','ai','Awaiting AI approval',?,?,?)",(snapshot,stamp(),stamp()))
    sql("INSERT INTO p8_schedules(user_id,lead_id,local_time,timezone,weekdays_json,next_run_utc,created_at) VALUES(1,1,'09:00','Australia/Sydney','[0,1,2,3,4,5,6]',0,?)",(stamp(),))
    sql("INSERT INTO p8_summary_settings VALUES(1,'UTC','00:00',1)")
    def start(label,watch=False):
        log=(out/(label+'.log')).open('w');logs.append(log)
        proc=subprocess.Popen([sys.executable,'manage.py','worker','--phase8']+(['--watch'] if watch else []),env=env,stdout=log,stderr=log,cwd=Path(application.APP_DIR));processes.append(proc);return proc
    fixture.post('/agency/pause',dict(paused='1'))
    proc=start('paused');assert proc.wait(timeout=15)==0
    assert not sql("SELECT id FROM agent_tasks WHERE status='Awaiting review'")
    fixture.post('/agency/pause',dict(paused='0'))
    first=start('worker-a',True);second=start('worker-b',True)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        completed=sql("SELECT COUNT(*) FROM agent_tasks WHERE status='Awaiting review'")[0][0]
        if completed==21:break
        assert first.poll() is None and second.poll() is None
        time.sleep(.1)
    else:raise AssertionError('Concurrent worker drain timeout')
    for proc in (first,second):proc.terminate();assert proc.wait(timeout=10)==0
    restarted=start('restarted');assert restarted.wait(timeout=15)==0
    assert sql('SELECT recovery_count FROM agent_tasks WHERE id=1')[0][0]==1
    assert sql('SELECT COUNT(*) FROM p8_schedule_runs')[0][0]==1
    assert sql('SELECT COUNT(*) FROM p8_daily_summaries')[0][0]==1
    assert sql("SELECT COUNT(*) FROM agent_tasks WHERE mode='ai' AND status='Awaiting AI approval'")[0][0]==1
    assert sql('SELECT COUNT(*) FROM p5_ai_usage')[0][0]==0
    assert sql("SELECT COUNT(*) FROM runtime_workers WHERE state='running'")[0][0]==0
    production_ops.collect_alerts(application.DB_PATH)
    assert sql("SELECT COUNT(*) FROM ops_alerts WHERE category='backup' AND resolved_at IS NULL")[0][0]==1
    result.update(passed=True,local_tasks_completed=21,expired_local_task_recoveries=1,scheduled_occurrences=1,daily_summaries=1,paid_tasks_executed=0,real_emails=0,publications=0,process_restart_verified=True,pause_verified=True)
    print(json.dumps(result,indent=2))
finally:
    for proc in processes:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
    for log in logs:log.close()
    (out/'overnight-results.json').write_text(json.dumps(result,indent=2))
    fixture.tearDown()

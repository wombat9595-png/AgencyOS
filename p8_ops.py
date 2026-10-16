"""Phase 8 local orchestration, wall-clock schedules, and operations summaries."""
import json
import time
from contextlib import closing
from datetime import date, datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import abort, flash, redirect, render_template, request, session, url_for

from phase3_store import connect
from phase4_store import paused


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p8_schedules (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
      local_time TEXT NOT NULL, timezone TEXT NOT NULL, weekdays_json TEXT NOT NULL,
      next_run_utc REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
      last_run_utc REAL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p8_schedule_runs (
      id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL REFERENCES p8_schedules(id),
      scheduled_for_utc REAL NOT NULL, task_id INTEGER NOT NULL REFERENCES agent_tasks(id),
      created_at TEXT NOT NULL, UNIQUE(schedule_id,scheduled_for_utc));
    CREATE TABLE IF NOT EXISTS p8_schedule_events (
      id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL REFERENCES p8_schedules(id),
      kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p8_summary_settings (
      user_id INTEGER PRIMARY KEY REFERENCES users(id), timezone TEXT NOT NULL DEFAULT 'UTC',
      local_time TEXT NOT NULL DEFAULT '18:00', enabled INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS p8_daily_summaries (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), local_date TEXT NOT NULL,
      timezone TEXT NOT NULL, summary_json TEXT NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(user_id,local_date));
    CREATE INDEX IF NOT EXISTS p8_schedule_due_idx ON p8_schedules(enabled,next_run_utc);
    ''')


def _valid_time(value):
    try:
        parsed=dt_time.fromisoformat(value)
        return parsed.strftime('%H:%M')
    except (ValueError,TypeError):
        raise ValueError('Choose a local time in HH:MM format.') from None


def _zone(value):
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError,TypeError):
        raise ValueError('Enter a valid IANA time zone, for example Australia/Sydney.') from None


def next_wall_time(local_time, timezone_name, weekdays, after=None):
    """Find the next real local occurrence; skip nonexistent DST wall times."""
    wall=dt_time.fromisoformat(local_time)
    zone=_zone(timezone_name)
    now=datetime.fromtimestamp(after or time.time(),timezone.utc)
    local_now=now.astimezone(zone)
    selected=set(weekdays)
    for offset in range(0,15):
        day=local_now.date()+timedelta(days=offset)
        if day.weekday() not in selected:
            continue
        naive=datetime.combine(day,wall)
        candidate=naive.replace(tzinfo=zone,fold=0)
        # A DST gap round trip changes the requested wall time: skip that date.
        utc=candidate.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None)!=naive:
            continue
        if utc.timestamp()>now.timestamp():
            return utc.timestamp()
    raise ValueError('Could not calculate the next schedule occurrence.')


def _snapshot(conn, lead_id):
    lead=conn.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
    if not lead:
        return None
    return {field:lead[field] for field in ('business_name','website','industry','location')}


def create_scheduled_tasks(conn, now_epoch=None):
    """Enqueue due, owner-authorized local-only tasks once per occurrence."""
    current=now_epoch or time.time()
    if paused(conn):
        return 0
    conn.execute('BEGIN IMMEDIATE')
    schedules=conn.execute('SELECT * FROM p8_schedules WHERE enabled=1 AND next_run_utc<=? ORDER BY next_run_utc,id',(current,)).fetchall()
    created=0
    for schedule in schedules:
        snapshot=_snapshot(conn,schedule['lead_id'])
        agent=conn.execute("SELECT enabled,availability FROM agents WHERE id='lead-research'").fetchone()
        if not snapshot or not agent or not agent['enabled'] or agent['availability']!='available':
            conn.execute('UPDATE p8_schedules SET enabled=0 WHERE id=?',(schedule['id'],))
            conn.execute('INSERT INTO p8_schedule_events(schedule_id,kind,message,created_at) VALUES(?,?,?,?)',
                         (schedule['id'],'disabled_agent','Schedule stopped because the local lead-research agent or saved lead is unavailable.',datetime.fromtimestamp(current,timezone.utc).isoformat()))
            continue
        scheduled=schedule['next_run_utc']
        pending=conn.execute("SELECT COUNT(*) FROM agent_tasks WHERE user_id=? AND status IN ('Queued','Running','Awaiting AI approval')",(schedule['user_id'],)).fetchone()[0]
        if pending>=50:
            days=json.loads(schedule['weekdays_json'])
            next_run=next_wall_time(schedule['local_time'],schedule['timezone'],days,after=current)
            conn.execute('UPDATE p8_schedules SET next_run_utc=?,last_run_utc=? WHERE id=?',(next_run,current,schedule['id']))
            conn.execute('INSERT INTO p8_schedule_events(schedule_id,kind,message,created_at) VALUES(?,?,?,?)',
                         (schedule['id'],'queue_pressure','Occurrence skipped at the 50-task owner queue ceiling; schedule advanced to its next local occurrence.',datetime.fromtimestamp(current,timezone.utc).isoformat()))
            continue
        cur=conn.execute('''INSERT INTO agent_tasks(user_id,agent_id,lead_id,title,instructions,mode,status,snapshot_json,created_at,updated_at)
            VALUES(?, 'lead-research', ?, ?, ?, 'local', 'Queued', ?, ?, ?)''',
            (schedule['user_id'],schedule['lead_id'],'Scheduled lead review: '+snapshot['business_name'],
             'Owner-authorized recurring local review. Use only this saved lead snapshot.',json.dumps(snapshot,sort_keys=True),
             datetime.fromtimestamp(current,timezone.utc).isoformat(),datetime.fromtimestamp(current,timezone.utc).isoformat()))
        conn.execute('INSERT INTO agent_events(task_id,message,created_at) VALUES(?,?,?)',
                     (cur.lastrowid,'Created by local-time schedule #'+str(schedule['id'])+'; no external calls or actions.',datetime.fromtimestamp(current,timezone.utc).isoformat()))
        conn.execute('INSERT OR IGNORE INTO p8_schedule_runs(schedule_id,scheduled_for_utc,task_id,created_at) VALUES(?,?,?,?)',
                     (schedule['id'],scheduled,cur.lastrowid,datetime.fromtimestamp(current,timezone.utc).isoformat()))
        zone=_zone(schedule['timezone'])
        local_scheduled=datetime.fromtimestamp(scheduled,timezone.utc).astimezone(zone)
        days=json.loads(schedule['weekdays_json'])
        next_run=next_wall_time(schedule['local_time'],schedule['timezone'],days,after=current)
        conn.execute('UPDATE p8_schedules SET next_run_utc=?,last_run_utc=? WHERE id=?',(next_run,current,schedule['id']))
        created+=1
    conn.commit()
    return created


def worker_once(path):
    """Run one queued local lead-research task. AI tasks remain owner initiated."""
    from agent_center import local_analysis
    with closing(connect(path)) as conn, conn:
        if paused(conn):
            return False
        create_scheduled_tasks(conn)
        conn.execute('BEGIN IMMEDIATE')
        task=conn.execute('''SELECT t.* FROM agent_tasks t JOIN agents a ON a.id=t.agent_id
            WHERE t.status='Queued' AND t.mode='local' AND t.agent_id='lead-research' AND a.enabled=1
            ORDER BY t.id LIMIT 1''').fetchone()
        if not task:
            conn.commit()
            return False
        changed=conn.execute("UPDATE agent_tasks SET status='Running',progress=10,started_at=?,updated_at=? WHERE id=? AND status='Queued'",
                             (time.time(),datetime.now(timezone.utc).isoformat(),task['id'])).rowcount
        if not changed:
            conn.rollback();return False
        conn.execute('INSERT INTO agent_events(task_id,message,created_at) VALUES(?,?,?)',
                     (task['id'],'Phase 8 worker claimed the local task; zero-cost saved-record handler only.',datetime.now(timezone.utc).isoformat()))
        conn.commit()
        try:
            result=local_analysis(json.loads(task['snapshot_json']),task['instructions'])
            if not isinstance(result,str) or not result.strip() or len(result)>12000:
                raise ValueError('Invalid local result.')
        except Exception:
            conn.execute("UPDATE agent_tasks SET status='Failed',error=?,updated_at=? WHERE id=? AND status='Running'",
                         ('Local task failed. Review configuration and create an explicit replacement.',datetime.now(timezone.utc).isoformat(),task['id']))
            message='Local handler failed; no automatic retry was performed.'
        else:
            conn.execute("UPDATE agent_tasks SET status='Awaiting review',progress=100,result=?,updated_at=? WHERE id=? AND status='Running'",
                         (result,datetime.now(timezone.utc).isoformat(),task['id']))
            message='Local task completed. Owner review is required; no actions were executed.'
        conn.execute('INSERT INTO agent_events(task_id,message,created_at) VALUES(?,?,?)',
                     (task['id'],message,datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return True


def _daily_data(conn, user_id, local_date, timezone_name):
    start=datetime.combine(date.fromisoformat(local_date),dt_time.min,tzinfo=_zone(timezone_name)).astimezone(timezone.utc).isoformat()
    end=datetime.combine(date.fromisoformat(local_date)+timedelta(days=1),dt_time.min,tzinfo=_zone(timezone_name)).astimezone(timezone.utc).isoformat()
    utc_first=datetime.fromisoformat(start).date().isoformat()
    utc_last=(datetime.fromisoformat(end)-timedelta(microseconds=1)).date().isoformat()
    tasks={row['status']:row['n'] for row in conn.execute('SELECT status,COUNT(*) n FROM agent_tasks WHERE user_id=? AND created_at>=? AND created_at<? GROUP BY status',(user_id,start,end))}
    queues={}
    for table,owner_field in (('p3_jobs','user_id'),('p4_jobs','user_id'),('p5_jobs','p5')):
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
        if not exists:
            queues[table]={};continue
        if owner_field=='p5':
            query='SELECT j.status,COUNT(*) n FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND j.created_at>=? AND j.created_at<? GROUP BY j.status'
            params=(user_id,start,end)
        else:
            query='SELECT status,COUNT(*) n FROM '+table+' WHERE user_id=? AND created_at>=? AND created_at<? GROUP BY status'
            params=(user_id,start,end)
        queues[table]={row['status']:row['n'] for row in conn.execute(query,params)}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='p7_invoices'").fetchone():
        queues['p7_invoices']={row['status']:row['n'] for row in conn.execute(
            'SELECT status,COUNT(*) n FROM p7_invoices WHERE user_id=? AND created_at>=? AND created_at<? GROUP BY status',(user_id,start,end))}
        queues['p7_payments']={row['source']+': '+row['status']:row['n'] for row in conn.execute(
            '''SELECT p.source,p.status,COUNT(*) n FROM p7_payments p JOIN p7_invoices i ON i.id=p.invoice_id
               WHERE i.user_id=? AND p.created_at>=? AND p.created_at<? GROUP BY p.source,p.status''',(user_id,start,end))}
    else:
        queues['p7_invoices']={};queues['p7_payments']={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='p10_releases'").fetchone():
        queues['p10_releases']={row['status']:row['n'] for row in conn.execute(
            'SELECT status,COUNT(*) n FROM p10_releases WHERE owner_id=? AND created_at>=? AND created_at<? GROUP BY status',(user_id,start,end))}
    else:
        queues['p10_releases']={}
    p3_calls=conn.execute('SELECT COALESCE(SUM(calls),0) FROM p3_usage WHERE day BETWEEN ? AND ?',(utc_first,utc_last)).fetchone()[0]
    p4_reserved=conn.execute("SELECT COALESCE(SUM(b.reserved_cents),0) FROM p4_budget b JOIN p4_jobs j ON j.id=b.job_id WHERE j.user_id=? AND b.day BETWEEN ? AND ?",(user_id,utc_first,utc_last)).fetchone()[0]
    p5_reserved=conn.execute("SELECT COALESCE(SUM(u.reserved_cents),0) FROM p5_ai_usage u JOIN p5_jobs j ON j.id=u.job_id JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND u.day BETWEEN ? AND ?",(user_id,utc_first,utc_last)).fetchone()[0]
    return dict(local_date=local_date,timezone=timezone_name,tasks=tasks,queues=queues,
                usage=dict(phase3_provider_calls=p3_calls,phase4_ai_reserved_cents=p4_reserved,phase5_ai_reserved_cents=p5_reserved),
                note='Counts are workflow states, not sales, verified revenue, independent research or customer outcomes.')


def create_due_summaries(conn, now_epoch=None):
    current=datetime.fromtimestamp(now_epoch or time.time(),timezone.utc)
    created=0
    for setting in conn.execute('SELECT * FROM p8_summary_settings WHERE enabled=1').fetchall():
        zone=_zone(setting['timezone']); local_now=current.astimezone(zone)
        if local_now.strftime('%H:%M')<setting['local_time']:
            continue
        local_date=local_now.date().isoformat()
        data=_daily_data(conn,setting['user_id'],local_date,setting['timezone'])
        cursor=conn.execute('INSERT OR IGNORE INTO p8_daily_summaries(user_id,local_date,timezone,summary_json,created_at) VALUES(?,?,?,?,?)',
                            (setting['user_id'],local_date,setting['timezone'],json.dumps(data,sort_keys=True),current.isoformat()))
        created+=cursor.rowcount
    conn.commit()
    return created


def register(app, get_db, login_required, get_db_path):
    @app.route('/operations',methods=['GET'])
    @login_required
    def operations():
        conn=get_db(); user=session['user_id']
        from runtime_status import status as runtime_status_view
        runtime=runtime_status_view(conn,get_db_path(),'8')
        task_status={r['status']:r['n'] for r in conn.execute('SELECT status,COUNT(*) n FROM agent_tasks WHERE user_id=? GROUP BY status',(user,))}
        failures=[]
        queries={
          'p3_jobs':('SELECT id,status,error,updated_at FROM p3_jobs WHERE user_id=? AND status IN (\'Failed\',\'Interrupted\') ORDER BY id DESC LIMIT 10',(user,)),
          'p4_jobs':('SELECT id,status,error,updated_at FROM p4_jobs WHERE user_id=? AND status IN (\'Failed\',\'Interrupted\') ORDER BY id DESC LIMIT 10',(user,)),
          'p5_jobs':('SELECT j.id,j.status,j.error,j.updated_at FROM p5_jobs j JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND j.status IN (\'Failed\',\'Interrupted\') ORDER BY j.id DESC LIMIT 10',(user,)),
        }
        for table,(query,params) in queries.items():
            for row in conn.execute(query,params):
                failures.append(dict(queue=table,id=row['id'],status=row['status'],error=row['error'],updated_at=row['updated_at']))
        for row in conn.execute("SELECT id,status,error,updated_at FROM agent_tasks WHERE user_id=? AND status='Failed' ORDER BY id DESC LIMIT 10",(user,)):
            failures.append(dict(queue='agent_tasks',id=row['id'],status=row['status'],error=row['error'],updated_at=row['updated_at']))
        failures.sort(key=lambda item:item['updated_at'],reverse=True)
        usage=dict(p3_calls=0,p4_reserved=0,p4_actual=0,p5_reserved=0,p5_requests=0)
        usage['p3_calls']=conn.execute("SELECT COALESCE(SUM(calls),0) FROM p3_usage WHERE day=date('now')").fetchone()[0]
        usage['p4_reserved']=conn.execute("SELECT COALESCE(SUM(b.reserved_cents),0) FROM p4_budget b JOIN p4_jobs j ON j.id=b.job_id WHERE j.user_id=? AND b.day=date('now')",(user,)).fetchone()[0]
        usage['p4_actual']=conn.execute("SELECT COALESCE(SUM(b.actual_cents),0) FROM p4_budget b JOIN p4_jobs j ON j.id=b.job_id WHERE j.user_id=? AND b.day=date('now')",(user,)).fetchone()[0]
        usage['p5_reserved']=conn.execute("SELECT COALESCE(SUM(u.reserved_cents),0) FROM p5_ai_usage u JOIN p5_jobs j ON j.id=u.job_id JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND u.day=date('now')",(user,)).fetchone()[0]
        usage['p5_requests']=conn.execute("SELECT COUNT(*) FROM p5_ai_usage u JOIN p5_jobs j ON j.id=u.job_id JOIN p5_flows f ON f.id=j.flow_id WHERE f.user_id=? AND u.day=date('now')",(user,)).fetchone()[0]
        schedules=[]
        for item in conn.execute('''SELECT s.*,l.business_name FROM p8_schedules s JOIN leads l ON l.id=s.lead_id
            WHERE s.user_id=? ORDER BY s.id DESC''',(user,)).fetchall():
            row=dict(item);row['next_local']=datetime.fromtimestamp(row['next_run_utc'],timezone.utc).astimezone(_zone(row['timezone'])).strftime('%a %d %b %Y, %H:%M %Z')
            schedules.append(row)
        schedule_events=conn.execute('''SELECT e.*,s.lead_id,l.business_name FROM p8_schedule_events e
            JOIN p8_schedules s ON s.id=e.schedule_id JOIN leads l ON l.id=s.lead_id
            WHERE s.user_id=? ORDER BY e.id DESC LIMIT 20''',(user,)).fetchall()
        setting=conn.execute('SELECT * FROM p8_summary_settings WHERE user_id=?',(user,)).fetchone()
        summaries=conn.execute('SELECT * FROM p8_daily_summaries WHERE user_id=? ORDER BY local_date DESC LIMIT 14',(user,)).fetchall()
        return render_template('operations.html',runtime=runtime,task_status=task_status,failures=failures,
                               usage=usage,schedules=schedules,schedule_events=schedule_events,setting=setting,summaries=summaries,
                               leads=conn.execute('SELECT id,business_name FROM leads ORDER BY business_name').fetchall(),
                               paused=runtime['paused'])

    @app.route('/operations/schedules',methods=['POST'])
    @login_required
    def operations_schedule_create():
        conn=get_db(); lead_id=request.form.get('lead_id',type=int)
        local_time=request.form.get('local_time','')
        zone=request.form.get('timezone','').strip()
        days=sorted({int(day) for day in request.form.getlist('weekdays') if day.isdigit() and 0<=int(day)<=6})
        if not lead_id or not conn.execute('SELECT 1 FROM leads WHERE id=?',(lead_id,)).fetchone():
            flash('Choose a saved lead.','error')
        elif not days:
            flash('Select at least one local weekday.','error')
        else:
            try:
                local_time=_valid_time(local_time);_zone(zone)
                next_run=next_wall_time(local_time,zone,days)
            except ValueError as exc:
                flash(str(exc),'error')
            else:
                if conn.execute('SELECT COUNT(*) FROM p8_schedules WHERE user_id=? AND enabled=1',(session['user_id'],)).fetchone()[0]>=20:
                    flash('Limit reached: at most 20 active Phase 8 schedules per owner.','error')
                else:
                    conn.execute('INSERT INTO p8_schedules(user_id,lead_id,local_time,timezone,weekdays_json,next_run_utc,created_at) VALUES(?,?,?,?,?,?,?)',
                                 (session['user_id'],lead_id,local_time,zone,json.dumps(days),next_run,datetime.now(timezone.utc).isoformat()))
                    conn.commit();flash('Local recurring schedule saved. It only queues zero-cost saved-record review.','success')
        return redirect(url_for('operations'))

    @app.route('/operations/schedules/<int:schedule_id>/stop',methods=['POST'])
    @login_required
    def operations_schedule_stop(schedule_id):
        conn=get_db(); changed=conn.execute('UPDATE p8_schedules SET enabled=0 WHERE id=? AND user_id=?',(schedule_id,session['user_id'])).rowcount
        if not changed: abort(404)
        conn.commit();flash('Schedule stopped. Already queued tasks remain visible for review.','success')
        return redirect(url_for('operations'))

    @app.route('/operations/summary-settings',methods=['POST'])
    @login_required
    def operations_summary_settings():
        conn=get_db()
        try:
            local_time=_valid_time(request.form.get('local_time',''));zone=request.form.get('timezone','').strip();_zone(zone)
        except ValueError as exc:
            flash(str(exc),'error');return redirect(url_for('operations'))
        enabled=int(request.form.get('enabled')=='yes')
        conn.execute('''INSERT INTO p8_summary_settings(user_id,timezone,local_time,enabled) VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone,local_time=excluded.local_time,enabled=excluded.enabled''',
            (session['user_id'],zone,local_time,enabled))
        conn.commit();flash('Daily local operations summary schedule saved. No email will be sent.','success')
        return redirect(url_for('operations'))

    @app.route('/operations/summaries/<int:summary_id>')
    @login_required
    def operations_summary(summary_id):
        row=get_db().execute('SELECT * FROM p8_daily_summaries WHERE id=? AND user_id=?',(summary_id,session['user_id'])).fetchone()
        if not row: abort(404)
        return render_template('operations_summary.html',summary=json.loads(row['summary_json']),created_at=row['created_at'])


def worker_tick(path):
    with closing(connect(path)) as conn, conn:
        scheduled=create_due_summaries(conn)
    return worker_once(path) or bool(scheduled)

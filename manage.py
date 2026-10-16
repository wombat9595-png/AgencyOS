"""Local administration and explicitly started Phase 3 worker."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
import time
import uuid
import signal
from contextlib import closing
from discovery import POLICIES, NOMINATIM, OVERPASS
from phase3_store import stamp

def main():
    parser=argparse.ArgumentParser(description='AgencyOS local maintenance; never sends email or publishes websites.')
    commands=parser.add_subparsers(dest='command',required=True)
    worker=commands.add_parser('worker',help='Run the selected queue: --phase5 sales, --phase4 research, or legacy Phase 3')
    worker.add_argument('--phase5',action='store_true',help='Process sales workflow jobs and internal follow-up reviews; no live email')
    worker.add_argument('--phase4',action='store_true',help='Process Phase 4 local schedules/jobs and approved audits ONLY; no legacy AI/discovery calls')
    worker.add_argument('--watch',action='store_true',help='Poll until Control+C; selected phase also processes its enabled internal schedules')
    worker.add_argument('--database',help='Explicit SQLite path; relative paths resolve under the checkout, not the terminal directory')
    doctor=commands.add_parser('doctor',help='Read-only database, queue and worker diagnostics; does not execute tasks')
    doctor.add_argument('--phase5',action='store_true')
    doctor.add_argument('--phase4',action='store_true')
    doctor.add_argument('--database')
    doctor.add_argument('--json',action='store_true',help='Machine-readable diagnostics')
    review=commands.add_parser('policy-review',help='Record YOUR current review of all three provider policies; does not verify them automatically')
    review.add_argument('--reviewer',required=True);review.add_argument('--contact',required=True)
    review.add_argument('--output',default='.development/osm-policy.json')
    review.add_argument('--interval',type=float,default=2);review.add_argument('--daily-limit',type=int,default=20)
    review.add_argument('--i-have-verified-current-policies',action='store_true',required=True)
    args=parser.parse_args()
    if args.command=='policy-review':
        import re
        if not args.reviewer.strip() or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',args.contact) or not 2<=args.interval<=60 or not 1<=args.daily_limit<=20:
            parser.error('Supply reviewer, a contact email, interval 2–60 seconds and daily limit 1–20.')
        path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
        # Never replace a previous policy review silently.
        record=dict(reviewed=True,reviewed_at=stamp(),reviewer=args.reviewer,contact=args.contact,policy_urls=list(POLICIES),
                    endpoints=[NOMINATIM,OVERPASS],interval_seconds=args.interval,daily_limit=args.daily_limit)
        try:
            with path.open('x') as handle:json.dump(record,handle,indent=2)
        except FileExistsError:parser.error('Review file already exists. Use a new --output filename; previous reviews are preserved.')
        os.chmod(path,0o600)
        print('Recorded your attestation at',path,'. Set AGENCYOS_OSM_POLICY_FILE in BOTH app and worker shells. This command did not fetch or independently verify policies.')
        return
    import app
    import runtime_status
    from phase3_store import connect
    if args.database:app.DB_PATH=runtime_status.database_path(args.database)
    if args.phase4 and args.phase5:parser.error('Choose --phase4 or --phase5, not both.')
    phase='5' if args.phase5 else ('4' if args.phase4 else '3')
    if not Path(app.DB_PATH).is_file():parser.error('Selected database does not exist: '+app.DB_PATH+'. Start app.py with the same AGENCYOS_DB; the worker will not create another database.')
    # Read-only startup checks; no migrations or task execution through doctor.
    try:
        with closing(sqlite3.connect(Path(app.DB_PATH).as_uri()+'?mode=ro',uri=True)) as conn:
            info=runtime_status.status(conn,app.DB_PATH,phase)
            if info['database_identity']=='Not migrated':parser.error('Selected database needs current migrations. Start matching app.py on a backup copy first.')
    except sqlite3.Error:parser.error('Cannot read selected database: '+app.DB_PATH)
    if args.command=='doctor':
        if args.json:print(json.dumps(info,sort_keys=True))
        else:
            print('Database: '+info['database_path']+'\nIdentity: '+info['database_identity']+'\nSelected phase: '+phase)
            print('Queues: '+json.dumps(info['queues'],sort_keys=True))
            print('Matching recent worker: '+str(info['selected_worker_connected'])+'; paused: '+str(info['paused']))
            print('Phase 5 sales needs --phase5; Agency Manager research needs --phase4; the legacy research queue uses neither flag.')
        return
    if args.phase5:
        from sales_engine import worker_once
    elif args.phase4:
        from phase4 import worker_once
    else:
        from phase3 import worker_once
    print('Worker phase '+phase+' | database '+info['database_path']+' | identity '+info['database_identity'],flush=True)
    for other,counts in info['queues'].items():
        if other!=phase and counts.get('Queued',0):
            print('Notice: '+str(counts['Queued'])+' queued task(s) belong to Phase '+other+' and are not consumed by this worker.',flush=True)
    worker_id=uuid.uuid4().hex
    def terminate(_signum,_frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,terminate)
    try:
        while True:
            runtime_status.heartbeat(app.DB_PATH,worker_id,phase)
            try:worked=worker_once(app.DB_PATH)
            except sqlite3.OperationalError:parser.error('Selected database is unavailable, busy or not migrated to the selected phase. Check AGENCYOS_DB and start the matching app first.')
            if worked:print('Processed one task.',flush=True)
            if not args.watch:
                if not worked:print('No queued task.',flush=True)
                break
            if not worked:time.sleep(1)
    finally:
        runtime_status.heartbeat(app.DB_PATH,worker_id,phase,'stopped')

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Worker stopped. An active request may have completed; interrupted tasks never automatically retry.')

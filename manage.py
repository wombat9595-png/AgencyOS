"""Local administration and explicitly started Phase 3 worker."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
import time
from discovery import POLICIES, NOMINATIM, OVERPASS
from phase3_store import stamp

def main():
    parser=argparse.ArgumentParser(description='AgencyOS local maintenance; never sends email or publishes websites.')
    commands=parser.add_subparsers(dest='command',required=True)
    worker=commands.add_parser('worker',help='Run the selected queue (legacy Phase 3, or --phase4)')
    worker.add_argument('--phase4',action='store_true',help='Process Phase 4 local schedules/jobs and approved audits ONLY; no legacy AI/discovery calls')
    worker.add_argument('--watch',action='store_true',help='Poll until Control+C; --phase4 also runs owner-enabled local schedules')
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
    if args.phase4:
        from phase4 import worker_once
    else:
        from phase3 import worker_once
    # No init_db here: avoid accidental migrations. Start the selected app once first.
    if not Path(app.DB_PATH).is_file():parser.error('Selected database does not exist. Start app.py first with the same AGENCYOS_DB.')
    while True:
        try:worked=worker_once(app.DB_PATH)
        except sqlite3.OperationalError:parser.error('Selected database is unavailable, busy or not migrated to the selected phase. Check AGENCYOS_DB and start the matching app first.')
        if not args.watch:
            print('Processed one task.' if worked else 'No queued task.');break
        if not worked:time.sleep(1)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Worker stopped. An active request may have completed; interrupted tasks never automatically retry.')

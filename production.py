"""Explicit local operational commands; no network actions or purchases."""
import argparse
from pathlib import Path
from datetime import datetime,timezone
import json
import sqlite3
import os
from contextlib import closing
from production_ops import backup,restore,collect_alerts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('migrate','create-owner','backup','restore','check'))
    parser.add_argument('--database',required=True)
    parser.add_argument('--output');parser.add_argument('--input');parser.add_argument('--destination')
    parser.add_argument('--key-file');parser.add_argument('--staging-root')
    parser.add_argument('--username');parser.add_argument('--password-file')
    parser.add_argument('--upgrade-copy',action='store_true',help='Explicitly authorize additive migrations of this isolated backup/restore copy')
    args=parser.parse_args();database=Path(args.database).resolve()
    if args.command=='restore':
        if not all((args.input,args.destination,args.key_file)):parser.error('Restore requires --input --destination --key-file')
        print(json.dumps(restore(args.input,args.destination,Path(args.key_file).read_bytes().strip())));return
    if args.command=='migrate':
        if database.exists() and not args.upgrade_copy:
            parser.error('Migrations require an isolated restored copy or --database pointing to a new file. Use the documented upgrade procedure.')
        if database.exists():
            with closing(sqlite3.connect(database)) as conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':parser.error('Copy failed integrity check')
        import app
        app.DB_PATH=str(database);app.init_db();print('Migration complete: '+str(database));return
    if not database.is_file():parser.error('Database must already exist')
    if args.command=='create-owner':
        if not args.username or not args.password_file:parser.error('Owner creation requires --username and --password-file')
        password=Path(args.password_file).read_text().strip()
        if len(password)<16 or len(args.username)>254:parser.error('Use a password of at least 16 characters and a bounded username')
        from werkzeug.security import generate_password_hash
        from phase3_store import connect
        with closing(connect(database)) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]:parser.error('Owner already exists; no account replaced')
            conn.execute('INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)',(args.username,generate_password_hash(password),datetime.now(timezone.utc).isoformat()))
        print('Owner created; password was not logged.');return
    if args.command=='backup':
        if not args.key_file or not args.output:parser.error('Backup requires --key-file and --output')
        output=Path(args.output)
        if output.is_dir():output=output/('agencyos-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.enc')
        print(json.dumps(backup(database,output,Path(args.key_file).read_bytes().strip(),args.staging_root)));return
    print(json.dumps(dict(active_alerts=collect_alerts(database))))


if __name__=='__main__':main()

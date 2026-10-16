"""WSGI entry point. Provision and migrate explicitly before starting the service."""
from pathlib import Path
import sqlite3
from contextlib import closing
from app import app, DB_PATH

if not Path(DB_PATH).is_file():raise RuntimeError('Provision and migrate the database before starting WSGI')
with closing(sqlite3.connect(Path(DB_PATH).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
    conn.execute('SELECT id FROM ops_backups LIMIT 1')

"""Filesystem-authorised owner recovery. No HTTP reset endpoint or new accounts.

Supports old AgencyOS databases without importing app.py or running application
migrations. The owner selects the existing file, confirms its records and enters
a new password locally. No credentials are printed, emailed or written as text.
"""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

ROOT=Path(__file__).resolve().parent
SKIP={'.git','node_modules','__pycache__','output','backups','venv','.venv','.venv313','.venv-first-sale','Library'}


def existing_database(value):
    path=Path(value).expanduser()
    if path.is_symlink() or not path.is_file():raise ValueError('Choose an existing AgencyOS database file, not a link or a new filename.')
    return path.resolve()


def inspect_database(value):
    path=existing_database(value)
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as conn:
            conn.row_factory=sqlite3.Row
            columns={r[1] for r in conn.execute('PRAGMA table_info(users)')}
            if not {'id','username','password_hash'}<=columns:raise ValueError('This file is not a supported AgencyOS account database.')
            owner=conn.execute('SELECT id,username FROM users ORDER BY id LIMIT 1').fetchone()
            if not owner:raise ValueError('This database has no owner account. Select the existing workspace you used before; recovery will not create another account.')
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'leads','projects'}<=tables:raise ValueError('This file does not contain the AgencyOS business records expected for recovery.')
            counts={name:conn.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('leads','projects','quotes','invoices') if name in tables}
            usernames=[r[0] for r in conn.execute('SELECT username FROM users ORDER BY id LIMIT 20')]
            return dict(path=str(path),owner_id=owner['id'],username=owner['username'],usernames=usernames,counts=counts)
    except sqlite3.Error:raise ValueError('Could not read this AgencyOS database. Select the actual .db/.sqlite3 file and keep the original files intact.') from None


def find_databases(roots):
    """Bounded local inventory; no home-wide search, network or symlink traversal."""
    found=[];seen=set();visited=0
    def walk(path,depth):
        nonlocal visited
        if visited>=1500 or len(found)>=50 or depth>4 or path.is_symlink():return
        visited+=1
        if path.is_file():
            if path.suffix.casefold() in ('.db','.sqlite','.sqlite3'):
                try:
                    report=inspect_database(path)
                    if report['path'] not in seen:found.append(report);seen.add(report['path'])
                except (ValueError,OSError):pass
            return
        if not path.is_dir() or path.name in SKIP or path.name.startswith('.venv'):return
        try:
            for child in sorted(path.iterdir()):walk(child,depth+1)
        except OSError:return
    for root in roots:walk(Path(root),0)
    return found


def backup_database(database,backup_root):
    """Encrypted SQLite snapshot with a private recovery key; source is read-only."""
    database=existing_database(database);root=Path(backup_root).expanduser()
    if root.is_symlink():raise ValueError('Recovery backup directory must not be a symbolic link.')
    root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    keyfile=root/'recovery-backup.secret'
    if keyfile.is_symlink():raise ValueError('Recovery key must not be a symbolic link.')
    if not keyfile.exists():
        fd=os.open(keyfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as handle:handle.write(Fernet.generate_key())
    keyfile.chmod(0o600)
    try:cipher=Fernet(keyfile.read_bytes())
    except (ValueError,OSError):raise ValueError('Recovery backup key is invalid. Restore that key; no password was changed.') from None
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        copy=Path(tmp)/'snapshot.sqlite3'
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=5)) as source,closing(sqlite3.connect(copy)) as destination:
            started=time.monotonic()
            def progress(*_):
                if time.monotonic()-started>30:raise ValueError('Database is busy. Stop its AgencyOS worker and retry; no password was changed.')
            source.backup(destination,pages=100,progress=progress,sleep=.05)
            if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed. No account was changed.')
        if copy.stat().st_size>128*1024*1024:raise ValueError('Recovery snapshot exceeds 128 MiB. No password was changed; preserve this database for assisted recovery.')
        raw=copy.read_bytes();encrypted=cipher.encrypt(raw)
    if cipher.decrypt(encrypted)!=raw:raise ValueError('Backup verification failed. No account was changed.')
    output=root/('before-login-recovery-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(6)+'.sqlite3.enc')
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as handle:handle.write(encrypted)
    return dict(backup=str(output),key_file=str(keyfile),sha256=hashlib.sha256(encrypted).hexdigest())


def reset_owner(database,password,backup_root,expected_owner):
    """Update only the existing first owner, never create/delete/rename users."""
    if not isinstance(password,str) or not 16<=len(password)<=1024 or not password.strip() or any(c in password for c in '\r\n\x00'):
        raise ValueError('Choose a new password of 16–1,024 characters without line breaks.')
    report=inspect_database(database)
    if (report['owner_id'],report['username'])!=tuple(expected_owner):raise ValueError('Selected owner changed. Reopen recovery and review the workspace again.')
    backup=backup_database(report['path'],backup_root)
    password_hash=generate_password_hash(password,method='pbkdf2:sha256')
    with closing(sqlite3.connect(Path(report['path']).as_uri()+'?mode=rw',uri=True,timeout=10)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        owner=conn.execute('SELECT id,username FROM users ORDER BY id LIMIT 1').fetchone()
        if not owner or tuple(owner)!=tuple(expected_owner):raise ValueError('Owner changed during recovery. No password was reset; review the workspace again.')
        conn.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash,owner[0]))
        conn.execute('CREATE TABLE IF NOT EXISTS security_password_resets(user_id INTEGER PRIMARY KEY,reset_at REAL NOT NULL)')
        conn.execute('INSERT INTO security_password_resets VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET reset_at=excluded.reset_at',(owner[0],time.time()))
        conn.execute('CREATE TABLE IF NOT EXISTS owner_recovery_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,created_at REAL NOT NULL,backup_hash TEXT NOT NULL)')
        conn.execute('INSERT INTO owner_recovery_events(user_id,created_at,backup_hash) VALUES(?,?,?)',(owner[0],time.time(),backup['sha256']))
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'security_rate' in tables:conn.execute('DELETE FROM security_rate')
        if 'security_audit' in tables:
            conn.execute('INSERT INTO security_audit(actor,event,object_json,created_at) VALUES(?,?,?,?)',(owner[0],'owner_password_recovered_locally',json.dumps({'backup_hash':backup['sha256']}),time.time()))
        conn.commit()
    return dict(report,**backup)


def candidate_roots():
    roots=[ROOT,Path.home()/'Library'/'Application Support'/'AgencyOS']
    try:roots.extend(p for p in ROOT.parent.iterdir() if p.is_dir() and 'agencyos' in p.name.casefold())
    except OSError:pass
    return roots


def main():
    # A native local dialog, never an unauthenticated web-password reset.
    try:
        import tkinter as tk
        from tkinter import ttk,filedialog,messagebox
        window=tk.Tk()
    except Exception:
        # Do not silently turn a GUI invocation into an account creation flow.
        raise SystemExit('The local recovery window could not open. Use the official python.org macOS Python installer (includes Tk), then reopen Recover AgencyOS Login.command.') from None
    window.title('Recover your existing AgencyOS login');window.geometry('850x610')
    frame=ttk.Frame(window,padding=20);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Recover access without creating another account',font=('',17,'bold')).pack(anchor='w')
    ttk.Label(frame,text='Choose the workspace containing your records. Its existing owner username is shown below.\nYour password stays on this Mac. An encrypted backup is made before any change.',wraplength=790).pack(anchor='w',pady=12)
    reports=find_databases(candidate_roots())
    choices=tk.Listbox(frame,height=6,exportselection=False);choices.pack(fill='x')
    details=tk.StringVar(value='Select a workspace, or browse for your existing AgencyOS database file.')
    ttk.Label(frame,textvariable=details,wraplength=790).pack(anchor='w',pady=10)
    def refresh():
        choices.delete(0,'end')
        for r in reports:choices.insert('end',f"Owner: {r['username']} | leads: {r['counts'].get('leads',0)} | projects: {r['counts'].get('projects',0)} | {r['path']}")
    def selected(*_):
        if choices.curselection():
            r=reports[choices.curselection()[0]]
            details.set('Existing owner username: '+r['username']+'\nDatabase: '+r['path']+'\nOther saved usernames: '+', '.join(r['usernames'])+'\nOnly the owner above will be reset; no users or business records will be removed.')
    choices.bind('<<ListboxSelect>>',selected)
    def browse():
        name=filedialog.askopenfilename(title='Choose the existing AgencyOS database',filetypes=[('SQLite databases','*.db *.sqlite *.sqlite3'),('All files','*')])
        if name:
            try:r=inspect_database(name)
            except ValueError as exc:messagebox.showerror('Database not selected',str(exc));return
            reports.append(r);refresh();choices.selection_set(len(reports)-1);selected()
    ttk.Button(frame,text='Browse for another existing workspace…',command=browse).pack(anchor='w')
    first=tk.StringVar();second=tk.StringVar()
    ttk.Label(frame,text='New password (at least 16 characters)').pack(anchor='w',pady=(12,0));ttk.Entry(frame,textvariable=first,show='•',width=60).pack(anchor='w')
    ttk.Label(frame,text='Enter the same new password again').pack(anchor='w',pady=(8,0));ttk.Entry(frame,textvariable=second,show='•',width=60).pack(anchor='w')
    def recover():
        if not choices.curselection():messagebox.showerror('Choose your existing workspace','Select the database containing your records first.');return
        r=reports[choices.curselection()[0]]
        if first.get()!=second.get():messagebox.showerror('Passwords differ','Enter the same new password in both boxes.');return
        if not messagebox.askyesno('Confirm selected existing account','Reset the existing owner '+r['username']+' in:\n'+r['path']+'\n\nNo account or database will be created. Continue?'):return
        try:
            result=reset_owner(r['path'],first.get(),Path.home()/'Library'/'Application Support'/'AgencyOS-Recovery',(r['owner_id'],r['username']))
        except (ValueError,OSError,sqlite3.Error) as exc:messagebox.showerror('Recovery did not finish',str(exc));return
        first.set('');second.set('')
        messagebox.showinfo('Existing login recovered','Username: '+r['username']+'\nUse the new password you just entered at your existing sign-in page.\n\nDatabase: '+r['path']+'\nEncrypted safety backup: '+result['backup']+'\nKeep the backup key private: '+result['key_file']+'\n\nCurrent AgencyOS sessions are revoked. If using an old Phase 2 app, restart that old app to discard its earlier sessions. Do not create another owner account.')
    ttk.Button(frame,text='Back up and reset this existing owner password',command=recover).pack(anchor='w',pady=18)
    refresh()
    if reports:choices.selection_set(0);selected()
    window.mainloop()


if __name__=='__main__':main()

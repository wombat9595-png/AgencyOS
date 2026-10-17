"""Dedicated-account Gmail OAuth and bounded, persistent correspondence.

Email is untrusted data. No tools, attachments, remote HTML or model instructions
are executed. Real network access occurs only after explicit OAuth or polling.
"""
import base64
from contextlib import closing
from email.message import EmailMessage
from email.utils import parseaddr, formataddr
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from cryptography.fernet import Fernet, InvalidToken
from flask import abort, flash, redirect, render_template, request, session, url_for
from phase3_store import WorkflowError, connect, stamp
from phase4_store import paused
from production_security import audit, secret
import sales_email
import sales_store

ACCOUNT = 'benji.price.webdesign@gmail.com'
DISPLAY = 'Benji Price | Web Design'
READ = 'https://www.googleapis.com/auth/gmail.readonly'
SEND = 'https://www.googleapis.com/auth/gmail.send'
# Lets AgencyOS put approved outreach into Gmail Drafts. Google has no drafts-only scope; AgencyOS never calls send with it.
COMPOSE = 'https://www.googleapis.com/auth/gmail.compose'
API = 'https://gmail.googleapis.com/gmail/v1/users/me/'
TOKEN = 'https://oauth2.googleapis.com/token'
AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
REVOKE = 'https://oauth2.googleapis.com/revoke'


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS gmail_accounts (
      owner_id INTEGER PRIMARY KEY REFERENCES users(id), email TEXT NOT NULL,
      token_cipher TEXT NOT NULL, connected_at TEXT NOT NULL, last_sync REAL NOT NULL DEFAULT 0,
      cursor TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', polling INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS gmail_oauth (
      state_hash TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, verifier_cipher TEXT NOT NULL,
      redirect_uri TEXT NOT NULL, scopes TEXT NOT NULL, expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS gmail_mail (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, external_id TEXT NOT NULL,
      thread_id TEXT NOT NULL, sender TEXT NOT NULL, flow_id INTEGER REFERENCES p5_flows(id),
      lead_id INTEGER REFERENCES leads(id), content_cipher TEXT NOT NULL,
      intent_json TEXT NOT NULL, received_at TEXT NOT NULL, direction TEXT NOT NULL DEFAULT 'incoming',
      UNIQUE(owner_id,external_id));
    CREATE TABLE IF NOT EXISTS gmail_drafts (
      id INTEGER PRIMARY KEY, mail_id INTEGER NOT NULL UNIQUE REFERENCES gmail_mail(id),
      owner_id INTEGER NOT NULL, content_cipher TEXT NOT NULL, content_hash TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Needs review', provider_id TEXT UNIQUE, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS gmail_jobs (
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Queued',
      attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL, lease REAL, token TEXT,
      error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS gmail_pending_poll ON gmail_jobs(owner_id)
      WHERE status IN ('Queued','Running');
    CREATE TABLE IF NOT EXISTS gmail_policy (
      owner_id INTEGER PRIMARY KEY, approved INTEGER NOT NULL DEFAULT 0,
      evidence TEXT NOT NULL DEFAULT '', contact_details TEXT NOT NULL DEFAULT '',
      daily_limit INTEGER NOT NULL DEFAULT 5, approved_at REAL NOT NULL DEFAULT 0);
    ''')
    columns={r[1] for r in conn.execute('PRAGMA table_info(gmail_accounts)')}
    if 'drafting' not in columns:conn.execute('ALTER TABLE gmail_accounts ADD COLUMN drafting INTEGER NOT NULL DEFAULT 0')
    columns={r[1] for r in conn.execute('PRAGMA table_info(gmail_drafts)')}
    if 'attempted_at' not in columns:conn.execute("ALTER TABLE gmail_drafts ADD COLUMN attempted_at TEXT NOT NULL DEFAULT ''")


def cipher():
    try:
        key = secret('AGENCYOS_GMAIL_KEY')
        if not key: raise ValueError()
        return Fernet(key.encode())
    except (ValueError, OSError):
        raise WorkflowError('Private Gmail encryption key unavailable. Use the private local launcher.') from None


def seal(value):
    return cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def unseal(value):
    try: return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError, TypeError):
        raise WorkflowError('Gmail encrypted record cannot be read. Restore its matching private key; do not replace it.') from None


def client_config():
    """Desktop client only; owner selects a downloaded file, never pastes passwords."""
    try:
        path = Path(os.environ.get('AGENCYOS_GMAIL_CLIENT_FILE', ''))
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077: raise ValueError()
        config = json.loads(path.read_text())['installed']
        if not config['client_id'].endswith('.apps.googleusercontent.com') or not config['client_secret']: raise ValueError()
        return {k: config[k] for k in ('client_id', 'client_secret')}
    except (OSError, ValueError, KeyError, TypeError):
        raise WorkflowError('Select a Google Desktop OAuth client JSON in the Gmail page. It must be a private file (owner access only).') from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def google_request(url, *, token=None, data=None, form=False):
    """Fixed Google origins; no provider-controlled redirects or raw error bodies."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in ('gmail.googleapis.com','oauth2.googleapis.com') or parts.port not in (None,443) or parts.username or parts.password:
        raise WorkflowError('Gmail request origin rejected.')
    headers = {'Accept':'application/json'}
    if token: headers['Authorization'] = 'Bearer '+token
    raw = None
    if data is not None:
        raw = (urlencode(data) if form else json.dumps(data)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    try:
        with build_opener(_NoRedirect()).open(Request(url, data=raw, headers=headers), timeout=15) as response:
            body = response.read(2_000_001)
        if len(body)>2_000_000: raise WorkflowError('Gmail response exceeded the local size limit.')
        parsed=json.loads(body or b'{}')
        if not isinstance(parsed,dict):raise WorkflowError('Google returned an unexpected response shape.')
        return parsed
    except HTTPError as exc:
        raise WorkflowError('Google request rejected (HTTP '+str(exc.code)+'). Review account access; no raw provider error was logged.') from None
    except (URLError, OSError, ValueError):
        raise WorkflowError('Google could not be reached or returned invalid data. No automatic message resend.') from None


def begin_oauth(conn, owner, redirect_uri, allow_send=False, allow_drafts=False):
    parts = urlsplit(redirect_uri)
    if parts.scheme!='http' or parts.hostname!='127.0.0.1' or parts.path!='/gmail/oauth/callback' or parts.query or parts.fragment or parts.username or parts.password:
        raise WorkflowError('Gmail authorisation must use this private 127.0.0.1 app, not a public dashboard.')
    config = client_config()
    state = secrets.token_urlsafe(32); verifier = secrets.token_urlsafe(48)
    scopes = [READ] + ([SEND] if allow_send else []) + ([COMPOSE] if allow_drafts else [])
    conn.execute('DELETE FROM gmail_oauth WHERE expires<? OR owner_id=?',(time.time(),owner))
    conn.execute('INSERT INTO gmail_oauth VALUES(?,?,?,?,?,?)',(hashlib.sha256(state.encode()).hexdigest(),owner,seal(verifier),redirect_uri,' '.join(scopes),time.time()+600))
    conn.commit()
    return AUTH+'?'+urlencode(dict(client_id=config['client_id'],redirect_uri=redirect_uri,response_type='code',scope=' '.join(scopes),state=state,
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),code_challenge_method='S256',
        access_type='offline',prompt='consent select_account',login_hint=ACCOUNT))


def finish_oauth(conn, owner, state, code):
    conn.execute('BEGIN IMMEDIATE')
    row=conn.execute('SELECT * FROM gmail_oauth WHERE state_hash=? AND owner_id=? AND expires>?',(hashlib.sha256(state.encode()).hexdigest(),owner,time.time())).fetchone()
    if not row: conn.rollback(); raise WorkflowError('Gmail sign-in expired or state did not match. Start a fresh connection.')
    conn.execute('DELETE FROM gmail_oauth WHERE state_hash=?',(row['state_hash'],));conn.commit()
    result=google_request(TOKEN,data=dict(client_config(),code=code,code_verifier=unseal(row['verifier_cipher']),redirect_uri=row['redirect_uri'],grant_type='authorization_code'),form=True)
    if not isinstance(result.get('access_token'),str) or not isinstance(result.get('refresh_token'),str):
        raise WorkflowError('Google did not provide durable authorisation. Reconnect with consent; no connection was recorded.')
    scopes=set(result.get('scope','').split())
    if READ not in scopes or not scopes<=set(row['scopes'].split()):
        raise WorkflowError('Google permissions differ from the requested minimum scopes. Revoke this grant in Google and reconnect.')
    profile=google_request(API+'profile',token=result['access_token'])
    if profile.get('emailAddress','').casefold()!=ACCOUNT:
        # Do not revoke a wrong account's existing broader grant; never save it.
        raise WorkflowError('Wrong Google account. No account was connected or retained. Select only '+ACCOUNT+'. Review/remove this attempted grant in Google.')
    result['expires_at']=time.time()+min(int(result.get('expires_in',3600)),3600)
    conn.execute('INSERT INTO gmail_accounts(owner_id,email,token_cipher,connected_at) VALUES(?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET email=excluded.email,token_cipher=excluded.token_cipher,connected_at=excluded.connected_at,error=\'\'',(owner,ACCOUNT,seal(result),stamp()))
    audit(conn,'gmail_connected',owner,{'account':ACCOUNT,'scopes':sorted(scopes)})
    conn.commit()


def access_token(conn, owner, sending=False):
    row=conn.execute('SELECT * FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
    if not row or row['email']!=ACCOUNT: raise WorkflowError('Dedicated Gmail account is not connected.')
    record=unseal(row['token_cipher'])
    if sending and SEND not in record.get('scope','').split(): raise WorkflowError('Sending scope has not been separately authorised in Google.')
    if record.get('expires_at',0)<time.time()+60:
        result=google_request(TOKEN,data=dict(client_config(),refresh_token=record['refresh_token'],grant_type='refresh_token'),form=True)
        if not result.get('access_token'): raise WorkflowError('Gmail access expired. Reconnect your dedicated account.')
        if result.get('scope') and not set(result['scope'].split())<=set(record['scope'].split()): raise WorkflowError('Unexpected refreshed Gmail permissions.')
        record.update(result);record['expires_at']=time.time()+min(int(result.get('expires_in',3600)),3600)
        conn.execute('UPDATE gmail_accounts SET token_cipher=? WHERE owner_id=?',(seal(record),owner));conn.commit()
    return record['access_token']


def can_draft(conn, owner):
    row=conn.execute('SELECT * FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
    return bool(row and row['email']==ACCOUNT and COMPOSE in unseal(row['token_cipher']).get('scope','').split())


def create_outreach_draft(conn, owner, recipient, subject, body):
    """Put an owner-approved message in Gmail Drafts. Never sends: the owner presses Send in Gmail."""
    if not can_draft(conn,owner):raise WorkflowError('Gmail Drafts is not connected.')
    if re.search(r'[\r\n]',subject):raise WorkflowError('The subject must be one line.')
    message=EmailMessage();message['From']=formataddr((DISPLAY,ACCOUNT));message['To']=sales_email.address(recipient)
    message['Subject']=subject;message.set_content(body)
    result=google_request(API+'drafts',token=access_token(conn,owner),data=dict(message=dict(raw=base64.urlsafe_b64encode(message.as_bytes()).decode())))
    if not isinstance(result.get('id'),str):raise WorkflowError('Gmail did not confirm the draft. Check your Drafts folder before trying again.')
    audit(conn,'gmail_outreach_draft_created',owner,{'draft_id':result['id'],'sent':False})
    return result['id']


def sent_since(conn, owner, recipient, since):
    """True when Gmail's Sent folder has a message to this address after the given Unix time."""
    query='in:sent to:'+sales_email.address(recipient)+' after:'+str(int(since))
    result=google_request(API+'messages?'+urlencode(dict(q=query,maxResults=1)),token=access_token(conn,owner))
    return bool(result.get('messages'))


def _text(part, depth=0):
    if depth>8 or part.get('filename') or part.get('body',{}).get('attachmentId'): return ''
    if part.get('mimeType')=='text/plain':
        value=part.get('body',{}).get('data','')
        if len(value)>100000: return '[Oversized email body omitted; review in Gmail]'
        try: return base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode('utf-8',errors='replace')[:50000]
        except (ValueError, TypeError): return '[Invalid plain-text content; review in Gmail]'
    return '\n'.join(_text(p,depth+1) for p in part.get('parts',[])[:20])[:50000]


def intent(text,subject=''):
    """Explainable hints only. Never acceptance, authority or a financial action."""
    import sales_engine
    base=sales_engine.classify(text)
    lower=(subject+' '+text).casefold()
    labels=[]
    for label,pattern in (
        ('pricing',r'\b(price|pricing|cost|how much|quote)\b'),
        ('requirements',r'\b(pages?|colours?|colors?|logo|domain|hosting|website needs|services)\b'),
        ('revision',r'\b(revision|change|replace|update|adjust)\b'),
        ('concern',r'\b(concern|expensive|dispute|refund|complaint)\b'),
        ('urgent',r'\b(urgent|asap|deadline)\b')):
        if re.search(pattern,lower): labels.append(label)
    return dict(base,signals=labels,acceptance=False,authority=False,provenance='Local phrase matching; not AI judgement or authenticated sender identity')


def match_flow(conn,owner,sender,thread):
    previous=conn.execute('SELECT DISTINCT flow_id FROM gmail_mail WHERE owner_id=? AND thread_id=? AND flow_id IS NOT NULL',(owner,thread)).fetchall()
    if len(previous)==1:
        expected=conn.execute('SELECT l.email FROM leads l JOIN p5_flows f ON f.lead_id=l.id WHERE f.id=? AND f.user_id=?',(previous[0][0],owner)).fetchone()
        if expected and expected[0].casefold()==sender:return previous[0][0]
    matches=conn.execute("SELECT f.id FROM p5_flows f JOIN leads l ON l.id=f.lead_id WHERE f.user_id=? AND lower(l.email)=? AND f.state!='Cancelled'",(owner,sender)).fetchall()
    return matches[0][0] if len(matches)==1 else None


def ingest(conn,owner,item):
    identifier=item.get('id','');thread=item.get('threadId','')
    if not re.fullmatch('[a-zA-Z0-9_-]{1,200}',identifier) or not re.fullmatch('[a-zA-Z0-9_-]{1,200}',thread): raise WorkflowError('Invalid Gmail message identity.')
    if conn.execute('SELECT 1 FROM gmail_mail WHERE owner_id=? AND external_id=?',(owner,identifier)).fetchone(): return False
    headers={}
    for header in item.get('payload',{}).get('headers',[])[:100]:
        key=str(header.get('name','')).casefold()
        if key in headers and key in ('from','message-id'): raise WorkflowError('Ambiguous email identity headers; review the original in Gmail.')
        headers[key]=str(header.get('value',''))[:1000]
    sender=sales_email.address(parseaddr(headers.get('from',''))[1])
    body=_text(item.get('payload',{})) or '[No plain-text body; inspect safely in Gmail]'
    subject=headers.get('subject','')[:200]
    flow_id=match_flow(conn,owner,sender,thread)
    lead=conn.execute('SELECT id FROM leads WHERE lower(email)=?',(sender,)).fetchall()
    lead_id=lead[0][0] if len(lead)==1 else None
    analysis=intent(body,subject)
    direction='outgoing' if sender==ACCOUNT else 'incoming'
    content=dict(subject=subject,body=body,message_id=headers.get('message-id',''),references=headers.get('references','')[:1000],
                 to=headers.get('to',''),sender=sender,auth_results=headers.get('authentication-results',''),untrusted=True)
    identifier=conn.execute('INSERT INTO gmail_mail(owner_id,external_id,thread_id,sender,flow_id,lead_id,content_cipher,intent_json,received_at,direction) VALUES(?,?,?,?,?,?,?,?,?,?)',
        (owner,identifier,thread,sender,flow_id,lead_id,seal(content),json.dumps(analysis),stamp(),direction)).lastrowid
    if direction=='incoming':
        if sales_email.opted_out(body): sales_email.suppress(conn,owner,sender,'Gmail opt-out; conservative suppression')
        if flow_id:
            conn.execute("UPDATE p5_followups SET status='Stopped' WHERE message_id IN (SELECT id FROM p5_messages WHERE flow_id=?)",(flow_id,))
            conn.execute("UPDATE p5_flows SET follow_state=? WHERE id=?",('Suppressed' if sales_email.opted_out(body) else 'Reply awaiting owner review',flow_id))
            # Existing correspondence event/handoff retains transport provenance.
            previous=conn.execute('SELECT * FROM p5_messages WHERE flow_id=? AND lower(recipient)=? ORDER BY id DESC LIMIT 1',(flow_id,sender)).fetchone()
            if previous:
                sales_email.apply_event(conn,previous,'gmail','gmail:'+item['id'],'reply',body[:10000],dict(text=body[:10000],gmail_id=item['id'],thread_id=thread,provenance='OAuth mailbox; sender claims untrusted'))
        audit(conn,'gmail_message_recorded',owner,{'mail_id':identifier,'matched':bool(flow_id)})
    return True


def queue_poll(conn,owner):
    if not conn.execute('SELECT 1 FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone(): raise WorkflowError('Connect your dedicated Gmail account first.')
    conn.execute('INSERT OR IGNORE INTO gmail_jobs(owner_id,due,created_at) VALUES(?,?,?)',(owner,time.time(),stamp()))


def poll_once(path):
    """One bounded, retryable read job. No inbox reads before explicit opt-in."""
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if paused(conn): conn.commit();return False
        conn.execute("UPDATE gmail_drafts SET status='Outcome unknown' WHERE status='Sending' AND attempted_at<?",(__import__('datetime').datetime.fromtimestamp(time.time()-600,__import__('datetime').timezone.utc).isoformat(),))
        conn.execute("UPDATE gmail_jobs SET status=CASE WHEN attempts<3 THEN 'Queued' ELSE 'Failed' END,due=?,error='Expired read lease; safe bounded retry' WHERE status='Running' AND lease<?",(time.time()+30,time.time()))
        for row in conn.execute('SELECT owner_id FROM gmail_accounts WHERE polling=1 AND last_sync<?',(time.time()-300,)).fetchall(): queue_poll(conn,row[0])
        job=conn.execute("SELECT * FROM gmail_jobs WHERE status='Queued' AND due<=? ORDER BY id LIMIT 1",(time.time(),)).fetchone()
        if not job:conn.commit();return False
        token=secrets.token_hex(16)
        conn.execute("UPDATE gmail_jobs SET status='Running',attempts=attempts+1,token=?,lease=? WHERE id=?",(token,time.time()+600,job['id']));conn.commit()
        try:
            owner=job['owner_id'];access=access_token(conn,owner)
            account=conn.execute('SELECT * FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
            params=dict(maxResults=20,q='in:inbox newer_than:30d')
            if account['cursor']:params['pageToken']=account['cursor']
            result=google_request(API+'messages?'+urlencode(params),token=access)
            for item in result.get('messages',[])[:20]:
                if not re.fullmatch('[a-zA-Z0-9_-]{1,200}',str(item.get('id',''))):raise WorkflowError('Invalid Gmail list identifier.')
                if conn.execute('SELECT 1 FROM gmail_mail WHERE owner_id=? AND external_id=?',(owner,item['id'])).fetchone():continue
                message=google_request(API+'messages/'+item['id']+'?format=full',token=access)
                if message.get('id')!=item['id']:raise WorkflowError('Google returned a different message identity; import stopped.')
                conn.execute('BEGIN IMMEDIATE')
                if paused(conn): conn.rollback();raise WorkflowError('Paused during inbox read; saved messages retained.')
                active=conn.execute("SELECT 1 FROM gmail_jobs WHERE id=? AND status='Running' AND token=? AND lease>?",(job['id'],token,time.time())).fetchone()
                if not active:conn.rollback();return True
                if not conn.execute('SELECT 1 FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone():raise WorkflowError('Gmail disconnected while reading; no further data saved.')
                inserted=ingest(conn,owner,message)
                if inserted and account['drafting']:
                    mail=conn.execute('SELECT * FROM gmail_mail WHERE owner_id=? AND external_id=?',(owner,message['id'])).fetchone()
                    if mail['direction']=='incoming' and mail['flow_id'] and not conn.execute('SELECT 1 FROM p5_suppressions WHERE user_id=? AND email=?',(owner,mail['sender'])).fetchone():draft_reply(conn,mail)
                conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE gmail_accounts SET last_sync=?,cursor=?,error=\'\' WHERE owner_id=?',(time.time(),str(result.get('nextPageToken',''))[:2000],owner))
            conn.execute("UPDATE gmail_jobs SET status='Completed',lease=NULL WHERE id=? AND token=?",(job['id'],token));conn.commit()
        except Exception as exc:
            conn.rollback()
            reason=str(exc) if isinstance(exc,WorkflowError) else 'Gmail read failed safely; review configuration and original in Gmail.'
            conn.execute('UPDATE gmail_accounts SET last_sync=?,error=? WHERE owner_id=?',(time.time(),reason,job['owner_id']))
            conn.execute("UPDATE gmail_jobs SET status=?,due=?,lease=NULL,error=? WHERE id=? AND token=?",('Queued' if job['attempts']<2 else 'Failed',time.time()+60,reason,job['id'],token));conn.commit()
        return True


def draft_reply(conn,mail):
    if mail['direction']!='incoming' or not mail['flow_id']: raise WorkflowError('Match an incoming message to an owned opportunity before drafting.')
    if conn.execute('SELECT 1 FROM p5_suppressions WHERE user_id=? AND email=?',(mail['owner_id'],mail['sender'])).fetchone():raise WorkflowError('Suppressed contact; no reply draft generated.')
    analysis=json.loads(mail['intent_json']);original=unseal(mail['content_cipher'])
    if analysis['classification'] in ('opt-out','rejection') or 'concern' in analysis['signals']:
        body='Hi,\n\nThank you for your message. I will personally review your concerns before confirming any next step.\n\nBenji Price | Web Design'
    elif 'pricing' in analysis['signals']:
        packages=json.loads(conn.execute('SELECT package_json FROM p5_flows WHERE id=?',(mail['flow_id'],)).fetchone()[0])
        gst=conn.execute('SELECT gst_mode FROM p5_control WHERE id=1').fetchone()[0]
        lines=[]
        if gst in ('not_registered','registered_10'):
            from sales_quotes import calculate
            for p in packages:
                p=dict(p,quantity=1);total=calculate([p],gst,'Indicative scope only','Existing saved package','')['totals']['one-off']['total_cents']
                if p['cycle']=='one-off': lines.append(f'{p["name"]}: A${total/100:,.2f}'+(' including GST' if gst=='registered_10' else ' (no GST charged)'))
        body='Hi,\n\nThanks for asking about a website. '+('Our current indicative options for this opportunity are:\n'+'\n'.join(lines) if lines else 'I need to confirm the scope and tax treatment before quoting a price.')+'\n\nWhat does your business do, which pages do you need, and do you already have a domain and content? Hosting and domains are separate customer costs. This is not a final quote or commitment.\n\nBenji Price | Web Design'
    else:
        body='Hi,\n\nThanks for your message. What would you like the website to help your customers do, and what pages or changes do you have in mind? I will confirm the scope with you before preparing a quote.\n\nBenji Price | Web Design'
    content=dict(subject=('Re: '+original['subject'].removeprefix('Re: '))[:200],body=body,recipient=mail['sender'],thread_id=mail['thread_id'],
                 in_reply_to=original['message_id'],references=original['references'],source_mail_id=mail['id'],mode='Local template; owner review required')
    conn.execute('INSERT OR IGNORE INTO gmail_drafts(mail_id,owner_id,content_cipher,content_hash,created_at) VALUES(?,?,?,?,?)',(mail['id'],mail['owner_id'],seal(content),sales_store.digest(content),stamp()))
    audit(conn,'gmail_reply_drafted',mail['owner_id'],{'mail_id':mail['id']})


def send_draft(conn,owner,identifier,expected_hash):
    """Exact owner-approved reply only. No automatic retries or cold outreach."""
    if os.environ.get('AGENCYOS_GMAIL_SEND_ENABLED')!='1':raise WorkflowError('Live Gmail sending is disabled. No email request was made.')
    conn.execute('BEGIN IMMEDIATE')
    draft=conn.execute('SELECT d.*,m.flow_id,m.direction FROM gmail_drafts d JOIN gmail_mail m ON m.id=d.mail_id WHERE d.id=? AND d.owner_id=?',(identifier,owner)).fetchone()
    policy=conn.execute('SELECT * FROM gmail_policy WHERE owner_id=?',(owner,)).fetchone()
    if not draft or draft['status']!='Needs review' or not hmac.compare_digest(draft['content_hash'],expected_hash):raise WorkflowError('Exact unmodified draft approval required; no duplicate submission.')
    if not policy or not policy['approved'] or policy['approved_at']<time.time()-30*86400 or not policy['evidence'] or not policy['contact_details'] or paused(conn): raise WorkflowError('Current owner communication policy/contact details and unpaused system required.')
    content=unseal(draft['content_cipher'])
    if sales_store.digest(content)!=draft['content_hash']:raise WorkflowError('Draft integrity failure.')
    from email_preparation import recipient_readiness
    eligible,_reason=recipient_readiness(conn,owner,content['recipient'])
    if not eligible:raise WorkflowError('Current contact permission evidence missing or recipient suppressed.')
    if not content['in_reply_to'] or re.search(r'[\r\n]',content['in_reply_to']+content['subject']+content['references']):raise WorkflowError('Safe reply headers required; inspect original message.')
    count=conn.execute("SELECT COUNT(*) FROM gmail_drafts WHERE owner_id=? AND status IN ('Sending','Sent','Outcome unknown') AND substr(attempted_at,1,10)=?",(owner,stamp()[:10])).fetchone()[0]
    if count>=min(policy['daily_limit'],10): raise WorkflowError('Daily approved reply ceiling reached.')
    conn.execute("UPDATE gmail_drafts SET status='Sending',attempted_at=? WHERE id=?",(stamp(),identifier));conn.commit()
    try:
        token=access_token(conn,owner,sending=True)
        # A token refresh may have yielded to an opt-out, disconnect or pause.
        conn.execute('BEGIN IMMEDIATE')
        if paused(conn) or not conn.execute('SELECT 1 FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone() or not recipient_readiness(conn,owner,content['recipient'])[0]:
            conn.rollback();raise WorkflowError('Communication permissions changed during authorisation.')
        conn.commit()
        message=EmailMessage();message['From']=formataddr((DISPLAY,ACCOUNT));message['To']=sales_email.address(content['recipient'])
        message['Subject']=content['subject'];message['In-Reply-To']=content['in_reply_to']
        message['References']=(content['references']+' '+content['in_reply_to']).strip()
        message['Message-ID']='<agencyos-'+str(identifier)+'-'+draft['content_hash'][:20]+'@gmail.com>'
        message.set_content(content['body']+'\n\n'+policy['contact_details']+'\nIf you do not want further website-service emails, reply “unsubscribe”.')
        receipt=google_request(API+'messages/send',token=token,data=dict(raw=base64.urlsafe_b64encode(message.as_bytes()).decode(),threadId=content['thread_id']))
        if not receipt.get('id') or receipt.get('threadId')!=content['thread_id']:raise WorkflowError('Unexpected Gmail receipt; inspect Sent in Gmail before doing anything else.')
        conn.execute("UPDATE gmail_drafts SET status='Sent',provider_id=? WHERE id=?",(receipt['id'],identifier))
        audit(conn,'gmail_reply_submitted',owner,{'draft_id':identifier,'gmail_id':receipt['id'],'delivery_verified':False});conn.commit()
    except Exception:
        conn.rollback();conn.execute("UPDATE gmail_drafts SET status='Outcome unknown' WHERE id=?",(identifier,));conn.commit()
        raise WorkflowError('Submission outcome unknown. Inspect Gmail Sent manually; no automatic retry is permitted.') from None


def register(app,get_db,login_required):
    def own_mail(identifier):
        row=get_db().execute('SELECT * FROM gmail_mail WHERE id=? AND owner_id=?',(identifier,session['user_id'])).fetchone()
        if not row:abort(404)
        return row

    @app.get('/gmail',strict_slashes=False)
    @login_required
    def gmail_home():
        conn=get_db();owner=session['user_id'];account=conn.execute('SELECT * FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
        mails=[dict(r,content=unseal(r['content_cipher']),analysis=json.loads(r['intent_json'])) for r in conn.execute('SELECT * FROM gmail_mail WHERE owner_id=? ORDER BY id DESC LIMIT 50',(owner,))]
        drafts=[dict(r,content=unseal(r['content_cipher'])) for r in conn.execute('SELECT * FROM gmail_drafts WHERE owner_id=? ORDER BY id DESC LIMIT 50',(owner,))]
        try:client_config();configured=True
        except WorkflowError:configured=False
        return render_template('gmail.html',account=account,mails=mails,drafts=drafts,configured=configured,email=ACCOUNT,
            flows=conn.execute('SELECT * FROM p5_flows WHERE user_id=? ORDER BY id DESC LIMIT 100',(owner,)).fetchall(),
            jobs=conn.execute('SELECT * FROM gmail_jobs WHERE owner_id=? ORDER BY id DESC LIMIT 10',(owner,)).fetchall(),
            policy=conn.execute('SELECT * FROM gmail_policy WHERE owner_id=?',(owner,)).fetchone(),sending=os.environ.get('AGENCYOS_GMAIL_SEND_ENABLED')=='1')

    @app.post('/gmail/client')
    @login_required
    def gmail_client():
        # Filename/path from the browser is never trusted; launcher chooses destination.
        upload=request.files.get('client_json');path=os.environ.get('AGENCYOS_GMAIL_CLIENT_FILE','')
        if not upload or not path:raise WorkflowError('Use the private launcher and select the downloaded Desktop OAuth JSON.')
        try:
            raw=upload.read(20001)
            if len(raw)>20000:raise ValueError()
            config=json.loads(raw)['installed']
            if not isinstance(config['client_id'],str) or not config['client_id'].endswith('.apps.googleusercontent.com') or not isinstance(config['client_secret'],str) or not config['client_secret']:raise ValueError()
        except (ValueError,TypeError,KeyError):raise WorkflowError('Invalid Google Desktop OAuth client file.') from None
        target=Path(path)
        if target.exists():raise WorkflowError('OAuth client already exists. Disconnect and deliberately replace its private local file to change clients.')
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as handle:json.dump({'installed':{k:config[k] for k in ('client_id','client_secret')}},handle)
        flash('Desktop OAuth client saved privately. Gmail is not connected yet.','success');return redirect(url_for('gmail_home'))

    @app.post('/gmail/connect')
    @login_required
    def gmail_connect():
        if request.form.get('confirm')!='yes':raise WorkflowError('Confirm the dedicated account before Google sign-in.')
        session['gmail_oauth_owner']=session['user_id']
        return redirect(begin_oauth(get_db(),session['user_id'],url_for('gmail_callback',_external=True),request.form.get('send_scope')=='yes',request.form.get('draft_scope')=='yes'))

    @app.get('/gmail/oauth/callback')
    @login_required
    def gmail_callback():
        if session.pop('gmail_oauth_owner',None)!=session['user_id']:raise WorkflowError('Start sign-in from this owner session.')
        if request.args.get('error'):raise WorkflowError('Google authorisation declined. Gmail remains disconnected.')
        finish_oauth(get_db(),session['user_id'],request.args.get('state','')[:200],request.args.get('code','')[:4000])
        flash('Dedicated account profile verified with Google. Inbox polling remains off until you enable it.','success');return redirect(url_for('gmail_home'))

    @app.post('/gmail/poll')
    @login_required
    def gmail_poll():
        conn=get_db()
        if paused(conn):raise WorkflowError('Emergency pause active.')
        queue_poll(conn,session['user_id']);conn.commit();return redirect(url_for('gmail_home'))

    @app.post('/gmail/polling')
    @login_required
    def gmail_polling():
        conn=get_db();enabled=request.form.get('enable')=='yes'
        conn.execute('UPDATE gmail_accounts SET polling=?,drafting=? WHERE owner_id=?',(int(enabled),int(request.form.get('drafting')=='yes'),session['user_id']))
        if not enabled:conn.execute("UPDATE gmail_jobs SET status='Cancelled' WHERE owner_id=? AND status IN ('Queued','Running')",(session['user_id'],))
        audit(conn,'gmail_polling_changed',session['user_id'],{'enabled':enabled});conn.commit()
        return redirect(url_for('gmail_home'))

    @app.post('/gmail/disconnect')
    @login_required
    def gmail_disconnect():
        conn=get_db();owner=session['user_id'];row=conn.execute('SELECT * FROM gmail_accounts WHERE owner_id=?',(owner,)).fetchone()
        if request.form.get('revoke')=='yes' and row:
            token=unseal(row['token_cipher'])['refresh_token']
            google_request(REVOKE,data={'token':token},form=True)
        conn.execute('DELETE FROM gmail_accounts WHERE owner_id=?',(owner,));conn.execute('DELETE FROM gmail_oauth WHERE owner_id=?',(owner,))
        conn.execute("UPDATE gmail_jobs SET status='Cancelled' WHERE owner_id=? AND status IN ('Queued','Running')",(owner,));audit(conn,'gmail_disconnected',owner);conn.commit()
        flash('Local tokens removed. Stored correspondence remains. If you did not revoke here, remove AgencyOS access in your Google account.','success');return redirect(url_for('gmail_home'))

    @app.post('/gmail/mail/<int:identifier>/match')
    @login_required
    def gmail_match(identifier):
        conn=get_db();mail=own_mail(identifier);flow=conn.execute('SELECT * FROM p5_flows WHERE id=? AND user_id=?',(request.form.get('flow_id',type=int),session['user_id'])).fetchone()
        if not flow:raise WorkflowError('Select your opportunity; no match was guessed.')
        conn.execute('UPDATE gmail_mail SET flow_id=?,lead_id=? WHERE id=?',(flow['id'],flow['lead_id'],mail['id']))
        if mail['direction']=='incoming':
            conn.execute("UPDATE p5_followups SET status='Stopped' WHERE message_id IN (SELECT id FROM p5_messages WHERE flow_id=?)",(flow['id'],))
            original=unseal(mail['content_cipher'])
            previous=conn.execute('SELECT * FROM p5_messages WHERE flow_id=? AND lower(recipient)=? ORDER BY id DESC LIMIT 1',(flow['id'],mail['sender'])).fetchone()
            if previous:sales_email.apply_event(conn,previous,'gmail','gmail:'+mail['external_id'],'reply',original['body'][:10000],dict(text=original['body'][:10000],gmail_id=mail['external_id'],thread_id=mail['thread_id'],provenance='OAuth mailbox; sender claims untrusted'))
        audit(conn,'gmail_owner_matched',session['user_id'],{'mail_id':identifier,'flow_id':flow['id']});conn.commit();return redirect(url_for('gmail_home'))

    @app.post('/gmail/mail/<int:identifier>/thread')
    @login_required
    def gmail_thread(identifier):
        conn=get_db();mail=own_mail(identifier)
        if paused(conn):raise WorkflowError('Emergency pause active.')
        thread=mail['thread_id']
        if not re.fullmatch('[a-zA-Z0-9_-]{1,200}',thread):raise WorkflowError('Invalid thread identity.')
        token=access_token(conn,session['user_id'])
        result=google_request(API+'threads/'+thread+'?format=full',token=token)
        if result.get('id')!=thread:raise WorkflowError('Google returned a different conversation; no records imported.')
        conn.execute('BEGIN IMMEDIATE')
        if paused(conn) or not conn.execute('SELECT 1 FROM gmail_accounts WHERE owner_id=?',(session['user_id'],)).fetchone():raise WorkflowError('Paused or disconnected during conversation read.')
        for item in result.get('messages',[])[:20]:
            if item.get('threadId')!=thread:raise WorkflowError('Conversation message is outside the authorised thread.')
            ingest(conn,session['user_id'],item)
        audit(conn,'gmail_thread_read',session['user_id'],{'mail_id':identifier,'maximum_messages':20});conn.commit()
        return redirect(url_for('gmail_home'))

    @app.post('/gmail/mail/<int:identifier>/draft')
    @login_required
    def gmail_draft(identifier):
        conn=get_db()
        if paused(conn):raise WorkflowError('Emergency pause active.')
        draft_reply(conn,own_mail(identifier));conn.commit();return redirect(url_for('gmail_home'))

    @app.post('/gmail/drafts/<int:identifier>/edit')
    @login_required
    def gmail_edit(identifier):
        conn=get_db();row=conn.execute('SELECT * FROM gmail_drafts WHERE id=? AND owner_id=?',(identifier,session['user_id'])).fetchone()
        if not row:abort(404)
        if row['status']!='Needs review':raise WorkflowError('Submitted or uncertain messages cannot be edited or resent.')
        content=unseal(row['content_cipher']);subject=request.form.get('subject','').strip();body=request.form.get('body','').strip()
        if not 1<=len(subject)<=200 or not 1<=len(body)<=6000 or any(c in subject for c in '\r\n'):raise WorkflowError('Use a subject up to 200 characters and reply body up to 6,000 characters.')
        content.update(subject=subject,body=body,mode='Owner edited local draft')
        conn.execute('UPDATE gmail_drafts SET content_cipher=?,content_hash=? WHERE id=?',(seal(content),sales_store.digest(content),identifier))
        audit(conn,'gmail_draft_edited',session['user_id'],{'draft_id':identifier});conn.commit();return redirect(url_for('gmail_home'))

    @app.post('/gmail/drafts/<int:identifier>/send')
    @login_required
    def gmail_send(identifier):
        if request.form.get('confirm')!='yes':raise WorkflowError('Exact one-message owner approval required.')
        conn=get_db()
        try:send_draft(conn,session['user_id'],identifier,request.form.get('content_hash',''))
        finally:
            if conn.in_transaction:conn.rollback()
        return redirect(url_for('gmail_home'))

    @app.post('/gmail/policy')
    @login_required
    def gmail_policy():
        evidence=request.form.get('evidence','').strip();contact=request.form.get('contact_details','').strip();limit=request.form.get('daily_limit',type=int)
        if not 10<=len(evidence)<=1000 or not 5<=len(contact)<=500 or limit is None or not 1<=limit<=10 or request.form.get('confirm')!='yes':raise WorkflowError('Record your actual policy review, contact details, a 1–10 daily ceiling and explicit approval. This does not enable sending.')
        conn=get_db();conn.execute('INSERT INTO gmail_policy VALUES(?,1,?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET approved=1,evidence=excluded.evidence,contact_details=excluded.contact_details,daily_limit=excluded.daily_limit,approved_at=excluded.approved_at',(session['user_id'],evidence,contact,limit,time.time()))
        audit(conn,'gmail_policy_reviewed',session['user_id']);conn.commit();return redirect(url_for('gmail_home'))

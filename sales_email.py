"""Mock-first email boundary. No live sending implementation is installed."""
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from typing import Protocol
from phase3_store import WorkflowError, stamp
from phase4_store import paused
from sales_store import digest, dumps, enqueue, log


def address(value):
    value=value.strip().casefold()
    if len(value)>254 or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+',value):
        raise WorkflowError('Use a plain email address without display names or header characters.')
    return value


def readiness(config):
    return dict(provider=config['provider'],sender_configured=bool(config['sender']),
                checks=dict(sender_address='configured' if config['sender'] else 'missing',
                            spf='not checked',dkim='not checked',dmarc='not checked',
                            provider_permission='unverified',legal_and_consent_review='not established',live_adapter='not installed'),
                sender_authentication='Not independently verified; mock mode does not perform DNS checks',
                live_sending=False,reason='No live adapter. Provider terms, consent/privacy review, authenticated sender and separate activation remain prerequisites.')


def message_hash(message,config):
    return digest([message['recipient'],message['sender'],message['subject'],message['body'],message['draft_id'],message['quote_id'],config['provider'],config['sender']])


def suppress(conn,user_id,email,reason):
    email=address(email)
    conn.execute('INSERT OR IGNORE INTO p5_suppressions(user_id,email,reason,created_at) VALUES(?,?,?,?)',(user_id,email,reason,stamp()))
    conn.execute("UPDATE p5_followups SET status='Stopped' WHERE message_id IN (SELECT m.id FROM p5_messages m JOIN p5_flows f ON f.id=m.flow_id WHERE f.user_id=? AND m.recipient=?)",(user_id,email))
    conn.execute("UPDATE p5_flows SET follow_state='Suppressed' WHERE id IN (SELECT flow_id FROM p5_messages WHERE recipient=?) AND user_id=?",(email,user_id))
    log(conn,user_id,'Suppressed recipient; reason: '+reason[:200])


def opted_out(text):
    return bool(re.search(r'\b(unsubscribe|remove me|stop emailing|do not contact|don.t contact|stop contacting)\b',text.casefold()))


def eligibility(conn,message,followup=False):
    flow=conn.execute('SELECT * FROM p5_flows WHERE id=?',(message['flow_id'],)).fetchone()
    if flow['state']=='Cancelled' or paused(conn):
        return False,'Cancelled or emergency pause active.'
    if conn.execute('SELECT 1 FROM p5_suppressions WHERE user_id=? AND email=?',(flow['user_id'],address(message['recipient']))).fetchone():
        return False,'Recipient suppressed.'
    if followup:
        if flow['follow_state'] in ('Suppressed','Reply awaiting owner review','Stopped after response','Stopped'):
            return False,'Workflow follow-ups stopped after a response or owner action.'
        if message['status'] not in ('Mock accepted','Mock delivered'):
            return False,'No confirmed mock acceptance; delivery/real sending not established.'
        if conn.execute("SELECT 1 FROM p5_events WHERE message_id=? AND kind IN ('reply','bounce','complaint','unsubscribe')",(message['id'],)).fetchone():
            return False,'Response/bounce/complaint/opt-out stops follow-up eligibility.'
    return True,'Eligible for internal review only; not permission to send.'


class EmailProvider(Protocol):
    def submit(self,message:dict,idempotency_key:str)->dict: ...


class MockEmailProvider:
    """Contract fixture: records acceptance, never sends email or claims delivery."""
    def submit(self,message,idempotency_key):
        return dict(id='mock:'+idempotency_key,status='Mock accepted',provenance='Mock provider; no email sent')


def dispatch(conn,job):
    payload=json.loads(job['payload_json'])
    conn.execute('BEGIN IMMEDIATE')
    message=conn.execute('SELECT * FROM p5_messages WHERE id=?',(payload['message_id'],)).fetchone()
    config=conn.execute('SELECT * FROM p5_control WHERE id=1').fetchone()
    flow=conn.execute('SELECT * FROM p5_flows WHERE id=?',(message['flow_id'],)).fetchone()
    valid,reason=eligibility(conn,message)
    if not valid:
        raise WorkflowError(reason)
    if config['provider']!='mock' or not flow['synthetic']:
        raise WorkflowError('Live sending is disabled. Mock dispatch requires an explicitly fictional workflow.')
    domain=address(message['recipient']).split('@')[1]
    if domain not in ('example.com','example.org','example.net') and not domain.endswith(('.test','.invalid','.example')):
        raise WorkflowError('Mock delivery requires a reserved fictional email domain.')
    if not config['sender'] or message['sender']!=config['sender'] or message['status']!='Approved' or message['approval_expires']<time.time() or message['approval_hash']!=message_hash(message,config):
        raise WorkflowError('Exact recipient/content/sender approval missing, expired or changed.')
    if message['draft_id']:
        draft=conn.execute('SELECT * FROM p5_drafts WHERE id=?',(message['draft_id'],)).fetchone()
        latest=conn.execute('SELECT MAX(version) FROM p5_drafts WHERE flow_id=? AND kind=?',(flow['id'],draft['kind'])).fetchone()[0]
        if draft['version']!=latest or draft['status']!='Approved':
            raise WorkflowError('A revised or unapproved draft cannot be dispatched.')
        if conn.execute("SELECT 1 FROM p5_jobs WHERE flow_id=? AND kind=? AND status IN ('Queued','Running','Awaiting approval')",(flow['id'],draft['kind'])).fetchone():
            raise WorkflowError('A draft revision is pending; dispatch blocked.')
    if message['quote_id']:
        quote=conn.execute('SELECT * FROM p5_quotes WHERE id=?',(message['quote_id'],)).fetchone()
        latest=conn.execute('SELECT MAX(version) FROM p5_quotes WHERE flow_id=?',(flow['id'],)).fetchone()[0]
        if quote['version']!=latest or quote['status']!='Approved' or conn.execute("SELECT 1 FROM p5_jobs WHERE flow_id=? AND kind IN ('quote','proposal') AND status IN ('Queued','Running','Awaiting approval')",(flow['id'],)).fetchone():
            raise WorkflowError('Quote is revised, accepted or not approved; dispatch blocked.')
    recent=conn.execute('''SELECT m.* FROM p5_messages m JOIN p5_flows f ON f.id=m.flow_id
      WHERE f.user_id=? AND m.recipient=? AND m.id!=? AND
      (m.status IN ('Dispatching','Outcome unknown') OR m.dispatched_at>=?)''',
      (flow['user_id'],message['recipient'],message['id'],stamp()[:10])).fetchall()
    if recent:
        raise WorkflowError('Another contact attempt exists for this recipient today or has an uncertain outcome. No duplicate contact.')
    count=conn.execute('''SELECT COUNT(*) FROM p5_messages m JOIN p5_flows f ON f.id=m.flow_id
      WHERE f.user_id=? AND m.dispatched_at>=?''',(flow['user_id'],stamp()[:10])).fetchone()[0]
    if count>=10:
        raise WorkflowError('Daily mock dispatch ceiling (10) reached.')
    conn.execute("UPDATE p5_messages SET status='Dispatching',dispatched_at=? WHERE id=?",(stamp(),message['id']))
    conn.commit()
    # A crash after this point leaves an uncertain outcome, never an automatic resend.
    try:
        receipt=MockEmailProvider().submit(dict(message),'message-'+str(message['id']))
    except Exception:
        conn.execute("UPDATE p5_messages SET status='Outcome unknown' WHERE id=?",(message['id'],))
        conn.commit()
        raise WorkflowError('Provider outcome unknown; check history before any replacement. No automatic resend.') from None
    if not isinstance(receipt,dict) or receipt.get('status')!='Mock accepted' or not isinstance(receipt.get('id'),str) or not receipt['id'].startswith('mock:'):
        conn.execute("UPDATE p5_messages SET status='Outcome unknown' WHERE id=?",(message['id'],))
        conn.commit()
        raise WorkflowError('Unexpected provider receipt; review uncertain outcome.')
    conn.execute("UPDATE p5_messages SET status='Mock accepted',provider_id=? WHERE id=?",(receipt['id'],message['id']))
    log(conn,flow['user_id'],'Mock provider accepted message; no email sent and delivery not established.',flow['id'],job['id'])
    conn.commit()
    return receipt


def apply_event(conn,message,provider,event_id,kind,text='',original=None):
    if kind not in ('reply','delivered','bounce','complaint','unsubscribe') or not isinstance(text,str) or len(text)>10000 or not isinstance(event_id,str) or not 1<=len(event_id)<=200:
        raise WorkflowError('Invalid email event type, ID or message size.')
    original=original or dict(type=kind,text=text,event_id=event_id)
    hashed=digest(original)
    existing=conn.execute('SELECT * FROM p5_events WHERE provider=? AND external_id=?',(provider,event_id)).fetchone()
    if existing:
        if existing['payload_hash']!=hashed or existing['message_id']!=message['id']:
            raise WorkflowError('Event ID reused with changed content; rejected.')
        return existing['id'],False
    flow=conn.execute('SELECT * FROM p5_flows WHERE id=?',(message['flow_id'],)).fetchone()
    identifier=conn.execute('INSERT INTO p5_events(message_id,provider,external_id,kind,original_json,payload_hash,received_at) VALUES(?,?,?,?,?,?,?)',
                            (message['id'],provider,event_id,kind,dumps(original),hashed,stamp())).lastrowid
    if kind in ('bounce','complaint','unsubscribe') or (kind=='reply' and opted_out(text)):
        suppress(conn,flow['user_id'],message['recipient'],provider+': '+kind+(' with opt-out language' if kind=='reply' else ''))
        if provider=='mock':
            conn.execute('UPDATE p5_messages SET status=? WHERE id=?',('Mock '+kind,message['id']))
    elif kind=='reply':
        conn.execute("UPDATE p5_followups SET status='Stopped' WHERE message_id IN (SELECT id FROM p5_messages WHERE flow_id=?)",(flow['id'],))
        conn.execute("UPDATE p5_flows SET follow_state='Reply awaiting owner review' WHERE id=?",(flow['id'],))
    elif kind=='delivered' and provider=='mock' and message['status']=='Mock accepted':
        conn.execute("UPDATE p5_messages SET status='Mock delivered' WHERE id=?",(message['id'],))
    if kind=='reply':
        reply_evidence=[dict(id=identifier,source_url='message:'+str(message['id']),observed_at=stamp(),origin=provider,facts=dict(original=text))]
        try:
            enqueue(conn,flow['id'],'classify',dict(event_id=identifier,original=text,provenance=provider,evidence=reply_evidence),key='classify-event-'+str(identifier))
        except WorkflowError:
            # Queue pressure must never roll back opt-outs, original replies or suppression.
            log(conn,flow['user_id'],'Reply classification deferred: queue full. Original event and suppression retained; owner attention required.',flow['id'])
    log(conn,flow['user_id'],'Recorded '+kind+' event ('+provider+'); original preserved.',flow['id'])
    return identifier,True


def verify_event(raw,signature):
    secret=os.environ.get('AGENCYOS_EMAIL_EVENT_SECRET','')
    if len(secret)<32:
        raise WorkflowError('Configure an event signing secret of at least 32 characters outside Git. No event accepted.')
    if len(raw)>20000 or not re.fullmatch('[0-9a-f]{64}',signature) or not hmac.compare_digest(hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest(),signature):
        raise WorkflowError('Email event signature invalid.')
    try:
        event=json.loads(raw)
        if type(event.get('timestamp')) is not int or abs(time.time()-event['timestamp'])>300:
            raise ValueError()
        if set(event)-{'timestamp','event_id','provider_id','type','text'}:
            raise ValueError()
        if not isinstance(event['provider_id'],str) or not event['provider_id'].startswith('mock:'):
            raise ValueError()
        return event
    except (ValueError,KeyError,TypeError,AttributeError):
        raise WorkflowError('Invalid or expired mock email event envelope.') from None

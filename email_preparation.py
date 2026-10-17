"""Sender verification and SES simulator contracts. No live recipient transport."""
import base64
import hashlib
import json
import re
import secrets
import time
from datetime import date,datetime,timezone
from email.message import EmailMessage
from urllib.parse import urlsplit
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from flask import request,render_template_string
from phase3_store import WorkflowError
from sales_email import address,suppress

DOMAIN=re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')
SIMULATORS={'success','bounce','complaint','ooto','suppressionlist'}


def migrate(conn):
    conn.executescript('''CREATE TABLE IF NOT EXISTS prep_sender_checks (
      id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,domain TEXT NOT NULL,checks_json TEXT NOT NULL,observed_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS prep_unsubscribe (
      token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,email TEXT NOT NULL,expires_at REAL NOT NULL);
    ''')


def check_sender(domain,identity,dns_lookup,now=None):
    """Uses supplied provider/DNS responses; caller must label fixture versus real evidence."""
    domain=domain.casefold()
    if not DOMAIN.fullmatch(domain):raise WorkflowError('Use a plain sender domain.')
    dkim=identity.get('DkimAttributes',{})
    mail=identity.get('MailFromAttributes',{})
    maildomain=mail.get('MailFromDomain','')
    if maildomain and not (maildomain==domain or maildomain.endswith('.'+domain)):raise WorkflowError('MAIL FROM domain does not match the sender.')
    spf=dns_lookup(maildomain,'TXT') if maildomain else []
    spf_records=[str(v).strip('"') for v in spf if str(v).strip('"').startswith('v=spf1')]
    dmarc=[str(v).strip('"') for v in dns_lookup('_dmarc.'+domain,'TXT') if str(v).strip('"').startswith('v=DMARC1;')]
    tokens=dkim.get('Tokens',[])
    if not isinstance(tokens,list) or any(not re.fullmatch('[a-z0-9]{1,100}',str(t)) for t in tokens):raise WorkflowError('Invalid provider DKIM tokens.')
    checks=dict(provider_identity=identity.get('VerificationStatus')=='SUCCESS',
        spf=len(spf_records)==1 and 'include:amazonses.com' in spf_records[0].split(),
        dkim=bool(tokens) and dkim.get('Status')=='SUCCESS' and all(str(t)+'.dkim.amazonses.com' in [str(v).rstrip('.') for v in dns_lookup(str(t)+'._domainkey.'+domain,'CNAME')] for t in tokens),
        dmarc=len(dmarc)==1 and bool(re.search(r'(?:^|;)\s*p=(quarantine|reject)(?:;|$)',dmarc[0])),
        mail_from=mail.get('MailFromDomainStatus')=='SUCCESS')
    return dict(domain=domain,checks=checks,ready=all(checks.values()),observed_at=now or time.time(),
                note='DNS/provider authentication evidence is separate from recipient consent and sending approval.')


def recipient_readiness(conn,user_id,recipient,now=None):
    recipient=address(recipient);now=now or time.time()
    if conn.execute('SELECT 1 FROM p5_suppressions WHERE user_id=? AND email=?',(user_id,recipient)).fetchone():return False,'Suppressed'
    basis=conn.execute('SELECT * FROM p5_contact_basis WHERE user_id=? AND email=?',(user_id,recipient)).fetchone()
    if not basis or basis['basis_type']!='consent' or not basis['evidence_reference']:
        return False,'Current explicit consent evidence is required by this conservative pilot policy.'
    if basis['expires_on'] and basis['expires_on']<datetime.fromtimestamp(now,timezone.utc).date().isoformat():return False,'Evidence expired'
    return True,'Owner-attested evidence present; legal/provider approval remains separate.'


def unsubscribe_token(conn,user_id,recipient,now=None):
    token=secrets.token_urlsafe(32)
    conn.execute('INSERT INTO prep_unsubscribe VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user_id,address(recipient),(now or time.time())+90*86400))
    return token


def commercial_mime(message,unsubscribe_url,business_identity):
    sender=address(message['sender']);recipient=address(message['recipient'])
    if not business_identity.strip() or len(business_identity)>500:raise WorkflowError('Approved sender identity/contact details are required.')
    parts=urlsplit(unsubscribe_url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or any(c in unsubscribe_url for c in '\r\n'):
        raise WorkflowError('An HTTPS unsubscribe URL is required.')
    if '\r' in message['subject'] or '\n' in message['subject']:raise WorkflowError('Subject header injection blocked')
    mail=EmailMessage();mail['From']=sender;mail['To']=recipient;mail['Subject']=message['subject']
    mail['List-Unsubscribe']='<'+unsubscribe_url+'>';mail['List-Unsubscribe-Post']='List-Unsubscribe=One-Click'
    mail.set_content(message['body']+'\n\n'+business_identity+'\nUnsubscribe: '+unsubscribe_url)
    return mail.as_bytes()


class SesSimulatorAdapter:
    """SDK client is injected. Explicit sandbox permission and simulator-only destinations."""
    def __init__(self,client,region='ap-southeast-2',allow_sandbox_requests=False):
        self.client=client;self.region=region;self.allowed=allow_sandbox_requests

    def submit(self,message,sender_check,unsubscribe_url,business_identity):
        recipient=address(message['recipient'])
        local,domain=recipient.split('@')
        if not self.allowed or self.region!='ap-southeast-2' or domain!='simulator.amazonses.com' or local not in SIMULATORS:
            raise WorkflowError('Only separately approved SES simulator requests are supported; real recipients are blocked.')
        if not sender_check.get('ready') or time.time()-sender_check.get('observed_at',0)>86400 or sender_check.get('observed_at',0)>time.time()+60 or address(message['sender']).split('@')[1]!=sender_check.get('domain'):
            raise WorkflowError('A current matching sender authentication check is required.')
        raw=commercial_mime(message,unsubscribe_url,business_identity)
        # SES has no general SendEmail idempotency token. Never auto-retry an uncertain submission.
        result=self.client.send_email(FromEmailAddress=address(message['sender']),Destination={'ToAddresses':[recipient]},Content={'Raw':{'Data':raw}})
        if not isinstance(result.get('MessageId'),str):raise WorkflowError('SES simulator outcome unknown; never automatically retry.')
        return dict(provider_id=result['MessageId'],status='SES simulator accepted',live=False)


def verify_sns(envelope,allowed_topic,certificate_loader,now=None):
    """Pure SNS v2 Notification verification with an injected bounded HTTPS certificate loader."""
    if not isinstance(envelope,dict) or len(json.dumps(envelope).encode())>300000:raise WorkflowError('SNS envelope exceeds the supported bound')
    if envelope.get('Type')!='Notification' or envelope.get('TopicArn')!=allowed_topic or envelope.get('SignatureVersion')!='2':raise WorkflowError('SNS topic/type/signature version rejected')
    parts=urlsplit(envelope.get('SigningCertURL',''))
    if parts.scheme!='https' or parts.netloc!='sns.ap-southeast-2.amazonaws.com' or parts.query or parts.fragment or not re.fullmatch(r'/SimpleNotificationService-[a-zA-Z0-9_-]+\.pem',parts.path):raise WorkflowError('SNS certificate destination rejected')
    current=datetime.fromtimestamp(now or time.time(),timezone.utc)
    try:
        observed=datetime.fromisoformat(envelope['Timestamp'].replace('Z','+00:00'))
        if abs((current-observed).total_seconds())>300:raise ValueError('stale')
        fields=['Message','MessageId']+(['Subject'] if 'Subject' in envelope else [])+['Timestamp','TopicArn','Type']
        canonical=''.join(key+'\n'+envelope[key]+'\n' for key in fields).encode()
        pem=certificate_loader(envelope['SigningCertURL'])
        if len(pem)>20000:raise ValueError('certificate size')
        cert=x509.load_pem_x509_certificate(pem)
        if not cert.not_valid_before_utc<=current<=cert.not_valid_after_utc:raise ValueError('certificate expired')
        cert.public_key().verify(base64.b64decode(envelope['Signature'],validate=True),canonical,padding.PKCS1v15(),hashes.SHA256())
        message=json.loads(envelope['Message'])
        if not isinstance(message,dict):raise ValueError('message')
        return message
    except Exception as exc:raise WorkflowError('SNS notification verification failed') from None


def register(app,get_db):
    @app.route('/unsubscribe/<token>',methods=['GET','POST'])
    def unsubscribe(token):
        if request.method=='POST':
            conn=get_db();conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM prep_unsubscribe WHERE token_hash=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if row:suppress(conn,row['user_id'],row['email'],'Recipient used unsubscribe endpoint')
            conn.commit()
            return 'Your request has been processed. No login is required.',200
        return render_template_string('<!doctype html><html lang="en"><title>Unsubscribe</title><h1>Stop marketing messages</h1><form method="post"><button>Unsubscribe</button></form></html>')

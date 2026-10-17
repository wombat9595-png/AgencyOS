"""Opt-in, one-page inspection with DNS pinning, robots checks and no redirects."""
import hashlib
import http.client
import ipaddress
import os
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from phase3_store import WorkflowError

class FactsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[];self.h1=[];self.text=[];self.description='';self.lang='';self.in_title=False;self.in_h1=False;self.hidden=0
    def handle_starttag(self,tag,attrs):
        attrs={key:(value or '') for key,value in attrs}
        if tag in ('script','style','noscript'):self.hidden+=1
        if tag=='title':self.in_title=True
        if tag=='h1':self.in_h1=True
        if tag=='html':self.lang=attrs.get('lang','')[:80]
        if tag=='meta' and attrs.get('name','').lower()=='description':self.description=attrs.get('content','')[:500]
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'):self.hidden=max(0,self.hidden-1)
        if tag=='title':self.in_title=False
        if tag=='h1':self.in_h1=False
    def handle_data(self,data):
        if self.hidden:return
        if self.in_title:self.title.append(data)
        if self.in_h1:self.h1.append(data)
        self.text.append(data)

def normalise_origin(url):
    try:
        if not isinstance(url,str) or any(ord(c)<33 for c in url) or '\\' in url:raise ValueError()
        parts=urlsplit(url)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.port not in (None,443):raise ValueError()
        host=parts.hostname.encode('idna').decode('ascii')
        if any(c.isspace() for c in host):raise ValueError()
        return 'https://'+('['+host+']' if ':' in host else host)
    except (ValueError,UnicodeError):raise WorkflowError('Website inspection requires a public HTTPS website without credentials or a custom port.') from None

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):
        super().__init__(host,timeout=timeout,context=ssl.create_default_context())
        self.address=address
    def connect(self):
        raw=socket.create_connection((self.address,443),self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:
            raw.close();raise

def public_get(url, maximum, allowed_type):
    if any(os.environ.get(name) for name in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')):
        raise WorkflowError('Website inspection is disabled with an outbound proxy because destination pinning cannot be guaranteed. Use owner-supplied evidence or a supported direct network.')
    origin=normalise_origin(url);host=urlsplit(origin).hostname
    try:
        addresses={item[4][0] for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise WorkflowError('Private, loopback, reserved and internal network addresses cannot be inspected.')
        deadline=time.monotonic()+15
        # Connect directly to the validated IP while retaining certificate/hostname verification.
        conn=PinnedHTTPS(host,sorted(addresses)[0],15)
        try:
            path=urlsplit(url).path or '/'
            conn.request('GET',path,headers={'User-Agent':'AgencyOSResearch/3.0','Accept':allowed_type,'Accept-Encoding':'identity'})
            response=conn.getresponse()
            if 300<=response.status<400:raise WorkflowError('Website redirected. No redirect was followed; review the destination manually.')
            if response.getheader('Content-Encoding','identity').lower() not in ('','identity'):
                raise WorkflowError('Compressed website responses are unsupported; no HTML findings can be made.')
            content_type=response.getheader('Content-Type','').split(';')[0].lower()
            if response.status==200 and content_type not in allowed_type.split(','):
                raise WorkflowError('The inspected response is not a supported text document.')
            parts=[];total=0
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise WorkflowError('Website inspection exceeded its time limit.')
                if conn.sock:conn.sock.settimeout(remaining)
                chunk=response.read1(min(8192,maximum+1-total))
                if not chunk:break
                parts.append(chunk);total+=len(chunk)
                if total>maximum:raise WorkflowError('Website document exceeds the inspection size limit.')
            return response.status,b''.join(parts)
        finally:conn.close()
    except WorkflowError:raise
    except (OSError,ValueError,http.client.HTTPException):
        raise WorkflowError('Website inspection failed. This is not evidence of a problem with the business website.') from None

def inspect(url):
    if os.environ.get('AGENCYOS_WEBSITE_FETCH')!='1':
        raise WorkflowError('Live website inspection is disabled. Set AGENCYOS_WEBSITE_FETCH=1 only after confirming authorised use. Manual evidence remains available.')
    origin=normalise_origin(url)
    status,robots=public_get(origin+'/robots.txt',65536,'text/plain,text/html')
    if status==200:
        parser=RobotFileParser();parser.parse(robots.decode('utf-8','replace').splitlines())
        delay=parser.crawl_delay('AgencyOSResearch')
        if not parser.can_fetch('AgencyOSResearch',origin+'/') or (delay and delay>2):
            raise WorkflowError('Robots policy blocks this inspection or requires a longer crawl interval. No website content was fetched.')
        if delay:time.sleep(delay)
    elif status not in (404,410):
        raise WorkflowError('Robots permissions could not be established. No website content was fetched.')
    status,body=public_get(origin+'/',524288,'text/html,application/xhtml+xml')
    if status!=200:raise WorkflowError(f'Website returned HTTP {status}. No website-quality claim can be made from this response.')
    parser=FactsParser();parser.feed(body.decode('utf-8','replace'))
    facts=dict(title=' '.join(parser.title)[:500],h1=' '.join(parser.h1)[:1000],
               meta_description=parser.description,html_language=parser.lang,
               visible_excerpt=' '.join(' '.join(parser.text).split())[:5000],
               scope='One HTTPS homepage, static HTML only. Robots checked. No JavaScript, speed, accessibility or whole-site audit performed.')
    return dict(source_url=origin+'/',facts=facts,content_hash=hashlib.sha256(body).hexdigest())

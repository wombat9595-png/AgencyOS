"""Deterministic, authorised static-HTML audit. No AI, scripts or remote assets execute."""
import hashlib
import os
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from phase3_store import WorkflowError, stamp
from website_evidence import normalise_origin, public_get, FactsParser


class AuditParser(FactsParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.viewport = ''
        self.contact_links = []
        self.base_href = None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = {key:(value or '') for key,value in attrs}
        if tag == 'base' and self.base_href is None and 'href' in attrs:
            self.base_href = attrs['href'][:2048]
        if tag == 'meta' and attrs.get('name', '').lower() == 'viewport':
            self.viewport = attrs.get('content', '')[:500]
        if tag == 'a' and len(self.links) < 500:
            href = attrs.get('href', '')
            if href.lower().startswith(('mailto:', 'tel:')):
                self.contact_links.append(href[:254])
            self.links.append(href[:2048])


def audit_url(value):
    if not isinstance(value, str) or len(value)>2048 or any(ord(c)<33 for c in value) or '\\' in value:
        raise WorkflowError('Audit URL contains invalid characters or exceeds 2,048 characters.')
    origin = normalise_origin(value)
    parts = urlsplit(value)
    if parts.query or parts.fragment:
        raise WorkflowError('Audit URLs must not contain query strings or fragments.')
    return origin+(parts.path or '/')


def context():
    return 'audit-v1;fetch='+os.environ.get('AGENCYOS_WEBSITE_FETCH', '')+';max_pages=6;max_requests=7'


def audit(url, before_request=lambda: None):
    if os.environ.get('AGENCYOS_WEBSITE_FETCH') != '1':
        raise WorkflowError('Live audits are disabled. Authorisation and AGENCYOS_WEBSITE_FETCH=1 are required.')
    url = audit_url(url)
    origin = normalise_origin(url)
    report = dict(url=url, observed_at=stamp(), observations=[], findings=[], recommendations=[],
                  unchecked=[], pages=[], requests=0,
                  limitations='At most six static HTML pages on one HTTPS origin; no redirects, query URLs, external links, JavaScript, performance or complete accessibility test. Absence from inspected HTML is not proof of absence from the business. TLS/network failures are not proof the site is down.')
    started = time.monotonic()
    last_request = None

    def fetch(target, maximum, types):
        nonlocal last_request
        if time.monotonic()-started > 120 or report['requests'] >= 7:
            raise WorkflowError('Audit time/request ceiling reached.')
        # Conservative inter-request pacing; stricter robots directives gate below.
        if last_request is not None:
            time.sleep(max(0, 1-(time.monotonic()-last_request)))
        before_request()
        report['requests'] += 1
        last_request = time.monotonic()
        return public_get(target, maximum, types)

    status, body = fetch(origin+'/robots.txt', 65536, 'text/plain,text/html')
    robots = RobotFileParser()
    if status == 200:
        robots.parse(body.decode('utf-8', 'replace').splitlines())
        delay = robots.crawl_delay('AgencyOSResearch')
        rate = robots.request_rate('AgencyOSResearch')
        if (delay and delay>1) or (rate and (rate.requests<=0 or rate.seconds/rate.requests>1)):
            raise WorkflowError('Robots requests a slower crawl than this audit supports; no pages fetched.')
    elif status in (404,410):
        robots.parse(['User-agent: *', 'Allow: /'])
    else:
        raise WorkflowError('Robots permission could not be established; no pages fetched.')
    report['observations'].append(dict(url=origin+'/robots.txt', http_status=status, observed_at=stamp(), scope='Robots response; not a legal permission grant'))
    targets = [url]
    seen = {url}
    for target in targets:
        if not robots.can_fetch('AgencyOSResearch', target):
            report['unchecked'].append(dict(url=target, reason='Robots disallows this path'))
            continue
        try:
            status, body = fetch(target, 524288, 'text/html,application/xhtml+xml')
        except WorkflowError as exc:
            report['unchecked'].append(dict(url=target, reason=str(exc)))
            continue
        observation = dict(url=target, http_status=status, observed_at=stamp(), sha256=hashlib.sha256(body).hexdigest())
        report['observations'].append(observation)
        if status != 200:
            if status in (404,410):
                report['findings'].append(dict(code='http-not-found', url=target, evidence=observation, detail=f'This requested URL returned HTTP {status}.'))
            else:
                report['unchecked'].append(dict(url=target, reason=f'HTTP {status}; HTML checks not performed. Not proof of whole-site unavailability.'))
            continue
        parser = AuditParser()
        parser.feed(body.decode('utf-8','replace'))
        facts = dict(url=target, title=' '.join(parser.title)[:500], meta_description=parser.description,
                     h1=' '.join(parser.h1)[:500], viewport=parser.viewport,
                     contact_links=parser.contact_links[:20], html_language=parser.lang)
        report['pages'].append(facts)
        report['observations'].append(dict(url=target, observed_at=observation['observed_at'], detail='HTTPS response received with certificate and hostname verification.'))
        for field in ('title','meta_description','viewport'):
            if not facts[field].strip():
                report['findings'].append(dict(code='missing-'+field, url=target, evidence=observation,
                                              detail=field+' was empty or absent in this retrieved HTML document.'))
                report['recommendations'].append(dict(url=target, detail='Review an appropriate '+field.replace('_',' ')+'. No traffic or revenue impact was measured.'))
        if not parser.contact_links:
            report['observations'].append(dict(url=target, detail='No mailto: or tel: anchor found in this HTML; contact forms, plain text, images and other pages may contain contact information.'))
        # One-hop link check only, same origin, no query URLs or downloads.
        if target == url:
            skipped = 0
            for href in parser.links:
                if not href or href.startswith(('#','mailto:','tel:')):
                    continue
                try:
                    base = urljoin(target, parser.base_href) if parser.base_href is not None else target
                    joined = urljoin(base, href)
                    parts = urlsplit(joined)
                    if parts.query or parts.scheme != 'https' or normalise_origin(joined) != origin:
                        skipped += 1
                        continue
                    linked = audit_url(urlunsplit((parts.scheme,parts.netloc,parts.path,'','')))
                    suffix = parts.path.rsplit('/',1)[-1]
                    if '.' in suffix and not suffix.lower().endswith(('.html','.htm')):
                        skipped += 1
                        continue
                except (WorkflowError, ValueError):
                    skipped += 1
                    continue
                if linked not in seen:
                    seen.add(linked)
                    if len(targets)<6:
                        targets.append(linked)
                    else:
                        skipped += 1
            report['unchecked'].append(dict(url=target, reason=f'{skipped} links excluded by scope or page limit. Only selected same-origin HTML paths were checked.'))
    if not report['pages']:
        report['unchecked'].append(dict(url=url, reason='No successful HTML page; metadata, viewport and contact checks unavailable.'))
    return report

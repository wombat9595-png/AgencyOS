"""Bounded local website generation, versioning, isolated preview and QA.

Only deterministic templates are emitted. Brief text is escaped as data; no
generated Python or JavaScript is executed by AgencyOS.
"""
from html import escape
from html.parser import HTMLParser
import json
import re
import time
from flask import abort, redirect, render_template, request, session, url_for
from phase3_store import WorkflowError, stamp
import sales_store as store
from static_safety import static_errors

THEMES = {
    'coastal': dict(label='Coastal', ink='#17324d', accent='#197a78', paper='#f4f8f7', muted='#536b73'),
    'earth': dict(label='Earth', ink='#302b25', accent='#a45c35', paper='#fbf7f1', muted='#6d655b'),
    'studio': dict(label='Studio', ink='#241d32', accent='#6750a4', paper='#f8f6fb', muted='#655b74'),
}
MAX_REVISION = 1000


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS p6_sites (
      id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id),
      brief_id INTEGER NOT NULL REFERENCES p5_project_briefs(id), owner_id INTEGER NOT NULL REFERENCES users(id),
      status TEXT NOT NULL DEFAULT 'Queued', active_version INTEGER NOT NULL DEFAULT 0,
      generation_authorized_at TEXT NOT NULL, approved_at TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS p6_site_versions (
      id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL REFERENCES p6_sites(id), version INTEGER NOT NULL,
      theme TEXT NOT NULL, content_json TEXT NOT NULL, html TEXT NOT NULL, pages_json TEXT NOT NULL DEFAULT '{}', qa_json TEXT NOT NULL,
      revision_note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Needs review', created_at TEXT NOT NULL,
      UNIQUE(site_id,version));
    CREATE INDEX IF NOT EXISTS p6_site_versions_site_idx ON p6_site_versions(site_id,version DESC);
    ''')
    columns={row[1] for row in conn.execute('PRAGMA table_info(p6_site_versions)')}
    if 'pages_json' not in columns:
        conn.execute("ALTER TABLE p6_site_versions ADD COLUMN pages_json TEXT NOT NULL DEFAULT '{}'")
    for identifier, name, description in (
        ('website-builder', 'Website Builder Agent', 'Creates safe, versioned static websites from accepted project briefs.'),
        ('website-qa', 'Website QA Agent', 'Checks generated pages, navigation, forms, accessibility, SEO, claims and scope.'),
    ):
        conn.execute("INSERT OR IGNORE INTO agents(id,name,description,availability,enabled) VALUES(?,?,?,'available',1)", (identifier, name, description))
    conn.execute("UPDATE agents SET name='Website Builder Agent',description='Creates safe, versioned static websites from accepted project briefs.',availability='available',enabled=1 WHERE id='website-builder'")


def _source(payload):
    """Validate the exact accepted brief snapshot before building."""
    brief = payload.get('brief')
    if not isinstance(brief, dict) or brief.get('schema_version') not in (1, 2):
        raise WorkflowError('Website generation requires a saved Phase 5 project brief.')
    if not brief.get('quote_hash') or not isinstance(brief.get('quote'), dict):
        raise WorkflowError('Project brief is missing its accepted quote snapshot.')
    if not brief.get('requirements_source') or not brief.get('requirements'):
        raise WorkflowError('Project brief must include owner-recorded requirements and their source.')
    project = payload.get('project')
    if not isinstance(project, dict) or not project.get('client_name'):
        raise WorkflowError('The linked project record is missing its client name.')
    quote = brief['quote']
    items = quote.get('items')
    if not isinstance(items, list) or not items or len(items) > 5:
        raise WorkflowError('Accepted scope must contain 1–5 saved package items.')
    for item in items:
        for key in ('description', 'scope', 'exclusions'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise WorkflowError('Accepted package scope is incomplete; owner review is required.')
    theme = payload.get('theme', 'coastal')
    if theme not in THEMES:
        raise WorkflowError('Choose one of the available visual themes.')
    note = payload.get('revision_note', '').strip()
    if not isinstance(note, str) or len(note) > MAX_REVISION:
        raise WorkflowError('Revision instructions must be 1,000 characters or fewer.')
    return brief, project, items, theme, note


def _site_content(name, industry, brief, items, theme, revision_note):
    categories = {item.get('category', '') for item in items}
    # Historical quote versions may not carry category, so retain a clear scope fallback.
    multi = bool(categories & {'multi-page', 'custom'}) or \
        any('multi-page' in str(item.get('scope', '')).casefold() for item in items)
    services = [dict(title=item['description'], description=item['scope']) for item in items]
    context = (brief.get('requirements', '') + ' ' + ' '.join(x['description'] for x in services)).strip()
    summary = f'{escape(name)} services' if industry else f'{escape(name)}'
    # Don't turn a business category into a claimed credential or track record.
    pages = [dict(slug='index', label='Home', title=name, heading=name,
                  intro='A clear starting point to learn about the services and get in touch.', kind='home')]
    if multi:
        pages.extend([
            dict(slug='services', label='Services', title='Services', heading='Services',
                 intro='Explore the services included in this website brief.', kind='services'),
            dict(slug='about', label='About', title='About', heading='About',
                 intro='Information about the business can be added here using customer-approved copy.', kind='about'),
            dict(slug='contact', label='Contact', title='Contact', heading='Contact',
                 intro='Send an enquiry using the contact details supplied by the business.', kind='contact'),
        ])
    else:
        pages[0]['sections'] = ['services', 'about', 'contact']
    return dict(name=name, industry=industry, summary=summary, theme=theme, pages=pages,
                services=services, branding=brief.get('branding_references', ''),
                requirements=context, revision_note=revision_note,
                contact_email='', testimonials=[], claims=[],
                limitations=['No testimonial, street address, credential or business claim was invented.',
                              'No customer contact endpoint was supplied; connect an approved form destination before publication.'])


def render_site(content):
    """Return one self-contained HTML document per page; all text is escaped."""
    theme=THEMES[content['theme']]; name=escape(content['name'])
    multi=len(content['pages'])>1
    nav_items=content['pages'] if multi else [dict(slug='services',label='Services'),dict(slug='about',label='About'),dict(slug='contact',label='Contact')]
    def href(slug):
        return '?page='+slug if multi else '#'+slug
    nav=''.join('<a href="'+escape(href(item['slug']),quote=True)+'">'+escape(item['label'])+'</a>' for item in nav_items)
    services=''.join('<article class="service-card"><h3>'+escape(item['title'])+'</h3><p>'+escape(item['description'])+'</p></article>' for item in content['services'])
    theme_css=f"--ink:{theme['ink']};--accent:{theme['accent']};--paper:{theme['paper']};--muted:{theme['muted']}"
    style='''<style>:root{'''+theme_css+''';--max:1120px}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}a{color:var(--accent);text-underline-offset:3px}.wrap{width:min(var(--max),calc(100% - 40px));margin:0 auto}.site-header{background:#fff;border-bottom:1px solid #dfe7e5}.nav{min-height:76px;display:flex;align-items:center;justify-content:space-between;gap:24px}.brand{font-size:20px;font-weight:750;letter-spacing:-.03em;color:var(--ink);text-decoration:none}.nav-links{display:flex;gap:24px}.nav-links a{font-size:14px;font-weight:650;text-decoration:none}.hero{padding:clamp(72px,12vw,150px) 0;background:linear-gradient(115deg,#fff 0%,var(--paper) 70%)}.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:750}.hero h1{max-width:850px;margin:10px 0 18px;font-size:clamp(42px,7vw,78px);letter-spacing:-.06em;line-height:1.02}.hero p{max-width:650px;color:var(--muted);font-size:19px}.button{display:inline-flex;margin-top:18px;padding:12px 19px;border-radius:6px;background:var(--accent);color:#fff;text-decoration:none;font-weight:700}.section{padding:80px 0}.section-soft{background:#fff}.section h2{font-size:clamp(30px,4vw,44px);letter-spacing:-.04em;line-height:1.15;margin:6px 0 24px}.section>div>p:not(.eyebrow){max-width:720px;color:var(--muted)}.service-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}.service-card{padding:24px;background:#fff;border:1px solid #e0e8e5;border-radius:12px}.service-card h3{margin:0 0 10px;font-size:19px}.service-card p{margin:0;color:var(--muted)}.contact-form{max-width:600px;display:grid;gap:14px}.contact-form label{display:grid;gap:6px;font-size:14px;font-weight:650}.contact-form input,.contact-form textarea{width:100%;padding:12px;border:1px solid #aebfbc;border-radius:6px;background:#fff;color:var(--ink);font:inherit}.contact-form button{justify-self:start;border:0;cursor:pointer}.form-note{color:var(--muted);font-size:13px}.site-footer{padding:28px 0;background:var(--ink);color:#fff}.site-footer p{margin:0}@media(max-width:650px){.wrap{width:min(var(--max),calc(100% - 30px))}.nav{min-height:64px;align-items:flex-start;flex-direction:column;padding:15px 0;gap:10px}.nav-links{width:100%;overflow:auto;gap:20px;padding-bottom:3px}.nav-links a{white-space:nowrap}.hero{padding:72px 0}.hero p{font-size:17px}.section{padding:58px 0}.service-grid{grid-template-columns:1fr}.contact-form button{width:100%}}</style>'''
    output={}
    for page in content['pages']:
        if page['kind']=='home':
            body='<section id="hero" class="hero"><div class="wrap"><p class="eyebrow">'+escape(content['industry'] or 'Local business')+'</p><h1>'+escape(page['heading'])+'</h1><p>'+escape(page['intro'])+'</p><a class="button" href="'+escape(href('contact'),quote=True)+'">Get in touch</a></div></section>'
            if not multi:
                body+='<section id="services" class="section"><div class="wrap"><p class="eyebrow">WHAT WE CAN HELP WITH</p><h2>Services</h2><div class="service-grid">'+services+'</div></div></section>'
                body+='<section id="about" class="section section-soft"><div class="wrap"><p class="eyebrow">ABOUT</p><h2>About '+name+'</h2><p>'+escape(page['intro'])+'</p></div></section>'
                body+='<section id="contact" class="section"><div class="wrap"><p class="eyebrow">CONTACT</p><h2>Start a conversation</h2>'+_contact_form()+'</div></section>'
            elif content['services']:
                body+='<section class="section"><div class="wrap"><h2>Services</h2><div class="service-grid">'+services+'</div></div></section>'
        elif page['kind']=='services':
            body='<main class="section"><div class="wrap"><h1>'+escape(page['heading'])+'</h1><p>'+escape(page['intro'])+'</p><div class="service-grid">'+services+'</div></div></main>'
        elif page['kind']=='contact':
            body='<main class="section"><div class="wrap"><h1>'+escape(page['heading'])+'</h1><p>'+escape(page['intro'])+'</p>'+_contact_form()+'</div></main>'
        else:
            body='<main class="section section-soft"><div class="wrap"><h1>'+escape(page['heading'])+'</h1><p>'+escape(page['intro'])+'</p></div></main>'
        title=page['title']+' · '+content['name']
        if not body.startswith('<main>') and not body.startswith('<main '): body='<main>'+body+'</main>'
        brand_href=href('index') if multi else '#hero'
        output[page['slug']]='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="'+escape((content['industry']+' services from '+content['name'])[:155],quote=True)+'"><title>'+escape(title)+'</title>'+style+'</head><body><header class="site-header"><div class="wrap nav"><a class="brand" href="'+escape(brand_href,quote=True)+'">'+name+'</a><nav class="nav-links" aria-label="Main navigation">'+nav+'</nav></div></header>'+body+'<footer class="site-footer"><div class="wrap"><p>'+name+'</p></div></footer></body></html>'
    return output


def _contact_form():
    return '<form class="contact-form" action="#contact" method="get"><label>Your name<input name="name" autocomplete="name" required></label><label>Email address<input name="email" type="email" autocomplete="email" required></label><label>How can we help?<textarea name="message" rows="4" required></textarea></label><button class="button" type="submit">Prepare enquiry</button><p class="form-note">This preview does not send or store messages. Connect a client-approved form destination before publication.</p></form>'


def apply_revision(content, note):
    """Apply the small, explicit local revision vocabulary; never execute prompts."""
    if not note:
        return
    home=content['pages'][0]
    for line in note.splitlines():
        match=re.fullmatch(r'\s*headline:\s*(.{1,140})\s*',line,re.I)
        if match:
            home['heading']=match.group(1).strip()
            home['title']=home['heading']
            continue
        match=re.fullmatch(r'\s*intro:\s*(.{1,360})\s*',line,re.I)
        if match:
            home['intro']=match.group(1).strip()
    if re.search(r'\b(shorter|concise|shorten the intro)\b',note,re.I):
        home['intro']='Learn about '+content['name']+' and the services in this accepted brief.'


class _Audit(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=set(); self.links=[]; self.images=[]; self.forms=[]; self.labels=0; self.fields=[]
    def handle_starttag(self, tag, attrs):
        item=dict(attrs)
        if item.get('id'): self.ids.add(item['id'])
        if tag == 'a': self.links.append(item.get('href',''))
        if tag == 'img': self.images.append(item)
        if tag == 'form': self.forms.append(item)
        if tag == 'label': self.labels += 1
        if tag in ('input','textarea'): self.fields.append(item)


def quality_check(pages, brief, content):
    if isinstance(pages,str): pages={'index':pages}
    errors=[]; warnings=[]
    parsers={}
    for slug,html in pages.items():
        errors.extend(slug+': '+error for error in static_errors(html))
        parser=_Audit(); parser.feed(html); parsers[slug]=parser
        for link in parser.links:
            if link.startswith('#') and link[1:] not in parser.ids:
                errors.append(slug+': navigation points to a missing section: '+link)
            if link.startswith('?page=') and link.split('=',1)[1] not in pages:
                errors.append(slug+': navigation points to a missing page: '+link)
        if '<html lang="en">' not in html or 'name="viewport"' not in html: errors.append(slug+': language or mobile viewport metadata is missing.')
        if '<meta name="description"' not in html or '<title>' not in html: errors.append(slug+': basic SEO title or description is missing.')
        if '<nav ' not in html or '<footer' not in html: errors.append(slug+': a page landmark is missing.')
        for image in parser.images:
            if not image.get('alt'): errors.append(slug+': an image is missing alternative text.')
        if any(x in html for x in ('<script', 'javascript:', ' onerror=', ' onclick=')):
            errors.append(slug+': unsafe executable markup or event handler detected.')
    if not any(p.forms for p in parsers.values()): errors.append('A contact form is missing.')
    if not any(p.labels>=3 for p in parsers.values()): errors.append('Contact fields are missing accessible labels.')
    for parser in parsers.values():
        for form in parser.forms:
            if not form.get('action'): errors.append('Contact form has no safe preview action.')
    fields=[field for p in parsers.values() for field in p.fields]
    if not any(f.get('name')=='name' and 'required' in f for f in fields): errors.append('Contact form name validation is missing.')
    if not any(f.get('type')=='email' and 'required' in f for f in fields): errors.append('Contact form email validation is missing.')
    if not any(f.get('name')=='message' and 'required' in f for f in fields): errors.append('Contact form message validation is missing.')
    # The local renderer has a fixed token vocabulary. These are phrases which
    # could imply unsupported status if introduced by a future renderer/model.
    claim_pattern=re.compile(r'\b(#1|number one|award[- ]winning|certified|licensed|guaranteed|trusted by|years of experience|customer testimonial|leading (?:provider|business|team)|top[- ]rated|experts?|fully insured|family[- ]owned|proven results)\b', re.I)
    brief_text=json.dumps(brief,ensure_ascii=False)
    for html in pages.values():
        for match in claim_pattern.finditer(html):
            if match.group(0).casefold() not in brief_text.casefold(): errors.append('Unsupported business claim detected: '+match.group(0))
    if not content.get('services'): errors.append('No accepted services were rendered.')
    if not content.get('testimonials'):
        warnings.append('No testimonial section was created because none was supplied and approved.')
    warnings.extend(content['limitations'])
    return dict(passed=not errors, critical_errors=errors, warnings=warnings,
                checks=dict(navigation=not any('navigation points' in e for e in errors), contact_form=any(p.forms for p in parsers.values()), form_validation=not any('Contact form ' in e for e in errors), accessible_labels=not any('accessible labels' in e for e in errors), images_have_alt=all(i.get('alt') for p in parsers.values() for i in p.images),
                            language_and_viewport=all('<html lang="en">' in h and 'name="viewport"' in h for h in pages.values()),
                            landmarks=all('<nav ' in h and '<footer' in h for h in pages.values()),
                            seo_description=all('<meta name="description"' in h for h in pages.values()),
                            unsupported_claim_scan=not any('Unsupported business claim' in e for e in errors),
                            safe_static_markup=not any('Unsafe executable' in e for e in errors), scope_services=bool(content.get('services'))))


def apply_ai_copy(result, generated):
    """Allow AI to supply bounded text fields only; templates and markup stay local."""
    if set(generated)!={'subject','body','evidence_ids','limitation'}:
        raise WorkflowError('AI website copy did not match the approved text-only output schema.')
    headline=generated['subject'].strip()
    intro=generated['body'].strip()
    if not (1<=len(headline)<=140 and 1<=len(intro)<=360):
        raise WorkflowError('AI website copy exceeded the bounded headline or introduction size.')
    brief_claims=json.dumps(result['content'],ensure_ascii=False)
    claim_pattern=re.compile(r'\b(#1|number one|award[- ]winning|certified|licensed|guaranteed|trusted by|years of experience|customer testimonial|leading (?:provider|business|team)|top[- ]rated|experts?|fully insured|family[- ]owned|proven results)\b',re.I)
    for match in claim_pattern.finditer(headline+' '+intro):
        if match.group(0).casefold() not in brief_claims.casefold():
            raise WorkflowError('AI website copy contains an unsupported business claim; no website version was saved.')
    result['content']['pages'][0]['heading']=headline
    result['content']['pages'][0]['title']=headline
    result['content']['pages'][0]['intro']=intro
    result['content']['ai_copy_limitation']=generated['limitation']
    result['pages']=render_site(result['content'])
    result['html']=result['pages']['index']
    brief=result.get('brief',{})
    result['qa']=quality_check(result['pages'],brief,result['content'])
    return result


def build(conn, payload):
    brief, project, items, theme, note = _source(payload)
    content = _site_content(project['client_name'], payload.get('industry',''), brief, items, theme, note)
    apply_revision(content,note)
    pages = render_site(content)
    qa = quality_check(pages, brief, content)
    if payload.get('revision_note'):
        # Keep revision trace in content and record every requested change.
        content['revision_note'] = payload['revision_note'].strip()
    return dict(content=content, html=pages['index'], pages=pages, qa=qa, brief=brief, project_id=project['id'], brief_id=payload['brief_id'], theme=theme)


def register(app, get_db, login_required):
    def site_access(site_id):
        row=get_db().execute('''SELECT s.*,f.id flow_id FROM p6_sites s
          JOIN p5_project_briefs b ON b.id=s.brief_id JOIN p5_acceptances a ON a.id=b.acceptance_id
          JOIN p5_quotes q ON q.id=a.quote_id JOIN p5_flows f ON f.id=q.flow_id
          WHERE s.id=? AND s.owner_id=? AND f.user_id=?''',(site_id,session['user_id'],session['user_id'])).fetchone()
        if not row: abort(404)
        return row

    def version_access(site_id, version):
        site=site_access(site_id)
        item=get_db().execute('SELECT * FROM p6_site_versions WHERE site_id=? AND version=?',(site_id,version)).fetchone()
        if not item: abort(404)
        return site,item

    @app.route('/projects/<int:project_id>/website', methods=['GET'])
    @login_required
    def website_project(project_id):
        conn=get_db()
        project=conn.execute('''SELECT p.*,b.id brief_id,b.brief_json,f.id flow_id FROM projects p
          JOIN p5_project_briefs b ON b.project_id=p.id JOIN p5_acceptances a ON a.id=b.acceptance_id
          JOIN p5_quotes q ON q.id=a.quote_id JOIN p5_flows f ON f.id=q.flow_id
          WHERE p.id=? AND f.user_id=?''',(project_id,session['user_id'])).fetchone()
        if not project: abort(404)
        site=conn.execute('SELECT * FROM p6_sites WHERE project_id=?',(project_id,)).fetchone()
        versions=conn.execute('SELECT * FROM p6_site_versions WHERE site_id=? ORDER BY version DESC',(site['id'],)).fetchall() if site else []
        latest=versions[0] if versions else None
        brief=json.loads(project['brief_json'])
        website_job=conn.execute("SELECT * FROM p5_jobs WHERE flow_id=? AND kind='website' ORDER BY id DESC LIMIT 1",(project['flow_id'],)).fetchone()
        releases=conn.execute('SELECT * FROM p10_releases WHERE site_id=? ORDER BY id DESC',(site['id'],)).fetchall() if site else []
        checks={release['id']:conn.execute('SELECT * FROM p10_checks WHERE release_id=? ORDER BY id DESC LIMIT 1',(release['id'],)).fetchone() for release in releases}
        alerts=conn.execute('SELECT * FROM p10_alerts WHERE owner_id=? AND (release_id IN (SELECT id FROM p10_releases WHERE site_id=?) OR release_id IS NULL) ORDER BY id DESC LIMIT 20',(session['user_id'],site['id'] if site else -1)).fetchall()
        return render_template('website_project.html',project=project,site=site,versions=versions,latest=latest,website_job=website_job,
                               brief=brief,themes=THEMES,
                               content=json.loads(latest['content_json']) if latest else {},
                               qa=json.loads(latest['qa_json']) if latest else {},releases=releases,checks=checks,release_alerts=alerts)

    @app.route('/projects/<int:project_id>/website/generate', methods=['POST'])
    @login_required
    def website_generate(project_id):
        conn=get_db(); conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('''SELECT p.id project_id,p.client_name,b.id brief_id,b.brief_json,a.id acceptance_id,
          q.flow_id,f.user_id,f.snapshot_json FROM projects p JOIN p5_project_briefs b ON b.project_id=p.id
          JOIN p5_acceptances a ON a.id=b.acceptance_id JOIN p5_quotes q ON q.id=a.quote_id
          JOIN p5_flows f ON f.id=q.flow_id WHERE p.id=? AND f.user_id=? AND f.state='Project brief ready' ''',
          (project_id,session['user_id'])).fetchone()
        if not row: abort(404)
        if request.form.get('confirm')!='yes': raise WorkflowError('Explicit authorization for local website generation is required.')
        mode=request.form.get('mode','local')
        if mode not in ('local','ai'): raise WorkflowError('Choose local generation or the separately approved AI option.')
        brief=json.loads(row['brief_json'])
        if brief.get('quote_hash') != conn.execute('SELECT content_hash FROM p5_quotes WHERE id=?',(brief.get('quote_id'),)).fetchone()['content_hash']:
            raise WorkflowError('Accepted quote hash no longer matches the saved project brief.')
        site=conn.execute('SELECT * FROM p6_sites WHERE project_id=?',(project_id,)).fetchone()
        if not site:
            site_id=conn.execute("INSERT INTO p6_sites(project_id,brief_id,owner_id,status,generation_authorized_at,created_at) VALUES(?,?,?,'Queued',?,?)",
                                 (project_id,row['brief_id'],session['user_id'],stamp(),stamp())).lastrowid
        else:
            if site['status'] in ('Queued','Needs review','Approved'):
                raise WorkflowError('A build is already pending or a version is awaiting review/approved. Use the revision workflow to create another version.')
            site_id=site['id']
        snapshot=json.loads(row['snapshot_json']);
        store.enqueue(conn,row['flow_id'],'website',dict(site_id=site_id,project_id=project_id,brief_id=row['brief_id'],brief=brief,
            project=dict(id=project_id,client_name=row['client_name']),industry=snapshot.get('lead',{}).get('industry',''),
            theme=request.form.get('theme','coastal'),revision_note=''),mode=mode,key='website-build-'+str(site_id)+'-'+str(time.time_ns()))
        store.log(conn,session['user_id'],'Owner authorized local website generation from accepted brief; no publication authorized.',row['flow_id'])
        conn.commit()
        if mode=='ai': return redirect(url_for('sales_flow',flow_id=row['flow_id']))
        return redirect(url_for('website_project',project_id=project_id))

    @app.route('/websites/<int:site_id>/revise', methods=['POST'])
    @login_required
    def website_revise(site_id):
        conn=get_db(); site=site_access(site_id); conn.execute('BEGIN IMMEDIATE')
        note=request.form.get('revision_note','').strip(); theme=request.form.get('theme','coastal')
        if not note or len(note)>MAX_REVISION: raise WorkflowError('Describe the requested revision in 1,000 characters or fewer.')
        if theme not in THEMES: raise WorkflowError('Choose an available visual theme.')
        if conn.execute("SELECT 1 FROM p5_jobs WHERE flow_id=? AND kind='website' AND status IN ('Queued','Running','Awaiting approval')",(site['flow_id'],)).fetchone():
            raise WorkflowError('A website build is already queued or running for this project.')
        b=conn.execute('SELECT brief_json FROM p5_project_briefs WHERE id=?',(site['brief_id'],)).fetchone()
        p=conn.execute('SELECT id,client_name FROM projects WHERE id=?',(site['project_id'],)).fetchone()
        f=conn.execute('SELECT snapshot_json FROM p5_flows WHERE id=?',(site['flow_id'],)).fetchone()
        store.enqueue(conn,site['flow_id'],'website',dict(site_id=site_id,project_id=site['project_id'],brief_id=site['brief_id'],
            brief=json.loads(b['brief_json']),project=dict(p),industry=json.loads(f['snapshot_json']).get('lead',{}).get('industry',''),
            theme=theme,revision_note=note),key='website-revision-'+str(site_id)+'-'+str(time.time_ns()))
        conn.execute("UPDATE p6_sites SET status='Queued' WHERE id=?",(site_id,))
        store.log(conn,session['user_id'],'Queued local website revision; existing versions are preserved.',site['flow_id'])
        conn.commit(); return redirect(url_for('website_project',project_id=site['project_id']))

    @app.route('/websites/<int:site_id>/approve/<int:version>', methods=['POST'])
    @login_required
    def website_approve(site_id,version):
        conn=get_db(); site,item=version_access(site_id,version); conn.execute('BEGIN IMMEDIATE')
        latest=conn.execute('SELECT MAX(version) FROM p6_site_versions WHERE site_id=?',(site_id,)).fetchone()[0]
        qa=json.loads(item['qa_json'])
        if item['status']!='Needs review' or version!=latest: abort(409)
        if not qa.get('passed'): raise WorkflowError('Critical website QA issues must be fixed before approval.')
        if request.form.get('confirm')!='yes': raise WorkflowError('Explicit owner review and approval are required.')
        conn.execute("UPDATE p6_site_versions SET status='Superseded' WHERE site_id=? AND status='Approved'",(site_id,))
        conn.execute("UPDATE p6_site_versions SET status='Approved' WHERE id=?",(item['id'],))
        conn.execute("UPDATE p6_sites SET status='Approved',active_version=?,approved_at=? WHERE id=?",(version,stamp(),site_id))
        store.log(conn,session['user_id'],'Owner approved website version '+str(version)+' for project review; publication remains unauthorized.',site['flow_id'])
        conn.commit(); return redirect(url_for('website_project',project_id=site['project_id']))

    @app.route('/websites/<int:site_id>/restore/<int:version>', methods=['POST'])
    @login_required
    def website_restore(site_id,version):
        conn=get_db(); site,item=version_access(site_id,version); conn.execute('BEGIN IMMEDIATE')
        # Restoration creates a new review version, preserving the full audit trail.
        conn.execute("UPDATE p6_sites SET status='Needs review' WHERE id=?",(site_id,))
        conn.execute("UPDATE p6_site_versions SET status='Superseded' WHERE site_id=? AND status='Needs review'",(site_id,))
        version_no=conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM p6_site_versions WHERE site_id=?',(site_id,)).fetchone()[0]
        conn.execute('INSERT INTO p6_site_versions(site_id,version,theme,content_json,html,pages_json,qa_json,revision_note,status,created_at) VALUES(?,?,?,?,?,?,?,? ,\'Needs review\',?)',
          (site_id,version_no,item['theme'],item['content_json'],item['html'],item['pages_json'],item['qa_json'],'Restored review copy of version '+str(version),stamp()))
        store.log(conn,session['user_id'],'Restored website version '+str(version)+' as a new review version; prior versions preserved.',site['flow_id'])
        conn.commit(); return redirect(url_for('website_project',project_id=site['project_id']))

    @app.route('/websites/<int:site_id>/preview/<int:version>')
    @login_required
    def website_preview(site_id,version):
        _site,item=version_access(site_id,version)
        # sandboxed iframe prevents generated static pages accessing app storage,
        # credentials, forms, or parent window. No scripts are generated.
        return render_template('website_preview.html',item=item,site_id=site_id,project_id=_site['project_id'])

    @app.route('/websites/<int:site_id>/source/<int:version>')
    @login_required
    def website_source(site_id,version):
        from flask import Response
        _site,item=version_access(site_id,version)
        pages=json.loads(item['pages_json'] or '{}')
        page=request.args.get('page','index')
        if page not in pages: abort(404)
        return Response(pages[page],mimetype='text/html',headers={'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'private, no-store'})


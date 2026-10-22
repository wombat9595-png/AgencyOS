"""The Designer agent: a scroll-story mock-up for each lead, built from the motion-kit demos.

The three demo sites (builder, landscaper, salon) are filled in with the lead's own name,
phone and email. "Download" makes one self-contained HTML file to attach to an email.
Nothing is published; the mock-up only exists on this Mac until the owner sends it.
"""
import base64
import html
import os
import re
from flask import Response,url_for
import playbook

ROOT=os.path.dirname(os.path.abspath(__file__))
KIT=os.path.join(ROOT,'static','motion','kit')
DEMO_PHONE,DEMO_TEL,DEMO_EMAIL='0400 000 000','0400000000','hello@example.com'


def _read(*parts):
    with open(os.path.join(*parts),encoding='utf-8') as handle:return handle.read()


def render(p,s,story,inline=False,media_prefix=None):
    """The demo page with the lead's details in it. inline=True packs every file into one page;
    media_prefix keeps real footage as files at that relative path (the publish pack) instead."""
    page=_read(ROOT,'templates','stories',story['demo']+'.html')
    name=html.escape(p['name'],quote=True)
    maker=html.escape(s['business'],quote=True)
    page=re.sub(r'Demo site by [^<]*? is a made-up business;[^<]*',
      'Free mock-up for '+name+' by '+maker+'. Photos, reviews, prices and numbers are placeholders until we add yours.',page)
    page=page.replace(story['name'],name)
    if story['demo']=='salon':page=page.replace('Maison Rosé',name)
    page=page.replace('aria-hidden="true">'+story['mark']+'</span>','aria-hidden="true">'+html.escape(p['name'][:1].upper())+'</span>')
    if p['phone']:
        page=page.replace(DEMO_PHONE,html.escape(p['phone'])).replace(DEMO_TEL,re.sub(r'[^0-9+]','',p['phone']))
    if p['email']:page=page.replace(DEMO_EMAIL,html.escape(p['email']))
    if story.get('media'):page=_real_media(page,story['media'],inline,media_prefix)
    if not inline:
        page=page.replace('../../kit/',url_for('static',filename='motion/kit/'))
        return page.replace('src="scene.js"','src="'+url_for('static',filename='motion/demos/'+story['demo']+'/scene.js')+'"')
    page=re.sub(r'<link rel="preload"[^>]*>\n?','',page)
    def css(match):
        text=_read(KIT,match.group(1))
        def font(m):
            data=base64.b64encode(open(os.path.join(KIT,m.group(1)),'rb').read()).decode()
            return "url('data:font/woff2;base64,"+data+"')"
        return '<style>'+re.sub(r"url\('(fonts/[^']+)'\)",font,text)+'</style>'
    page=re.sub(r'<link rel="stylesheet" href="\.\./\.\./kit/([^"]+)">',css,page)
    def script(match):
        path=os.path.join(ROOT,'static','motion','demos',story['demo'],'scene.js') if match.group(1)=='scene.js' else os.path.join(KIT,match.group(1).removeprefix('../../kit/'))
        return '<script>'+_read(path).replace('</script','<\\/script')+'</script>'
    return re.sub(r'<script src="((?:\.\./\.\./kit/)?[^"]+)" defer></script>',script,page)


def _data_uri(path):
    with open(path,'rb') as handle:return 'data:image/jpeg;base64,'+base64.b64encode(handle.read()).decode()


def _real_media(page,media,inline,prefix=None):
    """Real footage pages (static/motion/real/<media>/). In the app they load the full frame set;
    the downloadable single file carries every fourth frame at email-friendly size."""
    folder=os.path.join(ROOT,'static','motion','real',media)
    if prefix:return page.replace('REAL_MEDIA/',prefix+media+'/')
    if not inline:return page.replace('REAL_MEDIA/',url_for('static',filename='motion/real/'+media+'/'))
    small=os.path.join(folder,'inline')
    frames=sorted(name for name in os.listdir(small) if name.startswith('i_'))
    page=re.sub(r"window\.BUILD_FRAMES=\{[^}]*\};",lambda m:'window.BUILD_FRAMES={list:['+','.join("'"+_data_uri(os.path.join(small,f))+"'" for f in frames)+']};',page)
    def still(match):
        name=match.group(1)
        if name.startswith('f_'):name=frames[min(len(frames)-1,(int(name[2:5])-1)//4)]
        return _data_uri(os.path.join(small,name))
    return re.sub(r'REAL_MEDIA/([a-z0-9_-]+\.jpg)',still,page)


def register(app,get_db,login_required):
    from flask import request,session
    import lead_engine

    @app.get('/find-customers/<int:prospect_id>/story')
    @login_required
    def prospects_story(prospect_id):
        conn=get_db();owner=session['user_id'];p=lead_engine.prospect_for(conn,owner,prospect_id)
        story=playbook.story_for(p['trade'])
        if not story:
            from flask import redirect
            return redirect(url_for('prospects_mockup',prospect_id=prospect_id))
        s=lead_engine.settings(conn,owner)
        if request.args.get('download'):
            slug=re.sub(r'[^a-z0-9]+','-',p['name'].casefold()).strip('-') or 'mockup'
            return Response(render(p,s,story,inline=True),mimetype='text/html',headers={'Content-Disposition':'attachment; filename="'+slug+'-story-mockup.html"'})
        return render(p,s,story)

"""The Writer agent: drafts outreach from the shared playbook, optionally with Claude Haiku.

Off by default. The AI only runs when the owner switches it on, an Anthropic API key is set,
the zero-cost policy is lifted, and this month's spend is under the owner's cap. Every AI
draft must pass playbook.review(); otherwise the rule-based draft is used. Never sends.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from phase3_store import stamp
from production_security import secret
import lead_engine
import playbook

MODEL='claude-haiku-5-5'
# Claude Haiku 5.5: US$0.10 per million input tokens, US$0.50 per million output tokens.
USD_PER_MTOK_IN,USD_PER_MTOK_OUT=0.10,0.50
AUD_PER_USD=1.60  # deliberately on the high side so the cap is conservative
DEFAULT_CAP_CENTS=500  # A$5 a month


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS writer_settings (owner_id INTEGER PRIMARY KEY, ai_enabled INTEGER NOT NULL DEFAULT 0, cap_cents INTEGER NOT NULL DEFAULT 500);
    CREATE TABLE IF NOT EXISTS writer_usage (owner_id INTEGER NOT NULL, month TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
      input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner_id,month));
    ''')
    columns={r[1] for r in conn.execute('PRAGMA table_info(prospects)')}
    if 'draft_body' not in columns:
        for column in ('draft_subject','draft_body','draft_kind','draft_source'):
            conn.execute('ALTER TABLE prospects ADD COLUMN '+column+" TEXT NOT NULL DEFAULT ''")


def month():
    return datetime.now(ZoneInfo('Australia/Sydney')).strftime('%Y-%m')


def settings(conn,owner):
    row=conn.execute('SELECT * FROM writer_settings WHERE owner_id=?',(owner,)).fetchone()
    return dict(row) if row else dict(owner_id=owner,ai_enabled=0,cap_cents=DEFAULT_CAP_CENTS)


def spent_cents(conn,owner,on_month=None):
    row=conn.execute('SELECT input_tokens,output_tokens FROM writer_usage WHERE owner_id=? AND month=?',(owner,on_month or month())).fetchone()
    if not row:return 0.0
    usd=row['input_tokens']/1e6*USD_PER_MTOK_IN+row['output_tokens']/1e6*USD_PER_MTOK_OUT
    return usd*AUD_PER_USD*100


def ai_status(conn,owner):
    """Why the AI Writer is or is not running, in plain words."""
    s=settings(conn,owner);spent=spent_cents(conn,owner)
    status=dict(enabled=bool(s['ai_enabled']),cap_cents=s['cap_cents'],spent_cents=round(spent,2),ready=False,reason='')
    if not s['ai_enabled']:status['reason']='Off. Drafts use the playbook rules (free).'
    elif os.environ.get('AGENCYOS_ZERO_COST')=='1':status['reason']='Switched on, but the free-only safety lock is still on, so drafts use the rules.'
    elif not secret('ANTHROPIC_API_KEY'):status['reason']='Switched on, but no Anthropic API key is set yet, so drafts use the rules.'
    elif spent>=s['cap_cents']:status['reason']='This month\'s A$'+format(s['cap_cents']/100,'.2f')+' cap is used up, so drafts use the rules until next month.'
    else:
        try:import anthropic  # noqa: F401
        except ImportError:status['reason']='Switched on, but the Anthropic library is not installed yet, so drafts use the rules.'
        else:status.update(ready=True,reason='On. Haiku writes each draft; the playbook checks it before you see it.')
    return status


def _ask_haiku(prompt):
    """One short request. Returns (text, input_tokens, output_tokens)."""
    import anthropic
    client=anthropic.Anthropic(api_key=secret('ANTHROPIC_API_KEY'),timeout=30.0,max_retries=1)
    response=client.messages.create(model=MODEL,max_tokens=1024,output_config={'effort':'low'},
      messages=[{'role':'user','content':prompt}])
    text=''.join(b.text for b in response.content if b.type=='text') if response.stop_reason!='refusal' else ''
    return text,response.usage.input_tokens,response.usage.output_tokens


def _record(conn,owner,tokens_in,tokens_out):
    conn.execute('INSERT INTO writer_usage(owner_id,month,calls,input_tokens,output_tokens) VALUES(?,?,1,?,?) '
      'ON CONFLICT(owner_id,month) DO UPDATE SET calls=calls+1,input_tokens=input_tokens+excluded.input_tokens,output_tokens=output_tokens+excluded.output_tokens',
      (owner,month(),tokens_in,tokens_out))


def _parse(text):
    lines=text.strip().split('\n')
    if not lines or not lines[0].lower().startswith('subject:'):return None
    subject=lines[0].split(':',1)[1].strip();body='\n'.join(lines[1:]).strip()
    return (subject,body) if subject and body else None


def current_kind(p):
    if not p['email'] and p['phone']:return 'call'
    return ('first','followup1','followup2')[min(p['touches'],2)]


def write(conn,owner,p,s,ask=None):
    """Draft the next message for this business and store it on the record. Returns the source ('ai' or 'rules')."""
    kind=current_kind(p)
    subject,body=lead_engine.draft(p,s,kind)
    source='rules'
    if kind!='call' and ai_status(conn,owner)['ready']:
        try:
            text,tokens_in,tokens_out=(ask or _ask_haiku)(playbook.brief(p,s,kind))
            _record(conn,owner,tokens_in,tokens_out)
            parsed=_parse(text)
            if parsed:
                sign=body[body.index('\n\nCheers,'):] if '\n\nCheers,' in body else ''
                ai_subject,ai_body=parsed[0],parsed[1].rstrip()+sign
                if not playbook.review(ai_subject,ai_body,p,s,kind):subject,body,source=ai_subject,ai_body,'ai'
        except Exception:  # Network, key or provider trouble: fall back to the free rules, never block the shift.
            pass
    conn.execute('UPDATE prospects SET draft_subject=?,draft_body=?,draft_kind=?,draft_source=? WHERE id=?',(subject,body,kind,source,p['id']))
    return source


def stored(p):
    """The stored draft if it is for the message this business is due next, else None."""
    if p['draft_body'] and p['draft_kind']==current_kind(p):return p['draft_subject'],p['draft_body']
    return None


def register(app,get_db,login_required):
    from flask import flash,redirect,request,session,url_for
    from phase3_store import WorkflowError

    @app.post('/writer/settings')
    @login_required
    def writer_settings():
        conn=get_db();owner=session['user_id']
        enabled=request.form.get('ai_enabled')=='1'
        try:cap=round(float(request.form.get('cap','5'))*100)
        except ValueError:cap=-1
        if not 0<=cap<=2000:raise WorkflowError('Pick a monthly cap between A$0 and A$20.')
        if enabled and request.form.get('confirm')!='yes':raise WorkflowError('Tick to confirm you are happy to spend up to the cap each month.')
        conn.execute('INSERT OR REPLACE INTO writer_settings VALUES(?,?,?)',(owner,int(enabled),cap));conn.commit()
        flash(ai_status(conn,owner)['reason'],'success')
        return redirect(url_for('night_shift_home'))

"""Office: a text-free animated view of what each agent is doing, drawn from brain.snapshot()."""
import json
from flask import jsonify,render_template,request,session,url_for
import brain
import runtime_status


def state(conn,owner,want_sample=''):
    """Real activity unless the owner asks for the sample, or nothing at all is happening yet."""
    runtime=runtime_status.status(conn,conn.execute('PRAGMA database_list').fetchone()[2],'5')
    snap=brain.snapshot(conn,owner,worker=bool(runtime['workers']))
    if want_sample=='1' or (want_sample!='0' and not snap['active'] and not snap['paused']):snap=brain.sample()
    snap.setdefault('sample',False)
    for sector in snap['sectors']:sector['url']=url_for(sector.pop('endpoint'))
    return snap


def register(app,get_db,login_required):
    @app.get('/office',strict_slashes=False)
    @login_required
    def office():
        snap=state(get_db(),session['user_id'],request.args.get('sample',''))
        return render_template('office.html',snap=snap,snap_json=json.dumps(snap))

    @app.get('/office/state')
    @login_required
    def office_state():
        return jsonify(state(get_db(),session['user_id'],request.args.get('sample','')))

"""Reproducible local production-preparation checks; isolated synthetic fixtures only."""
import ast
from concurrent.futures import ThreadPoolExecutor
import configparser
import json
import platform
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'validation'/'evidence'/'production-final';OUT.mkdir(parents=True,exist_ok=True)
commands={
 'unit-tests':['-m','unittest','discover','-s','tests','-v'],
 'http-smoke':['tests/smoke_server.py'],
 'sales-smoke':['tests/smoke_sales.py'],
 'gunicorn-smoke':['tests/smoke_production.py'],
 'overnight':['tests/smoke_overnight.py','--artifacts',str(OUT)],
 'browser':['tests/browser_phase5.py','--artifacts',str(OUT)],
 'dependency-check':['-m','pip','check'],
 'dependency-audit':['-m','pip_audit','--local','--format','json','--output',str(OUT/'dependency-audit.json')],
}
def run(item):
    label,args=item;started=time.monotonic()
    result=subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True,timeout=240)
    (OUT/(label+'.log')).write_text(result.stdout+result.stderr)
    record=dict(name=label,command=[sys.executable,*args],passed=result.returncode==0,seconds=round(time.monotonic()-started,3))
    print(json.dumps(record),flush=True);return record

if __name__=='__main__':
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,commands.items()))
    for file in ROOT.glob('*.py'):ast.parse(file.read_text(),filename=str(file))
    units=[]
    for file in (ROOT/'deploy').glob('*.service'):
        parser=configparser.ConfigParser(interpolation=None,strict=False);parser.read(file)
        assert parser.has_section('Service') and parser.has_option('Service','ExecStart'),str(file)
        units.append(file.name)
    results.append(dict(name='source-and-service-static-check',passed=True,units=units,limitation='Syntax/structure only. Linux systemd/nginx and public TLS not executed.'))
    report=dict(passed=all(r['passed'] for r in results),python=platform.python_version(),platform=platform.platform(),seconds=round(time.monotonic()-started,3),checks=results)
    (OUT/'validation-results.json').write_text(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)

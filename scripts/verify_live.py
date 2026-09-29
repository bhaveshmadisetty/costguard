"""Record live integration evidence, then benchmark cache-only subprocess runs."""
import datetime
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence'
OUT.mkdir(exist_ok=True)


def run(name, *flags, stdin=False):
    plan=ROOT/'test-plans'/f'{name}.json'
    args=[sys.executable,str(ROOT/'costguard.py'),'--json','--strict',*flags]
    if not stdin:args+=['--plan',str(plan)]
    started=time.perf_counter()
    process=subprocess.run(args,cwd=ROOT,input=plan.read_text() if stdin else None,text=True,capture_output=True)
    elapsed=(time.perf_counter()-started)*1000
    result=json.loads(process.stdout)
    assert process.returncode==result['exit_code'],process.stderr
    return dict(plan=name,elapsed_ms=round(elapsed,3),**result)


results=[]
for i,name in enumerate(['plan-a-small-add','03-upgrade','02-delete','04-hostile-noise','05-tags-only','06-replace','07-downgrade','plan-b-upgrade-delete']):
    result=run(name,*(['--clear-cache'] if i==0 else []))
    assert result['complete'],result['warnings']
    results.append(result)
results.append(run('plan-a-small-add','--offline','--max-increase','20'))
assert results[-1]['exit_code']==1
results.append(run('01-create','--currency','EUR'))
assert results[-1]['complete']
results.append(run('01-create','--offline',stdin=True))
assert results[-1]['complete'] and results[-1]['api_calls']==0
samples=[run('plan-a-small-add','--offline') for _ in range(10)]
assert all(s['api_calls']==0 and s['cache_hits']==2 for s in samples)
benchmark=dict(runs=10,median_ms=round(statistics.median(s['elapsed_ms'] for s in samples),3),
               min_ms=min(s['elapsed_ms'] for s in samples),max_ms=max(s['elapsed_ms'] for s in samples),
               scope='Fresh Python subprocess, full CLI JSON output, offline cache, excludes py launcher',
               samples_ms=[s['elapsed_ms'] for s in samples])
document=dict(verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              fixture_origin='Synthetic Terraform-format fixtures; not generated from an Azure deployment',
              results=results,cache_benchmark=benchmark)
(OUT/'live-results.json').write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'runs':len(results),'cache_benchmark':benchmark,'evidence':str(OUT/'live-results.json')},indent=2))

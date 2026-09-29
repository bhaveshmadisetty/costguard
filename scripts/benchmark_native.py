"""Measure complete warm-cache native CostGuard launches on Windows."""
import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'costguard.exe'
if not EXE.exists():
    raise SystemExit('Build the native CLI with py scripts/build_fast.py first.')
plan=ROOT/'test-plans'/'terraform-azure-create.json'
command=[str(EXE),'--plan',str(plan),'--offline','--strict','--max-increase','50']
samples=[]
for _ in range(30):
    started=time.perf_counter()
    run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    elapsed=(time.perf_counter()-started)*1000
    if run.returncode!=0 or 'Cache: 2 hits, 0 API requests' not in run.stdout or 'Status: PASSED' not in run.stdout:
        raise SystemExit('Native benchmark did not complete a warm-cache run:\n'+run.stdout+run.stderr)
    samples.append(round(elapsed,3))
result={'scope':'Complete Windows native process launch, plan read, SQLite lookups, cost math, terminal output',
        'plan':plan.name,'runs':len(samples),'median_ms':round(statistics.median(samples),3),
        'second_full_run_ms':samples[1], 'second_full_run_under_50_ms':samples[1]<50,
        'max_ms':max(samples),'min_ms':min(samples),'all_under_50_ms':all(v<50 for v in samples),
        'samples_ms':samples}
(ROOT/'evidence'/'native-benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='samples_ms'},indent=2))

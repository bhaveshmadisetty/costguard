"""Measure cached processing independently from interpreter startup."""
import contextlib
import io
import json
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import costguard

samples=[]
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    warm=costguard.main(['--plan',str(ROOT/'test-plans/plan-a-small-add.json'),
                         '--cache',str(ROOT/'pricing_cache.db'),'--offline','--strict'])
if warm != 0:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        warm=costguard.main(['--plan',str(ROOT/'test-plans/plan-a-small-add.json'),
                             '--cache',str(ROOT/'pricing_cache.db'),'--timeout','20','--strict'])
if warm != 0:
    raise SystemExit('Cannot benchmark an incomplete cache: Azure pricing did not respond. Retry later; no timing evidence was written.')
for _ in range(20):
    start=time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        code=costguard.main(['--plan',str(ROOT/'test-plans/plan-a-small-add.json'),
                             '--cache',str(ROOT/'pricing_cache.db'),'--offline','--strict'])
    if code != 0:
        raise SystemExit('Cached pricing became incomplete during the benchmark.')
    samples.append((time.perf_counter()-start)*1000)
result=dict(scope='In-process main(): argument parsing, file, SQLite, pricing math, rendering; excludes interpreter startup',
            runs=len(samples),median_ms=round(statistics.median(samples),3),max_ms=round(max(samples),3),
            samples_ms=[round(s,3) for s in samples])
(ROOT/'evidence/cached-processing.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))

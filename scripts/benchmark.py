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
for _ in range(20):
    start=time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        code=costguard.main(['--plan',str(ROOT/'test-plans/plan-a-small-add.json'),
                             '--cache',str(ROOT/'pricing_cache.db'),'--offline','--strict'])
    assert code==0,'Warm cache first with Plan A'
    samples.append((time.perf_counter()-start)*1000)
result=dict(scope='In-process main(): argument parsing, file, SQLite, pricing math, rendering; excludes interpreter startup',
            runs=len(samples),median_ms=round(statistics.median(samples),3),max_ms=round(max(samples),3),
            samples_ms=[round(s,3) for s in samples])
(ROOT/'evidence/cached-processing.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))

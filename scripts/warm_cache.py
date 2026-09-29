"""Warm the demo price cache so every sample plan works in cached-only mode.

Runs each bundled sample once against the live Azure Retail Prices API using the
normal ``pricing_cache.db``; a second pass must then complete with zero API calls.
Run this on the demo network before the judging walkthrough.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ['plan-a-small-add', 'plan-b-upgrade-delete', '01-create', '02-delete', '03-upgrade',
           '05-tags-only', '06-replace', '07-downgrade', 'terraform-azure-create',
           'terraform-azure-upgrade', 'terraform-azure-delete']
EXTRA_CURRENCIES = {'01-create': ['EUR', 'GBP', 'INR']}


def run(name, currency, offline):
    args = [sys.executable, str(ROOT / 'costguard.py'), '--plan', str(ROOT / 'test-plans' / f'{name}.json'),
            '--json', '--strict', '--timeout', '30', '--currency', currency]
    if offline:
        args.append('--offline')
    process = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if not process.stdout.strip():
        raise SystemExit(f'{name} ({currency}): {process.stderr.strip() or "no output"}')
    return json.loads(process.stdout)


def main():
    incomplete = []
    for name in SAMPLES:
        for currency in ['USD'] + EXTRA_CURRENCIES.get(name, []):
            live = run(name, currency, offline=False)
            cached = run(name, currency, offline=True)
            status = 'ok' if cached['complete'] and cached['api_calls'] == 0 else 'INCOMPLETE'
            if status != 'ok':
                incomplete.append(f'{name} ({currency}): ' + '; '.join(cached['warnings']))
            print(f"{name:26} {currency}  live: {live['api_calls']} API / {live['cache_hits']} hits  "
                  f"cached: {cached['api_calls']} API / {cached['cache_hits']} hits  {status}")
    if incomplete:
        raise SystemExit('Some samples are still unpriced:\n  ' + '\n  '.join(incomplete))
    print('Cache is warm: every sample now completes offline with zero Azure requests.')


if __name__ == '__main__':
    main()

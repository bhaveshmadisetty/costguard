# CostGuard report

## 1. What We Built

CostGuard is a Python CLI and local browser app that consume Terraform plan JSON and estimate the monthly cost change for supported Azure resources. They retrieve actual Azure Retail Prices API meters, filter the pricing model and resource attributes, and store successful responses in SQLite. The shared engine calculates create, delete, update and replacement deltas with decimal arithmetic, using 730 hours for hourly compute and native monthly units for managed disks. The CLI prints a terminal table and budget verdict with CI exit codes; the browser page adds sample selection, file upload, budget controls, resource breakdown and pricing evidence. Live API and offline-cache verification succeeded, while full-process Windows startup misses the 50 ms target and the supported-resource scope remains narrower than a complete Azure bill.

## 2. Detection & Extraction Logic

Walk `resource_changes[]`, using `type`, `address` and `change.actions`. Read `before` for deletion, `after` for creation, and both states for updates and both replacement orderings. An output-only real Terraform plan can omit `resource_changes`; it is accepted as an empty resource list when `format_version` and `planned_values` identify the plan representation.

VM size comes from `size` or legacy `vm_size`; region comes from each state's `location`, lowercased with spaces removed. Price-relevant unknown values under `after_unknown` produce warnings. Linux/Windows resource types and explicit Spot priority select separate pricing identities. Managed disk capacity and redundancy select the exact Premium managed-disk meter. Metadata-only updates map to the same pricing identity, yielding exactly zero delta.

Known free types, data sources and no-op resources are skipped. Unsupported potentially billable types are warned. If either side of an update is unpriced, the entire row is unknown and excluded from known totals, preventing false savings. JSON/structure errors receive a controlled error and exit 2.

## 3. Methods Table

| Decision | Implementation and reason |
|---|---|
| Live API versus static rates | Public Microsoft endpoint; runtime never uses hardcoded prices. Evidence retains selected meters and exact queries. |
| Cache | SQLite `pricing_cache`, keyed by serialized pricing identity, region, currency; records also contain normalized hourly rate, timestamp, original meter JSON and URL. Identity includes service, OS and priority to prevent collisions. |
| Cache-first semantics | Read SQLite before every lookup, fetch only on misses, immediately commit a successful result. No failures are cached as zero. Clear explicitly with `--clear-cache`. |
| Meter filters | Exact service, region, SKU/product, currency and Consumption type; exclude Low Priority and unintended Spot/Windows; validate billing units and zero tier minimum; follow pagination. |
| Regional meters | Do not require `isPrimaryMeterRegion=true`: live eastus D2s_v3 regular Consumption records returned false. All required identity filters still apply. |
| Ambiguity | Multiple matching meter IDs produce an incomplete result. For one meter ID, select the latest effective nonfuture record. |
| Arithmetic | Decimal retail rate times 730 for `1 Hour`; direct monthly rate for `1/Month`. Delta = proposed minus prior. Round only for display. |
| Guardrail | Strictly greater than threshold returns 1; equality passes. Invalid input returns 2. Optional strict mode returns 2 for incomplete pricing unless a known breach already returns 1. |
| Dependencies | Python standard library only, reducing setup time and runtime imports. Portable Terraform/SQLite are verified against publisher checksums. |

`hourly_rate` is a normalized convenience field, including monthly disk rate / 730. Calculations use exact original unit/rate fields from `raw_json`, not this floating-point field.

## 4. Results Matrix

Measured against live Microsoft prices on 2026-09-29. These are synthetic Terraform-format test inputs, not plans captured from Azure infrastructure. Exact responses, fetch timestamps, queries and per-resource calculations are in `evidence/live-results.json`.

| Plan / check | Observed monthly net delta | Outcome |
|---|---:|---|
| Net-new B1s VM, USD | +7.5920 | Pass at 50 threshold; stdin verified |
| VM deletion, USD | -7.5920 | Savings; pass |
| B2s to D2s_v3 upgrade, USD | +39.7120 | Partial delta; pass |
| Fifteen non-billable resources | 0 | No API calls, no crash |
| Tags-only update | 0.0000 | Exact zero |
| Replace B1s with B2s | +22.7760 | Correct replacement delta |
| Downsize B2s to B1s | -22.7760 | Savings |
| Plan A: B1s + P10 LRS disk | +27.3020 | Two live requests on fresh cache |
| Plan B: upgrade plus B1s deletion | +32.1200 | Correct netting |
| Plan A, threshold 20 | +27.3020 | Exit 1 |
| B1s creation, EUR | +6.4970 | Separate live currency lookup |
| Plan A, offline repeated runs | +27.3020 | Two cache hits, zero network calls |

The live USD rates were B1s 0.0104/hour, B2s 0.0416/hour, D2s_v3 0.096/hour, and P10 LRS managed disk 19.71/month. They are observations, not constants in the application.

Unit tests additionally cover wrong-meter rejection, cache persistence/currency/OS/Spot separation, pagination, ambiguous meters, unknown SKUs, network failure, unknown values, malformed inputs, exact budget boundary and strict incompleteness. See `evidence/unit-tests.txt` for the final run.

An actual Terraform 1.16.4 output-only configuration was planned to a binary, converted with `terraform show -json`, piped through the Windows launcher, and returned zero with no cloud calls. Azure create/update/delete fixtures have not been validated against an authenticated Azure-generated plan.

### Cache performance

| Measurement | Runs | Median | Maximum |
|---|---:|---:|---:|
| Fresh Python process, full JSON report, offline cache; excludes `py` launcher | 10 | 248.474 ms | 483.871 ms |
| In-process `main`, argument parsing, file read, SQLite, math, terminal rendering | 20 | 1.799 ms | 2.582 ms |

The strict full-CLI under-50-ms requirement is **not met on this Windows environment**. The under-50-ms processing result is not substituted for the full-process measurement. Zero HTTP calls on the warm path is met. Raw timing samples are in the two evidence JSON files.

## 5. Limitations & Next Steps

1. Reduce executable startup overhead to meet 50 ms end-to-end; benchmark a compiled implementation on the actual judging machine.
2. Support embedded OS disks, additional storage classes, usage-based networking, discounts and more resource families. Current totals cover supported changed resources only.
3. Validate the Azure lifecycle fixtures against real `terraform show -json` output from organizer-provided plans. No Azure resources were provisioned.
4. Cache has explicit refresh, no TTL; old cached rates can differ from current retail prices. Add configurable expiry without violating offline/cache-first behavior.
5. Offline or unknown prices remain unknown. The handout's literal `$0.00` fallback can hide a breach, so default mode continues with `INCOMPLETE` and excluded costs, while `--strict` blocks with exit 2. This is a deliberate documented deviation from displaying invented zero prices.
6. Disk inclusion is ambiguous in the handout; this implementation covers Plan A's P10 Premium disk, using Microsoft's actual monthly unit.
7. Tag grouping uses proposed tags (prior tags for deletion); it is not a full reallocation ledger for moves between teams.
8. Windows and explicit Spot selection have automated fixture tests; the recorded live integration evidence covers regular Linux compute and Premium disk pricing.
9. Transient Azure timeouts and rate limits are retried twice by default. Continued failure produces an incomplete estimate; the verification script uses a separate cache so a failed run does not erase the normal cache.

## 6. How to Run It

No application dependencies need installing with Python 3.11+. On this machine use `py`, because `python` points to the Windows Store shortcut.

For the local web interface, double-click `Run-CostGuard.bat` and keep its terminal open while the browser page is in use. It runs on `127.0.0.1` and calls the same pricing engine. No Azure VM or subscription is needed for the included samples.

```powershell
py -m unittest discover -s tests -v
.\costguard.cmd --plan test-plans/plan-a-small-add.json --strict
.\costguard.cmd --plan test-plans/plan-a-small-add.json --offline --strict
.\costguard.cmd --plan test-plans/plan-b-upgrade-delete.json --max-increase 25 --strict
Get-Content -Raw test-plans/04-hostile-noise.json | .\costguard.cmd
.\costguard.cmd --plan test-plans/01-create.json --currency EUR --json
.\costguard.cmd --plan test-plans/03-upgrade.json --markdown --group-by Team
py scripts/verify_live.py
py scripts/benchmark.py
```

The upgrade/delete command with threshold 25 should exit 1 at the recorded rates. Live prices can change; use observed output, not these sample amounts, as the source of truth. See README for portable-tool setup, real Terraform piping and cache inspection.

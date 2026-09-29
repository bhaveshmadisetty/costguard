# Preparation and demo guide

## Before the session

Confirm whether prewritten implementation code is permitted. The handout explicitly permits environment setup and preparation of test plans; it does not explicitly authorize bringing a completed implementation. Treat this repository as preparation/reference until the organizer confirms the rules.

Run the tests and live demo on the exact laptop and network you will use. Activate the local tools using `. .\activate.ps1`. Understand `costguard.py` well enough to explain its filters, cache identity, units, action matrix and exit codes. Keep the cache warm for an offline backup, but show a fresh lookup when demonstrating live pricing.

## Build priorities (100 marks)

| Area | Marks | Evidence to show |
|---|---:|---|
| Parsing | 20 | Create/delete/upgrade/replacement fixtures, before/after extraction |
| Live pricing | 20 | Cleared-cache lookup and meter attribution in JSON |
| SQLite | 15 | Warm run with 0 API calls, cache inspection |
| Accounting | 15 | Negative savings, zero tags-only delta, correct monthly units |
| Budget gate | 10 | Same plan passes at 50 and exits 1 at 20 |
| Resilience | 10 | Noise, invalid JSON, unknown SKU/network warnings |
| Report | 10 | Results matrix, exact commands, honest limitations |

## Three-hour schedule

- 0:00-0:15: CLI skeleton, file/stdin.
- 0:15-0:45: Extract actions, old/new state, SKU and region.
- 0:45-1:30: Correct live meter selection and SQLite cache.
- 1:30-2:05: Decimal cost math and actual shell exit codes.
- 2:05-2:30: Terminal table, resilience and essential verification.
- 2:30-2:40: Stop features, run checklist, commit and push the working code.
- 2:40-3:00: Finish and commit REPORT.md. Code freeze remains in effect.

## Five-minute judging walkthrough

1. Double-click `Run-CostGuard.bat` to open the local website. Explain the problem: valid infrastructure changes can increase recurring costs before anyone notices.
2. Select Plan A, clear the price cache, set the limit to 50 and run it. Explain why VM price is multiplied by 730 and disk price is already monthly.
3. Turn on "Use cached prices only" and repeat. Show two cache hits and zero API calls.
4. Lower the limit to 20 and run it. Show the red budget verdict. The CLI runs the same engine and returns exit code 1 for this case.
5. Select the Terraform-generated Azure create, upgrade and deletion samples. Explain that Terraform's planner produced them with a mocked AzureRM provider, so no subscription was needed. Then show downsize, tags-only and hostile-noise examples.
6. Expand "Pricing evidence" to show a specific meter ID, Azure query URL, unit and rate.
7. Run `py scripts/benchmark_native.py` and show the complete warm-cache CLI launch time in `evidence/native-benchmark.json`. Open REPORT.md and explain the supported-resource scope.

Use `scripts/demo.ps1` for the repeatable walkthrough. Avoid spending the demo on installation or on features that do not earn rubric marks.

## Explain the hard questions

- **Why not first API result?** Spot, Low Priority, Windows, Dev/Test and reservation meters can return different rates for the same SKU.
- **How is a deletion priced?** Use `before`, with proposed cost zero.
- **How is a replacement priced?** Price both states and subtract; action order does not change steady-state monthly delta.
- **What if new size is unknown?** Mark the estimate incomplete, never turn a missing new price into false savings.
- **Why SQLite?** Persistent local cache between CLI launches; inspectable, no external service.
- **Does it predict the full invoice?** No. It estimates retail recurring cost for supported changed resources under stated usage assumptions.
- **Is it under 50 ms?** The second complete native Windows launch measured 14.711 ms here. Re-run the benchmark on the judging machine; the Python fallback is slower.
- **Are the Azure plans real?** Terraform generated create, update and delete plans for actual AzureRM resource schemas. The provider was mocked, so no live Azure infrastructure was provisioned.

## Submission checklist

Tests pass, live rates verified, cache demonstrated, exit 0/1/2 checked, report honest, all intended files committed, remote push verified. Keep local caches, tools, temporary files, credentials and real sensitive plans out of Git. The original event handout is left local and is not included in the project commit.

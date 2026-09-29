# CostGuard on the Plan

Estimate the monthly cost change in an Azure Terraform plan before deployment. CostGuard reads plan JSON, selects the matching Azure Retail Prices meter, caches it in SQLite, and blocks changes that exceed a budget.

**You do not need an Azure VM or subscription.** The included test plans represent proposed changes; pricing comes from Microsoft's public API. Start with `costguard.cmd --plan test-plans\plan-a-small-add.json --max-increase 20` in Command Prompt to see a budget failure.

For the local website interface, double-click `Run-CostGuard.bat`. It starts a server bound only to your computer and opens the site in your browser. Keep the small terminal window open while using the site; press Ctrl+C there to stop it. The page lets you choose sample plans or upload a `terraform show -json` file, set a monthly limit and currency, run the check, and inspect the Azure meter evidence. It shares the same pricing engine and SQLite cache as the CLI.

```text
Terraform plan JSON -> resource before/after -> SQLite / live Azure prices
                    -> monthly delta -> terminal report -> exit 0 / 1 / 2
```

## Quick start on this Windows workspace

Python 3.11+ is the only runtime dependency. The bundled Windows `costguard.exe` speeds up supported warm-cache CLI runs; cache misses and advanced options use the Python engine. No pip packages, Azure subscription, API key, or cloud deployment is required to run the included fixtures.

```powershell
.\costguard.cmd --plan test-plans/plan-a-small-add.json --strict
.\costguard.cmd --plan test-plans/plan-a-small-add.json --offline --strict
.\costguard.cmd --plan test-plans/plan-a-small-add.json --offline --max-increase 20
$LASTEXITCODE # 1: budget breached
Get-Content -Raw test-plans/04-hostile-noise.json | .\costguard.cmd
```

Use `. .\activate.ps1` to add this project and `tools/bin` to PATH for the current PowerShell session. Then `costguard`, `terraform`, and `sqlite3` work by name. Portable Terraform and SQLite have already been installed in this workspace; on a fresh Windows checkout run `py scripts/install_tools.py` to download and checksum-verify them from the official publishers. This does not change system PATH.

On Linux/macOS use `python3 costguard.py ...`. To install the `costguard` console command in an existing virtual environment, run `python -m pip install .` (the installer may download setuptools; the application has no third-party runtime dependencies).

## Use a real Terraform plan

In your initialized Terraform project:

```powershell
terraform plan '-out=tfplan.binary'
terraform show -json tfplan.binary | costguard --max-increase 50 --strict
```

Check that Terraform itself succeeded before relying on a pipeline result. CostGuard consumes `terraform show -json` output, not the event stream from `terraform plan -json`, and never applies infrastructure.

The included `examples/terraform-smoke` is an actual Terraform configuration with only an output and no cloud resources. Test the real binary-to-JSON-to-CLI pipeline without credentials:

```powershell
terraform '-chdir=examples/terraform-smoke' init -backend=false
terraform '-chdir=examples/terraform-smoke' plan '-out=smoke.tfplan'
terraform '-chdir=examples/terraform-smoke' show -json smoke.tfplan | costguard --strict
```

`examples/azure-mock` contains a real Terraform AzureRM configuration and Terraform test runs that generate create, VM upgrade, and VM delete plans. The provider is mocked, so these plans are produced by Terraform without provisioning Azure resources or requiring credentials. Reproduce the committed, redacted `test-plans/terraform-azure-*.json` fixtures with:

```powershell
terraform '-chdir=examples/azure-mock' init -backend=false
py scripts/capture_terraform_mock.py
.\costguard.cmd --plan test-plans/terraform-azure-create.json --offline --strict
.\costguard.cmd --plan test-plans/terraform-azure-upgrade.json --offline --strict
.\costguard.cmd --plan test-plans/terraform-azure-delete.json --offline --strict
```

Warm those prices once with `py scripts/warm_cache.py` (or any live run) before using `--offline`. The AzureRM test provider is mocked; this verifies Terraform's Azure change-plan shape, while applying to a live Azure subscription remains outside this demo.

## Options and policy

| Option | Behavior |
|---|---|
| `--plan FILE` | Read UTF-8 JSON from a file; otherwise read stdin |
| `--max-increase 50` | Maximum net monthly increase, in selected currency; default 50 |
| `--currency USD/EUR/GBP/INR` | Request currency directly from Azure; isolate cache entries |
| `--cache FILE` | SQLite location; default `pricing_cache.db` in current directory |
| `--clear-cache` | Remove cached rates before running; also works alone |
| `--offline` | Use cached prices only; uncached SKUs display `$0.00` with a warning and an incomplete verdict |
| `--refresh` | Force a live lookup from `https://prices.azure.com/api/retail/prices` and replace saved prices |
| `--auto-refresh-hours 24` | Opt in to refreshing a saved rate after the selected age; disabled by default to preserve the handout's cache-first rule |
| `--strict` | Exit 2 when any changed resource cannot be priced completely |
| `--timeout 10` | HTTP timeout in seconds |
| `--retries 2` | Retry transient API timeouts and 429/5xx responses; default 2 |
| `--markdown` | Render pure Markdown (heading, breakdown table, summary table, verdict, warnings) for pull-request comments; no ASCII banner |
| `--json` | Machine-readable results, exact decimal strings, meter records and query URLs |
| `--group-by Team` | Additional delta totals grouped by a tag |

Exit 0 means the known delta is within budget; exit 1 means it exceeds the budget; exit 2 means invalid input/operational error, or an incomplete estimate under `--strict`. Equality with the threshold passes. A known breach returns 1 even if other resources are unpriced. **Use `--strict` in deployment gates.** Offline uncached SKUs and network failures show the handout's `$0.00` fallback but retain an `INCOMPLETE` verdict; zero is a display default, not a known free price.

The terminal report follows the handout's output contract: a resource breakdown table, a `FINANCIAL SUMMARY` (prior, projected, net impact and cache statistics) and a `POLICY VERDICT`. A breach prints `Status: FAILED (Exceeds budget allowance by +X.XX USD/mo)` followed by `[CIRCUIT BREAKER] CostGuard: Budget threshold breached. Deployment blocked.` The bundled `costguard.exe` prints byte-identical output to the Python engine on the warm-cache path, and an automated test enforces that.

Calculations use decimal arithmetic and unrounded values for the threshold. Display values are rounded to two decimal places only at output. Totals describe changed, supported resources, not the full Azure bill or unchanged estate.

## Supported resources and pricing

- Linux and Windows VMs; legacy VMs when their OS configuration is identifiable. Regular and explicitly declared Spot pricing have separate cache identities.
- Premium LRS/ZRS managed disks mapped from size to P1-P80 capacity tiers. Select the exact managed-disk product and disk meter, excluding page blobs and mount charges. Custom performance tiers, shared disks and on-demand bursting are warned as unsupported.
- Create, delete, update, and both replacement orderings. `no-op`, data reads, and known free resource types are skipped. Unknown/potentially billable resource types produce warnings.
- VM hourly rates are multiplied by 730. Disk `1/Month` rates are already monthly. Rates, meter IDs, units, effective dates, fetch timestamps and source URLs are retained in SQLite and JSON output.
- Consumption-only filtering excludes reservation, Dev/Test, Low Priority, wrong OS, wrong currency and wrong region meters. Spot is excluded unless explicitly requested by the plan. Pagination is followed and ambiguous results are warned rather than guessed.
- A partially priced update is excluded as a whole so a missing new price cannot become a false saving.

VM estimates cover compute meters only: embedded OS disks, network traffic, software licensing beyond the selected VM meter, taxes, discounts and other usage-based charges are outside scope. By default, cached rates are returned immediately until explicitly cleared or refreshed with `--refresh`. Opt-in automatic refresh is available with `--auto-refresh-hours`; it remains off by default to preserve strict cache-first behavior. Tag groups use the proposed tag, or the prior tag for deletion.

## Verification and demo

```powershell
py -m unittest discover -s tests -v
py scripts/warm_cache.py
py scripts/verify_live.py
py scripts/benchmark.py
py scripts/benchmark_native.py
powershell -ExecutionPolicy Bypass -File scripts/demo.ps1
sqlite3 pricing_cache.db "SELECT region,currency,hourly_rate,cached_at FROM pricing_cache;"
```

`warm_cache.py` prices every bundled sample once from the live API into the normal `pricing_cache.db` and then proves a zero-request offline repeat; run it on the demo network before any cached-only demonstration. `verify_live.py` requires network access, clears its own verification cache, records real pricing evidence, and checks zero-network offline repeats. It leaves the normal CLI cache intact. `benchmark.py` measures the Python engine. `benchmark_native.py` measures complete Windows native process launches with a warmed cache and records each sample in `evidence/native-benchmark.json`. The executable can be rebuilt with `py scripts/build_fast.py` if GCC is installed; that script verifies the downloaded SQLite source checksum. `scripts/prepare_plans.py` regenerates the older **synthetic Terraform-format fixtures**. Unit tests use fake rates to test logic, while production pricing and `evidence/live-results.json` use the live API.

See [REPORT.md](REPORT.md) for measured results and [COMPETITION.md](COMPETITION.md) for the preparation and judging walkthrough. The second complete native Windows run meets the 50 ms target on this machine; the Python-only CLI remains slower. Both measurements are recorded separately.

## References

- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Terraform plan JSON format](https://developer.hashicorp.com/terraform/internals/json-format)
- [Terraform binaries](https://releases.hashicorp.com/terraform/1.16.4/)
- [SQLite downloads](https://www.sqlite.org/download.html)

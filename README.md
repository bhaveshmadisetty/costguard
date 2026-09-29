# CostGuard on the Plan

Estimate the monthly cost change in an Azure Terraform plan before deployment. CostGuard reads plan JSON, selects the matching Azure Retail Prices meter, caches it in SQLite, and blocks changes that exceed a budget.

**You do not need an Azure VM or subscription.** The included test plans represent proposed changes; pricing comes from Microsoft's public API. Start with `costguard.cmd --plan test-plans\plan-a-small-add.json --max-increase 20` in Command Prompt to see a budget failure.

```text
Terraform plan JSON -> resource before/after -> SQLite / live Azure prices
                    -> monthly delta -> terminal report -> exit 0 / 1 / 2
```

## Quick start on this Windows workspace

Python 3.11+ is the only runtime dependency. No pip packages, Azure subscription, API key, or cloud deployment is required to run the included fixtures.

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

## Options and policy

| Option | Behavior |
|---|---|
| `--plan FILE` | Read UTF-8 JSON from a file; otherwise read stdin |
| `--max-increase 50` | Maximum net monthly increase, in selected currency; default 50 |
| `--currency USD/EUR/GBP/INR` | Request currency directly from Azure; isolate cache entries |
| `--cache FILE` | SQLite location; default `pricing_cache.db` in current directory |
| `--clear-cache` | Remove cached rates before running; also works alone |
| `--offline` | Use cached prices only |
| `--strict` | Exit 2 when any changed resource cannot be priced completely |
| `--timeout 10` | HTTP timeout in seconds |
| `--retries 2` | Retry transient API timeouts and 429/5xx responses; default 2 |
| `--markdown` | Render a Markdown table |
| `--json` | Machine-readable results, exact decimal strings, meter records and query URLs |
| `--group-by Team` | Additional delta totals grouped by a tag |

Exit 0 means the known delta is within budget; exit 1 means it exceeds the budget; exit 2 means invalid input/operational error, or an incomplete estimate under `--strict`. Equality with the threshold passes. A known breach returns 1 even if other resources are unpriced. **Use `--strict` in deployment gates.** Default mode continues on unknown resources as requested by the handout but prints `INCOMPLETE`, never a misleading complete pass.

Calculations use decimal arithmetic and unrounded values for the threshold. Display values are rounded to two decimal places only at output. Totals describe changed, supported resources, not the full Azure bill or unchanged estate.

## Supported resources and pricing

- Linux and Windows VMs; legacy VMs when their OS configuration is identifiable. Regular and explicitly declared Spot pricing have separate cache identities.
- Premium LRS/ZRS managed disks mapped from size to P1-P80 capacity tiers. Select the exact managed-disk product and disk meter, excluding page blobs and mount charges. Custom performance tiers, shared disks and on-demand bursting are warned as unsupported.
- Create, delete, update, and both replacement orderings. `no-op`, data reads, and known free resource types are skipped. Unknown/potentially billable resource types produce warnings.
- VM hourly rates are multiplied by 730. Disk `1/Month` rates are already monthly. Rates, meter IDs, units, effective dates, fetch timestamps and source URLs are retained in SQLite and JSON output.
- Consumption-only filtering excludes reservation, Dev/Test, Low Priority, wrong OS, wrong currency and wrong region meters. Spot is excluded unless explicitly requested by the plan. Pagination is followed and ambiguous results are warned rather than guessed.
- A partially priced update is excluded as a whole so a missing new price cannot become a false saving.

VM estimates cover compute meters only: embedded OS disks, network traffic, software licensing beyond the selected VM meter, taxes, discounts and other usage-based charges are outside scope. Cache rates remain until explicitly cleared; refresh before a final live demo. Tag groups use the proposed tag, or the prior tag for deletion.

## Verification and demo

```powershell
py -m unittest discover -s tests -v
py scripts/verify_live.py
py scripts/benchmark.py
powershell -ExecutionPolicy Bypass -File scripts/demo.ps1
sqlite3 pricing_cache.db "SELECT region,currency,hourly_rate,cached_at FROM pricing_cache;"
```

`verify_live.py` requires network access, clears its own verification cache, records real pricing evidence, and checks zero-network offline repeats. It leaves the normal CLI cache intact. `benchmark.py` warms a missing Plan A cache from the live API before measuring; if Azure remains unavailable it exits with a clear message. `scripts/prepare_plans.py` regenerates the **synthetic Terraform-format fixtures**; they are not presented as captured Azure deployment plans. Unit tests use explicitly fake rates to test logic, while production pricing and `evidence/live-results.json` use the live API.

See [REPORT.md](REPORT.md) for measured results and [COMPETITION.md](COMPETITION.md) for the preparation and judging walkthrough. Full Windows Python launches currently exceed the handout's 50 ms target; cached processing itself is below it. Both measurements are recorded separately.

## References

- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Terraform plan JSON format](https://developer.hashicorp.com/terraform/internals/json-format)
- [Terraform binaries](https://releases.hashicorp.com/terraform/1.16.4/)
- [SQLite downloads](https://www.sqlite.org/download.html)

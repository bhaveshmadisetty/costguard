$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot)
try {
    Write-Host '1. Live creation: VM + disk (clear cache to prove the API integration)'
    & .\costguard.cmd --plan test-plans/plan-a-small-add.json --clear-cache --strict
    if ($LASTEXITCODE -ne 0) { throw 'Live pricing did not complete.' }
    Write-Host '2. Cached repeat, with network explicitly disabled'
    & .\costguard.cmd --plan test-plans/plan-a-small-add.json --offline --strict
    if ($LASTEXITCODE -ne 0) { throw 'Cache test failed.' }
    Write-Host '3. Same plan with a tighter budget: expect exit 1'
    & .\costguard.cmd --plan test-plans/plan-a-small-add.json --offline --max-increase 20
    if ($LASTEXITCODE -ne 1) { throw 'Budget gate did not block.' }
    Write-Host '4. Upgrade and delete'
    & .\costguard.cmd --plan test-plans/plan-b-upgrade-delete.json --strict
    if ($LASTEXITCODE -ne 0) { throw 'Upgrade test failed.' }
    Write-Host '5. Tags-only change: zero delta'
    & .\costguard.cmd --plan test-plans/05-tags-only.json --offline --strict
    if ($LASTEXITCODE -ne 0) { throw 'Tag test failed.' }
    Write-Host '6. Fifteen free resources through stdin'
    Get-Content -Raw test-plans/04-hostile-noise.json | & .\costguard.cmd --strict
    if ($LASTEXITCODE -ne 0) { throw 'Noise test failed.' }
    Write-Host 'Demo completed successfully.'
} finally { Pop-Location }

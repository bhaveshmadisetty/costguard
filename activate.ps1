$costguardRoot = $PSScriptRoot
$env:PATH = "$costguardRoot;$costguardRoot\tools\bin;$env:PATH"
Write-Host 'CostGuard workspace activated. Try: costguard --plan test-plans/plan-a-small-add.json'

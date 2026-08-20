$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $ProjectRoot "app"
Push-Location $AppRoot
try { python -m pytest -q }
finally { Pop-Location }

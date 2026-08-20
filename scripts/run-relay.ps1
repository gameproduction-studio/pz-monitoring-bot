$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $ProjectRoot "app"
$PzBot = Join-Path $AppRoot ".venv\Scripts\pzbot.exe"
if (-not (Test-Path $PzBot)) { throw "Run scripts\install.ps1 first." }
Push-Location $AppRoot
try { & $PzBot --config config.json relay-monitor }
finally { Pop-Location }

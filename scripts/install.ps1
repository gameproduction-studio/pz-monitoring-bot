$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ModSource = Join-Path $ProjectRoot "mod\PZMonitoringBot"
$ModTarget = Join-Path $env:USERPROFILE "Zomboid\mods\PZMonitoringBot"
$AppRoot = Join-Path $ProjectRoot "app"
$Venv = Join-Path $AppRoot ".venv"

New-Item -ItemType Directory -Force -Path $ModTarget | Out-Null
Copy-Item -Path (Join-Path $ModSource "*") -Destination $ModTarget -Recurse -Force
if (-not (Test-Path $Venv)) { python -m venv $Venv }
& (Join-Path $Venv "Scripts\python.exe") -m pip install -e $AppRoot
$Config = Join-Path $AppRoot "config.json"
if (-not (Test-Path $Config)) {
    Copy-Item -LiteralPath (Join-Path $AppRoot "config.example.json") -Destination $Config
}
Write-Host "Installed: $ModTarget"
Write-Host "Enable the mod, load a save, then run scripts\run-relay.ps1"
Write-Host "Survivor Organizer dashboard: http://127.0.0.1:8765/"

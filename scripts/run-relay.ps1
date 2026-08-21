$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $ProjectRoot "app"
$Runtime = Join-Path $AppRoot "runtime"
$PidFile = Join-Path $Runtime "relay.pid"
$PzBot = Join-Path $AppRoot ".venv\Scripts\pzbot.exe"
if (-not (Test-Path -LiteralPath $PzBot)) { throw "Run scripts\install.ps1 first." }

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
[IO.File]::WriteAllText($PidFile, [string]$PID, [Text.Encoding]::ASCII)

Push-Location $AppRoot
try {
    & $PzBot --config config.json relay-monitor
    if ($LASTEXITCODE -ne 0) { throw "Relay exited with code $LASTEXITCODE." }
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $PidFile) {
        $Recorded = Get-Content -Raw -LiteralPath $PidFile
        if ($Recorded -eq [string]$PID) {
            Remove-Item -LiteralPath $PidFile -Force
        }
    }
}

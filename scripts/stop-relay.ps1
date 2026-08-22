$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $ProjectRoot "app\runtime"
$PidFile = Join-Path $Runtime "relay.pid"

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "pz monitoring bot relay is not running."
    exit 0
}

$RelayPid = [int](Get-Content -Raw -LiteralPath $PidFile)
$Process = Get-CimInstance Win32_Process -Filter "ProcessId=$RelayPid" -ErrorAction SilentlyContinue
if (-not $Process) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "Removed stale relay PID file."
    exit 0
}

$Expected = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "run-relay.ps1"))
if ($Process.CommandLine -notlike "*$Expected*") {
    throw "PID $RelayPid does not belong to pz monitoring bot; refusing to stop it."
}

$TaskKill = Join-Path $env:SystemRoot "System32\taskkill.exe"
& $TaskKill /PID $RelayPid /T /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to stop pz monitoring bot relay process tree (PID $RelayPid)."
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "pz monitoring bot relay stopped."

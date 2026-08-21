$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $ProjectRoot "app\runtime"
$PidFile = Join-Path $Runtime "relay.pid"
$Runner = Join-Path $PSScriptRoot "run-relay.ps1"
$StdOut = Join-Path $Runtime "relay.stdout.log"
$StdErr = Join-Path $Runtime "relay.stderr.log"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

if (Test-Path -LiteralPath $PidFile) {
    $ExistingPid = [int](Get-Content -Raw -LiteralPath $PidFile)
    $Existing = Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue
    if ($Existing) {
        Write-Host "pz monitoring bot relay is already running (PID $ExistingPid)."
        exit 0
    }
    Remove-Item -LiteralPath $PidFile -Force
}

$PowerShell = (Get-Command powershell.exe).Source
$Arguments = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $Runner + '"')
)
$Start = @{
    FilePath = $PowerShell
    ArgumentList = $Arguments
    WorkingDirectory = $ProjectRoot
    WindowStyle = "Hidden"
    RedirectStandardOutput = $StdOut
    RedirectStandardError = $StdErr
    PassThru = $true
}
$Process = Start-Process @Start

[IO.File]::WriteAllText($PidFile, [string]$Process.Id, [Text.Encoding]::ASCII)
Write-Host "pz monitoring bot relay started (PID $($Process.Id))."

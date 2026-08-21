$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $ProjectRoot "app"
$PzBot = Join-Path $AppRoot ".venv\Scripts\pzbot.exe"

if (-not (Test-Path -LiteralPath $PzBot)) {
    & (Join-Path $PSScriptRoot "install.ps1")
}

$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "pz monitoring bot.lnk"
$Starter = Join-Path $PSScriptRoot "start-relay.ps1"
$PowerShell = (Get-Command powershell.exe).Source

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Starter + '"'
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Project Zomboid resource monitor relay"
$Shortcut.Save()

& $Starter
Write-Host "Autostart installed: $ShortcutPath"
Write-Host "From now on, use the in-game update command; relay and GitHub sync are automatic."

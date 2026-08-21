$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "stop-relay.ps1")
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "pz monitoring bot.lnk"
if (Test-Path -LiteralPath $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
}
Write-Host "pz monitoring bot autostart removed."

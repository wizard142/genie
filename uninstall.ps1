# genie uninstaller for Windows
# Run in PowerShell:   powershell -ExecutionPolicy Bypass -File uninstall.ps1
$ErrorActionPreference = "SilentlyContinue"

Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "Programs\genie")
Remove-Item -Force (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\genie.cmd")

Write-Host ""
Write-Host "  genie is gone. (your config in $env:APPDATA\genie was kept -"
Write-Host "  delete that folder too if you want a clean slate.)"
Write-Host ""

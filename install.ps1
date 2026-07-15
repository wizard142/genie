# genie installer for Windows 10/11
# Run in PowerShell:   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  installing genie..."
Write-Host ""

# --- find a real Python 3 (not the Microsoft Store stub) ---
function Find-Python {
    foreach ($c in @("py", "python", "python3")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            $v = & $c -c "import sys; print(sys.version_info[0])" 2>$null
            if ("$v".Trim() -eq "3") { return $c }
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "  x Python 3 is required but not found. Install it with:"
    Write-Host "      winget install Python.Python.3.12"
    Write-Host "    then run this installer again."
    exit 1
}

# --- copy genie.py to a stable home ---
$dest = Join-Path $env:LOCALAPPDATA "Programs\genie"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $PSScriptRoot "genie.py") (Join-Path $dest "genie.py") -Force
Write-Host "  + installed genie.py to $dest"

# --- drop a 'genie' command onto the user PATH ---
# %LOCALAPPDATA%\Microsoft\WindowsApps is user-writable and already on PATH
$shimDir = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
$shim = Join-Path $shimDir "genie.cmd"
"@echo off`r`n$py `"$dest\genie.py`" %*" | Set-Content -Path $shim -Encoding Ascii
Write-Host "  + created the 'genie' command"

Write-Host ""
Write-Host "  next steps (open a NEW terminal first):"
Write-Host "    genie setup     # connect a free AI provider (2 min)"
Write-Host "    genie how much disk space do i have"
Write-Host ""
Write-Host "  note: on Windows you type 'genie' without the slash."
Write-Host ""

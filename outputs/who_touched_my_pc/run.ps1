$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python -ErrorAction SilentlyContinue

if (-not $Python) {
  Write-Host "Python was not found. Install Python 3.11+ and add python.exe to PATH."
  exit 1
}

Set-Location $ScriptDir
$VersionCheck = & python --version 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "The python command is not usable. It may be the Microsoft Store placeholder. Install Python 3.11+ and retry."
  exit 1
}

python -m pip install -r requirements.txt
python .\app.py

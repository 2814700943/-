$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python -ErrorAction SilentlyContinue

if (-not $Python) {
  Write-Host "Python was not found. Install Python 3.11+ and add python.exe to PATH."
  exit 1
}

Set-Location $ScriptDir
python --version
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller `
  -y `
  --onefile `
  --noconsole `
  --clean `
  --name "谁动了我的电脑" `
  .\app.py

Write-Host "EXE created at: $ScriptDir\dist\谁动了我的电脑.exe"

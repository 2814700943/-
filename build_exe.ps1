$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root "outputs\who_touched_my_pc"

Set-Location $AppDir
& .\build_exe.ps1

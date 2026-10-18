$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$nodeDirectory = Get-ChildItem (Join-Path $ProjectRoot '.tools') -Directory -Filter 'node-*-win-x64' -ErrorAction SilentlyContinue | Where-Object { (Test-Path (Join-Path $_.FullName 'node.exe')) -and (Test-Path (Join-Path $_.FullName 'npm.cmd')) } | Sort-Object Name -Descending | Select-Object -First 1
if ($nodeDirectory) { $env:Path = $nodeDirectory.FullName + ';' + $env:Path }
$env:CARGO_HOME = Join-Path $ProjectRoot '.tools/cargo'
$env:RUSTUP_HOME = Join-Path $ProjectRoot '.tools/rustup'
$env:Path = (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:Path
$Python = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path $Python)) { throw 'Run scripts/setup.ps1 first' }

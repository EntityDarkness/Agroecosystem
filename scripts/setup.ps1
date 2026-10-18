$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force .tools | Out-Null
if (-not (Test-Path .venv/Scripts/python.exe)) { python -m venv .venv; if ($LASTEXITCODE) { throw 'Cannot create venv' } }
& .venv/Scripts/python.exe -m pip install --timeout 180 --no-compile -r python_service/requirements.lock.txt
if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
$nodeInstall = Get-ChildItem .tools -Directory -Filter 'node-*-win-x64' | Where-Object { (Test-Path (Join-Path $_.FullName 'node.exe')) -and (Test-Path (Join-Path $_.FullName 'npm.cmd')) } | Select-Object -First 1
if (-not $nodeInstall) {
    Invoke-WebRequest https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt -OutFile .tools/node-shasums.txt
    $line = (Get-Content .tools/node-shasums.txt | Select-String 'win-x64.zip').Line
    $parts = $line.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
    Invoke-WebRequest ('https://nodejs.org/dist/latest-v22.x/' + $parts[1]) -OutFile (Join-Path .tools $parts[1])
    if ((Get-FileHash (Join-Path .tools $parts[1]) -Algorithm SHA256).Hash -ne $parts[0]) { throw 'Node.js: SHA256 mismatch' }
    Expand-Archive -LiteralPath (Join-Path .tools $parts[1]) -DestinationPath .tools -Force
}
. $PSScriptRoot/env.ps1
if (-not (Test-Path .tools/cargo/bin/rustc.exe)) {
    Invoke-WebRequest https://win.rustup.rs/x86_64 -OutFile .tools/rustup-init.exe
    & .tools/rustup-init.exe -y --no-modify-path --profile minimal --default-toolchain stable
    if ($LASTEXITCODE) { throw 'Rust installation failed' }
}
Push-Location AgroecosystemTauri
try { npm.cmd ci; if ($LASTEXITCODE) { throw 'npm dependency installation failed' } } finally { Pop-Location }

param([switch]$SkipSidecar)
. $PSScriptRoot/env.ps1
Set-Location $ProjectRoot
& $Python python_service/sync_models.py
if ($LASTEXITCODE) { throw 'ML contract validation failed' }
if (-not $SkipSidecar) {
    & $Python python_service/build.py --target windows
    if ($LASTEXITCODE) { throw 'Sidecar build failed' }
}
$triple = (& rustc --print host-tuple).Trim()
if ($LASTEXITCODE) { throw 'Cannot determine Rust target triple' }
if ($triple -ne 'x86_64-pc-windows-msvc') { throw 'This build script supports Windows x64 only' }
New-Item -ItemType Directory -Force AgroecosystemTauri/src-tauri/binaries | Out-Null
Copy-Item -LiteralPath "python_service/dist/python_service-$triple.exe" -Destination AgroecosystemTauri/src-tauri/binaries -Force
& $Python python_service/tests/frozen.py "python_service/dist/python_service-$triple.exe"
if ($LASTEXITCODE) { throw 'Frozen sidecar validation failed' }
Push-Location AgroecosystemTauri
try {
    npm.cmd run desktop:build
    if ($LASTEXITCODE) { throw 'Tauri build failed' }
} finally { Pop-Location }
New-Item -ItemType Directory -Force artifacts | Out-Null
Copy-Item AgroecosystemTauri/src-tauri/target/release/bundle/nsis/*.exe artifacts -Force
Get-ChildItem artifacts/*.exe | Get-FileHash -Algorithm SHA256 | Format-Table -AutoSize

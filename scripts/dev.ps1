. $PSScriptRoot/env.ps1
Set-Location (Join-Path $ProjectRoot 'AgroecosystemTauri')
npm.cmd run desktop:dev
if ($LASTEXITCODE) { throw 'Tauri startup failed' }

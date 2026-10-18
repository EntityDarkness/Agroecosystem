. $PSScriptRoot/env.ps1
Set-Location $ProjectRoot
& rustc --test AgroecosystemTauri/src-tauri/src/model_store.rs -o .tools/model-store-tests.exe
if ($LASTEXITCODE) { throw 'Model migration test compilation failed' }
& .tools/model-store-tests.exe
if ($LASTEXITCODE) { throw 'Model migration test failed' }

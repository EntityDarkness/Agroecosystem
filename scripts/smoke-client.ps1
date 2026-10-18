. $PSScriptRoot/env.ps1
Set-Location $ProjectRoot
$clientPath = Join-Path $ProjectRoot 'AgroecosystemTauri/src-tauri/target/release/agroecosystemtauri.exe'
$servicePath = Join-Path $ProjectRoot 'AgroecosystemTauri/src-tauri/target/release/python_service.exe'
$dataPath = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'com.agroecosystem.agroecosystem/wtp-data'
$logPath = Join-Path $dataPath 'service.log'
$launchTime = Get-Date
$clientProcess = Start-Process -FilePath $clientPath -PassThru -WindowStyle Hidden
try {
    $deadline = (Get-Date).AddSeconds(180)
    $started = $false
    while ((Get-Date) -lt $deadline) {
        $clientProcess.Refresh()
        if ($clientProcess.HasExited) { throw 'Client exited before its frontend connected to the sidecar' }
        if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).LastWriteTime -ge $launchTime) {
            $logStream = [IO.FileStream]::new($logPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
            $logReader = [IO.StreamReader]::new($logStream)
            try { $logText = $logReader.ReadToEnd() } finally { $logReader.Dispose() }
            if ($logText -match 'GET /meta HTTP/1.1" 200' -and $logText -match 'GET /dataset HTTP/1.1" 200') { $started = $true; break }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $started) { throw ('Client startup timeout. Log: ' + $logPath) }
    $before = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $servicePath }).Count
    $secondProcess = Start-Process -FilePath $clientPath -PassThru -WindowStyle Hidden
    if (-not $secondProcess.WaitForExit(10000)) { & taskkill /PID $secondProcess.Id /T /F | Out-Null; throw 'Second client instance did not exit' }
    $after = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $servicePath }).Count
    if ($before -ne $after) { throw 'Second instance started another sidecar' }
    if (-not (Test-Path -LiteralPath (Join-Path $dataPath '.bundled-models.sha256'))) { throw 'Bundled model revision was not recorded' }
    Write-Output 'Native client: frontend IPC, health/meta/dataset, model initialization and single-instance checks OK'
    Write-Output ('Data: ' + $dataPath)
} finally {
    $clientProcess.Refresh()
    if (-not $clientProcess.HasExited) { & taskkill /PID $clientProcess.Id /T /F | Out-Null }
}

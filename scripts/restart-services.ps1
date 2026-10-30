param([ValidateRange(5,600)][int]$TimeoutSeconds = 25)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

function Get-CurrentServicePids {
  $api = @(Get-Listeners 8100)
  $dashboard = @(Get-Listeners 3100)
  $py = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
  $pubRaw = & $py (Join-Path $PSScriptRoot 'publication-worker.py') --status 2>$null
  $pub = $null; if ($pubRaw) { try { $pub=($pubRaw -join "`n")|ConvertFrom-Json } catch { } }
  $researchRaw = & $py (Join-Path $PSScriptRoot 'service-runtime-status.py') --worker research_worker 2>$null
  $research = $null; if ($researchRaw) { try { $research=($researchRaw -join "`n")|ConvertFrom-Json } catch { } }
  return [ordered]@{ api=if($api.Count -eq 1){[int]$api[0]}else{$null}; dashboard=if($dashboard.Count -eq 1){[int]$dashboard[0]}else{$null}; research_worker=if($research.ready){[int]$research.process_id}else{$null}; publication_worker=if($pub.heartbeat_fresh){[int]$pub.heartbeat.process_id}else{$null} }
}

$requestId = [guid]::NewGuid().ToString('N')
$before = Get-CurrentServicePids
Write-LifecycleLog 'all_services' 'restart_started' "request_id=$requestId old_pids=$($before|ConvertTo-Json -Compress)"
try {
  & (Join-Path $PSScriptRoot 'stop-services.ps1') -TimeoutSeconds $TimeoutSeconds
  $afterStop = Get-CurrentServicePids
  $remaining = @($afterStop.GetEnumerator() | Where-Object { $null -ne $_.Value })
  if ($remaining.Count) { throw "Restart aborted because old services remain: $(($remaining|ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ',')." }
  foreach ($port in @(3100,8100)) { if (@(Get-Listeners $port).Count) { throw "Restart aborted: TCP $port is not free." } }
  Write-LifecycleLog 'all_services' 'restart_stop_verified' "request_id=$requestId old_pids=$($before|ConvertTo-Json -Compress)"

  $deadline=(Get-Date).AddSeconds(300)
  $dbReady=$false
  do {
    $postgres=@(Get-Service -Name 'postgresql-*' -ErrorAction SilentlyContinue | Where-Object Status -eq 'Running')
    if ($postgres.Count) {
      $raw=& (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'service-runtime-status.py') --database-ready 2>$null
      if ($LASTEXITCODE -eq 0 -and $raw) { try { $check=($raw -join "`n")|ConvertFrom-Json; if($check.ready -and $check.database -eq 'woori_blog_agent'){$dbReady=$true;break} } catch{} }
    }
    Start-Sleep -Seconds 5
  } while ((Get-Date) -lt $deadline)
  if (-not $dbReady) { throw 'Restart aborted: PostgreSQL project database did not become ready within 300 seconds.' }
  Write-LifecycleLog 'database' 'ready_before_restart_start' "request_id=$requestId database=woori_blog_agent"

  & (Join-Path $PSScriptRoot 'start-services.ps1') -ExplicitUserStart
  if (-not (Test-LoopbackHttp 'http://127.0.0.1:8100/health' 10)) { throw 'API health check did not return HTTP 200.' }
  if (-not (Test-LoopbackHttp 'http://127.0.0.1:3100/research' 10)) { throw 'Dashboard health check did not return HTTP 200.' }
  $after=Get-CurrentServicePids
  foreach($name in @('api','dashboard','research_worker','publication_worker')) {
    if(-not $after[$name]) { throw "$name has no fresh service PID after restart." }
    if($before[$name] -and [int]$before[$name] -eq [int]$after[$name]) { throw "$name PID did not change ($($before[$name]))." }
  }
  $pubRaw=& (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'publication-worker.py') --status 2>$null
  $pub=($pubRaw -join "`n")|ConvertFrom-Json
  if(-not $pub.heartbeat_fresh -or $pub.worker_execution_mode -ne 'operations-scheduled-auto-and-manual-and-trends') { throw 'Publication Worker heartbeat or execution mode verification failed.' }
  $researchRaw=& (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'service-runtime-status.py') --worker research_worker 2>$null
  $research=($researchRaw -join "`n")|ConvertFrom-Json
  if(-not $research.ready -or [int]$research.process_id -ne [int]$after.research_worker) { throw 'Research Worker heartbeat verification failed.' }
  Write-LifecycleLog 'all_services' 'restart_complete' "request_id=$requestId old_pids=$($before|ConvertTo-Json -Compress) new_pids=$($after|ConvertTo-Json -Compress) publication_mode=scheduled-auto-manual-trends"
  Write-Output 'Restart verified: old PIDs exited, ports were released, PostgreSQL was ready, HTTP health returned 200, and both Worker heartbeats are fresh.'
  [pscustomobject]@{ RequestId=$requestId; OldPids=$before; NewPids=$after; ApiHttp=200; DashboardHttp=200; PublicationMode=$pub.worker_execution_mode }
} catch {
  $detail=([string]$_.Exception.Message -replace '[\r\n]+',' ') -replace '\s+',' '
  Write-LifecycleLog 'all_services' 'restart_failed' "request_id=$requestId error_type=$($_.Exception.GetType().Name) detail=$($detail.Substring(0,[Math]::Min(300,$detail.Length)))"
  throw
}

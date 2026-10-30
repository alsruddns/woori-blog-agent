. (Join-Path $PSScriptRoot 'server-common.ps1')
$manifest = Read-ServerManifest
$table = Get-ProcessTable
foreach ($name in @('dashboard', 'api')) {
  $service = $script:Services[$name]
  $listeners = Get-Listeners $service.Port
  if (-not $listeners.Count) { [pscustomobject]@{ Service=$name; Port=$service.Port; State='stopped'; PID=$null; ProjectOwned=$false; AppliedCommit=if ($manifest.services[$name]) { $manifest.services[$name].applied_commit } else { $null }; LogPath=(Join-Path $script:RuntimeDir "logs\$name.stderr.log") }; continue }
  foreach ($pidValue in $listeners) {
    $proc = $table | Where-Object Id -eq ([int]$pidValue) | Select-Object -First 1
    $record = $manifest.services[$name]
    $owned = $false
    $runnerInfo = if ($record) { $table | Where-Object Id -eq ([int]$record.pid) | Select-Object -First 1 } else { $null }
    $managedRunner = Test-RecordedRunner $runnerInfo $record $name
    if ($proc -and $record -and $managedRunner -and (Test-DescendantOf $table $proc.Id ([int]$record.pid))) { $owned = $true }
    elseif ($proc -and $proc.CommandLine -and $proc.CommandLine.IndexOf($script:ProjectRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0) { $owned = $true }
    [pscustomobject]@{ Service=$name; Port=$service.Port; State='listening'; PID=[int]$pidValue; Executable=$proc.Path; StartedUtc=(Get-ProcessStarted ([int]$pidValue)); ProjectOwned=$owned; AppliedCommit=if ($manifest.services[$name]) { $manifest.services[$name].applied_commit } else { $null }; LogPath=if ($manifest.services[$name] -and $manifest.services[$name].log_path) { $manifest.services[$name].log_path } else { Join-Path $script:RuntimeDir "logs\$name.stderr.log" } }
  }
}

$table = Get-ProcessTable
$researchWorkerStatus = $null
try {
  $raw = & (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') `
    (Join-Path $PSScriptRoot 'service-runtime-status.py') --worker research_worker 2>$null
  if ($raw) { $researchWorkerStatus = ($raw -join "`n") | ConvertFrom-Json }
} catch { Write-Warning 'Research Worker heartbeat could not be read; process inventory remains read-only.' }
$publicationWorkerStatus = $null
try {
  $raw = & (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') `
    (Join-Path $PSScriptRoot 'publication-worker.py') --status 2>$null
  if ($LASTEXITCODE -eq 0 -and $raw) { $publicationWorkerStatus = ($raw -join "`n") | ConvertFrom-Json }
} catch { Write-Warning 'Publication Worker heartbeat could not be read; process inventory remains read-only.' }

foreach ($name in @('worker','evaluation_worker','publication_worker')) {
  $knownPort = if ($script:Services.ContainsKey($name)) { [int]$script:Services[$name].Port } else { $null }
  $matched = @(Get-CheckoutServiceProcesses $table $name)
  if ($name -eq 'worker' -and $researchWorkerStatus -and $researchWorkerStatus.process_id) {
    $heartbeatPid = [int]$researchWorkerStatus.process_id
    $matched = @($matched | Where-Object {
      ([int]$_.Id -eq $heartbeatPid) -or
      -not (Test-DescendantOf $table $heartbeatPid ([int]$_.Id))
    })
  }
  if ($name -eq 'publication_worker' -and $publicationWorkerStatus -and $publicationWorkerStatus.heartbeat.process_id) {
    $heartbeatPid = [int]$publicationWorkerStatus.heartbeat.process_id
    $matched = @($matched | Where-Object {
      ([int]$_.Id -eq $heartbeatPid) -or
      -not (Test-DescendantOf $table $heartbeatPid ([int]$_.Id))
    })
  }
  $allMatched = @($matched)
  $matched = @($allMatched | Where-Object {
    $candidate = $_
    -not @($allMatched | Where-Object { ([int]$_.Id -ne [int]$candidate.Id) -and (Test-DescendantOf $table ([int]$_.Id) ([int]$candidate.Id)) }).Count
  })
  foreach ($proc in $matched) {
    $ports = @()
    try {
      $ports = @(Get-NetTCPConnection -OwningProcess ([int]$proc.Id) -State Listen -ErrorAction Stop |
        Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
    } catch {
      if ($_.FullyQualifiedErrorId -notlike 'CmdletizationQuery_NotFound,*') {
        Write-Warning "Could not inspect listener ports for checkout PID $($proc.Id)."
      }
    }
    $state = if ($null -ne $knownPort -and $ports -contains $knownPort) { 'listening' }
      elseif ($ports.Count) { 'listening-on-alternate-port' }
      else { 'checkout-process-detected' }
    [pscustomobject]@{
      Service=$name; Port=($ports -join ','); State=$state; PID=[int]$proc.Id
      Executable=$proc.Path; StartedUtc=(Get-ProcessStarted ([int]$proc.Id)); ProjectOwned=$true
      ExecutionMode=if ($name -eq 'publication_worker' -and $proc.CommandLine -match '--operations-scheduled-auto-and-manual-and-trends') { 'scheduled-auto-manual-trends' }
        elseif ($name -eq 'publication_worker' -and $proc.CommandLine -match '--operations-scheduled-auto-and-manual') { 'scheduled-auto-and-manual' }
        elseif ($name -eq 'publication_worker' -and $proc.CommandLine -match '--operations-scheduled-auto') { 'scheduled-auto' }
        elseif ($name -eq 'publication_worker' -and $proc.CommandLine -match '--operations-manual-confirmed') { 'manual-confirmed' }
        elseif ($name -eq 'publication_worker' -and $proc.CommandLine -match '--operations-mock-only') { 'mock-only' }
        elseif ($name -eq 'worker') { 'research' } else { $null }
      HeartbeatState=if ($name -eq 'worker' -and $researchWorkerStatus) { if ($researchWorkerStatus.ready) { 'fresh' } else { $researchWorkerStatus.state } }
        elseif ($name -eq 'publication_worker' -and $publicationWorkerStatus) { if ($publicationWorkerStatus.heartbeat_fresh) { 'fresh' } else { [string]$publicationWorkerStatus.heartbeat.status } }
        else { $null }
      AppliedCommit=if ($manifest.services[$name]) { $manifest.services[$name].applied_commit } else { $null }
      LogPath=if ($manifest.services[$name]) { $manifest.services[$name].log_path } else { $null }
    }
  }
}

if ($researchWorkerStatus) {
  [pscustomobject]@{
    Service='research_worker_heartbeat'
    State=if ($researchWorkerStatus.ready) { 'running' } else { [string]$researchWorkerStatus.state }
    PID=$researchWorkerStatus.process_id; LastSeenUtc=$researchWorkerStatus.last_seen_at
    HeartbeatAgeSeconds=$researchWorkerStatus.age_seconds; LastError=$researchWorkerStatus.last_error_category
    AppliedCommit=if ($manifest.services['research_worker']) { $manifest.services['research_worker'].applied_commit } else { $null }
    LogPath=if ($manifest.services['research_worker']) { $manifest.services['research_worker'].log_path } else { (Join-Path $script:RuntimeDir 'logs\research-worker.stderr.log') }
  }
}

try {
  $workerOutput = & (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') `
    (Join-Path $script:ProjectRoot 'scripts\publication-worker.py') --status
  if ($LASTEXITCODE -eq 0 -and $workerOutput) {
    $workerStatus = ($workerOutput -join "`n") | ConvertFrom-Json
    $workerProcess = $table | Where-Object Id -eq ([int]$workerStatus.heartbeat.process_id) | Select-Object -First 1
    $executionMode = if ($workerProcess.CommandLine -match '--operations-scheduled-auto-and-manual-and-trends') { 'scheduled-auto-manual-trends' }
      elseif ($workerProcess.CommandLine -match '--operations-scheduled-auto-and-manual') { 'scheduled-auto-manual' }
      elseif ($workerProcess.CommandLine -match '--operations-manual-confirmed') { 'manual-confirmed' }
      elseif ($workerProcess.CommandLine -match '--operations-scheduled-auto') { 'scheduled-auto' }
      elseif ($workerProcess.CommandLine -match '--operations-mock-only') { 'mock-only' }
      else { 'unknown' }
    [pscustomobject]@{
      Service='publication_worker_heartbeat'
      State=if ($workerStatus.heartbeat_fresh) { 'running' } elseif ($workerStatus.heartbeat) { $workerStatus.heartbeat.status } else { 'not_started' }
      PID=$workerStatus.heartbeat.process_id
      LastSeenUtc=$workerStatus.heartbeat.last_seen_at
      MockQueued=$workerStatus.queue.mock_queued
      MockDue=$workerStatus.queue.mock_due
      LiveQueued=$workerStatus.queue.live_queued
      LiveDue=$workerStatus.queue.live_due
      LastJobId=$workerStatus.last_job.id
      LastJobState=$workerStatus.last_job.publication_state
      LastJobError=$workerStatus.last_job.last_error_category
      IdleReason=$workerStatus.idle_reason_if_processed_false
      ExecutionMode=$executionMode
      AutoMode=$workerStatus.global_mode.configured_mode
      AutoPolicyActive=$workerStatus.auto_policy_active
      AppliedCommit=if ($manifest.services['publication_worker']) { $manifest.services['publication_worker'].applied_commit } else { $null }
      LogPath=if ($manifest.services['publication_worker']) { $manifest.services['publication_worker'].log_path } else { (Join-Path $script:RuntimeDir 'logs\publication-worker.stderr.log') }
    }
  } else {
    Write-Warning 'Publication Worker heartbeat and queue status could not be read; inspect local DB availability.'
  }
} catch {
  Write-Warning 'Publication Worker heartbeat and queue status could not be read; no process was changed.'
}

$autoTask = Get-ScheduledTask -TaskName 'WooriBlogAgent-Worker' -ErrorAction SilentlyContinue
if ($autoTask) {
  $actionPath = [string]$autoTask.Actions[0].Arguments
  $expected = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'start-services.ps1'))
  [pscustomobject]@{
    Service='windows_logon_autostart'; TaskName=$autoTask.TaskName; State=$autoTask.State
    Enabled=[bool]$autoTask.Settings.Enabled
    LogonTrigger=[bool](@($autoTask.Triggers | Where-Object { $_.CimClass.CimClassName -like '*LogonTrigger*' }).Count)
    ActionMatchesProject=($actionPath.Replace('/','\').IndexOf($expected.Replace('/','\'),[StringComparison]::OrdinalIgnoreCase) -ge 0)
    LastRunTime=(Get-ScheduledTaskInfo -TaskName $autoTask.TaskName).LastRunTime
    LastTaskResult=(Get-ScheduledTaskInfo -TaskName $autoTask.TaskName).LastTaskResult
    LogPath=(Join-Path $script:RuntimeDir 'logs\service-lifecycle.log')
  }
} else {
  [pscustomobject]@{ Service='windows_logon_autostart'; TaskName='WooriBlogAgent-Worker'; State='not_registered'; Enabled=$false; LogonTrigger=$false; ActionMatchesProject=$false; LogPath=(Join-Path $script:RuntimeDir 'logs\service-lifecycle.log') }
}

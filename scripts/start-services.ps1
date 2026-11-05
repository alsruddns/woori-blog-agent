param(
  [ValidateRange(30,900)][int]$DatabaseTimeoutSeconds = 300,
  [ValidateRange(1,10)][int]$ServiceAttempts = 3,
  [ValidateSet('mock-only','scheduled-auto','manual-confirmed','scheduled-auto-manual','scheduled-auto-manual-trends')][string]$PublicationMode = 'manual-confirmed',
  [switch]$ExplicitUserStart,
  [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

function Test-ValidatedStartupSource([string]$ValidatedCommit, [string]$Head) {
  if ($ValidatedCommit -notmatch '^[0-9a-f]{40}$' -or $Head -notmatch '^[0-9a-f]{40}$') { return $false }
  if ($ValidatedCommit -ceq $Head) { return $true }
  & git -C $script:ProjectRoot merge-base --is-ancestor $ValidatedCommit $Head
  if ($LASTEXITCODE -ne 0) { return $false }
  $paths = @(& git -C $script:ProjectRoot diff --name-only $ValidatedCommit $Head)
  if ($LASTEXITCODE -ne 0) { throw 'Could not compare startup source with its validated commit.' }
  # Documentation-only descendants do not invalidate already tested binaries.
  # Every script, configuration, dependency and application change still blocks.
  $runtimeChanges = @($paths | Where-Object { $_ -notmatch '^docs/|^(README|CHANGELOG)\.md$' })
  return $runtimeChanges.Count -eq 0
}

function Invoke-StartupProcess([string]$ScriptPath, [string[]]$ChildArguments) {
  # Native pipelines can stay open through a detached grandchild's inherited
  # handles. Redirect all streams and wait for this launcher PID, not its tree.
  $logs = Get-ProjectLogDirectory
  $requestId = [guid]::NewGuid().ToString('N')
  $stdout = Join-Path $logs "startup-child-$requestId.stdout.log"
  $stderr = Join-Path $logs "startup-child-$requestId.stderr.log"
  $stdin = Join-Path $logs "startup-child-$requestId.stdin"
  [IO.File]::WriteAllText($stdin,'')
  $arguments = @('-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',('"'+$ScriptPath+'"')) + $ChildArguments
  $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -WorkingDirectory $script:ProjectRoot -RedirectStandardInput $stdin -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $null = $child.Handle
  if (-not $child.WaitForExit(90000)) {
    throw "Startup child PID $($child.Id) did not exit within 90 seconds; left untouched. Inspect $stderr."
  }
  if ($null -eq $child.ExitCode) { throw "Startup child PID $($child.Id) exited without a verifiable exit code." }
  return $child.ExitCode
}

function Invoke-StartupChild([string[]]$ChildArguments) {
  # A separate PowerShell process gives exit/return a local boundary. Never
  # interpret the last Git/readiness command's stale LASTEXITCODE as startup.
  $childExit = Invoke-StartupProcess (Join-Path $PSScriptRoot 'start.ps1') $ChildArguments
  if ($childExit -ne 0) { throw "Startup child failed (exit=$childExit service=$($ChildArguments[1]))." }
}

function Get-StartupMutexName {
  $hash = [Security.Cryptography.SHA256]::Create()
  try {
    $identity = $script:ProjectRoot.ToLowerInvariant() + '|' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $digest = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($identity))).Replace('-','')
    return 'Global\WooriBlogAgent-Startup-' + $digest
  } finally { $hash.Dispose() }
}

function Invoke-ReadinessJson([string[]]$Arguments) {
  $python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
  $raw = & $python (Join-Path $PSScriptRoot 'service-runtime-status.py') @Arguments 2>$null
  $exit = $LASTEXITCODE
  if (-not $raw) { return @{ exit=$exit; value=$null } }
  try { return @{ exit=$exit; value=(($raw -join "`n") | ConvertFrom-Json) } }
  catch { return @{ exit=$exit; value=$null } }
}

function Wait-PostgresReady {
  $deadline = (Get-Date).AddSeconds($DatabaseTimeoutSeconds)
  $lastCategory = 'not_checked'
  do {
    $postgres = @(Get-Service -Name 'postgresql-*' -ErrorAction SilentlyContinue | Where-Object Status -eq 'Running')
    if ($postgres.Count) {
      $check = Invoke-ReadinessJson @('--database-ready')
      if ($check.exit -eq 0 -and $check.value.ready -and $check.value.database -eq 'woori_blog_agent') { return $true }
      if ($check.value.reason) { $lastCategory = [string]$check.value.reason }
      elseif ($check.value) { $lastCategory = 'database_identity_mismatch' }
      else { $lastCategory = 'database_connection_unavailable' }
    } else { $lastCategory = 'postgresql_service_not_running' }
    Start-Sleep -Seconds 5
  } while ((Get-Date) -lt $deadline)
  Write-LifecycleLog 'startup' 'database_wait_failed' "timeout_seconds=$DatabaseTimeoutSeconds reason=$lastCategory"
  throw "PostgreSQL/project database was not ready within $DatabaseTimeoutSeconds seconds ($lastCategory)."
}

function Ensure-HttpService([string]$Name, [int]$Port, [string]$HealthUrl) {
  for ($attempt=1; $attempt -le $ServiceAttempts; $attempt++) {
    $listeners = @(Get-Listeners $Port)
    if ($listeners.Count) {
      $table = Get-ProcessTable
      $owners = @($listeners | ForEach-Object { $table | Where-Object Id -eq ([int]$_) | Select-Object -First 1 })
      $owned = @($owners | Where-Object { Test-ExactCheckoutServiceProcess $_ $Name })
      if ($owned.Count -ne $listeners.Count) {
        Write-LifecycleLog $Name 'port_conflict' "port=$Port owner_pids=$($listeners -join ',')"
        throw "$Name port $Port is occupied by a process not verified as this checkout. It was left untouched."
      }
      if (Test-LoopbackHttp $HealthUrl 5) {
        Write-LifecycleLog $Name 'already_ready' "port=$Port owner_pids=$(($owned.Id -join ','))"
        return
      }
      Write-LifecycleLog $Name 'unhealthy_existing_process' "port=$Port owner_pids=$(($owned.Id -join ','))"
      throw "$Name has a checkout-owned listener on port $Port but its HTTP health check failed; no duplicate was started and no process was stopped."
    }
    $table = Get-ProcessTable
    $existing = @(Get-CheckoutServiceProcesses $table $Name | Where-Object { Test-ExactCheckoutServiceProcess $_ $Name })
    if ($existing.Count) {
      $ids = ($existing | ForEach-Object Id | Sort-Object -Unique) -join ','
      Write-LifecycleLog $Name 'startup_in_progress_or_unhealthy' "pids=$ids port=$Port"
      throw "$Name has checkout-owned process PID(s) $ids but no listener; no duplicate was started."
    }
    try {
      Invoke-StartupChild @('-Service',$Name)
      if (Test-LoopbackHttp $HealthUrl 5) { return }
    } catch {
      Write-LifecycleLog $Name 'start_attempt_failed' "attempt=$attempt error_type=$($_.Exception.GetType().Name)"
    }
    if ($attempt -lt $ServiceAttempts) { Start-Sleep -Seconds ([Math]::Min(5 * $attempt,20)) }
  }
  Write-LifecycleLog $Name 'start_failed' "attempts=$ServiceAttempts"
  throw "$Name failed to start and pass its HTTP health check after $ServiceAttempts attempts."
}

function Ensure-ResearchWorker {
  $status = Invoke-ReadinessJson @('--worker','research_worker')
  $table = Get-ProcessTable
  $matches = @(Get-CheckoutServiceProcesses $table 'worker' | Where-Object { Test-ExactCheckoutServiceProcess $_ 'worker' })
  if ($status.value -and $status.value.process_id) {
    $heartbeatProcess = $matches | Where-Object Id -eq ([int]$status.value.process_id) | Select-Object -First 1
    if ($status.value.ready -and $heartbeatProcess) {
      Write-LifecycleLog 'research_worker' 'already_ready' "pid=$($heartbeatProcess.Id) heartbeat_age_seconds=$($status.value.age_seconds)"
      return
    }
  }
  if ($matches.Count) {
    $ids = ($matches | ForEach-Object Id | Sort-Object -Unique) -join ','
    Write-LifecycleLog 'research_worker' 'recovery_refused' "matching_pids=$ids heartbeat_not_fresh=true"
    throw "Research Worker checkout process PID(s) $ids exist without a matching fresh heartbeat; left running to avoid duplicate work."
  }
  for ($attempt=1; $attempt -le $ServiceAttempts; $attempt++) {
    try {
      if ($attempt -gt 1 -and @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'worker').Count) {
        throw 'Research Worker process appeared after an earlier attempt; no duplicate was started.'
      }
      Invoke-StartupChild @('-Service','research_worker')
      $ready = Invoke-ReadinessJson @('--worker','research_worker')
      if ($ready.exit -eq 0 -and $ready.value.ready) { return }
    } catch { Write-LifecycleLog 'research_worker' 'start_attempt_failed' "attempt=$attempt error_type=$($_.Exception.GetType().Name)" }
    if ($attempt -lt $ServiceAttempts) { Start-Sleep -Seconds ([Math]::Min(5 * $attempt,20)) }
  }
  throw "Research Worker failed to start after $ServiceAttempts attempts."
}

function Get-PublicationStartupStatus {
  $python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
  $entry = Join-Path $PSScriptRoot 'publication-worker.py'
  $raw = & $python $entry --status 2>$null
  $exit = $LASTEXITCODE
  $status = $null
  if ($raw) { try { $status = ($raw -join "`n") | ConvertFrom-Json } catch { } }
  return @{ exit=$exit; value=$status }
}

function Ensure-PublicationWorker([string]$Mode = $PublicationMode) {
  $expectedSwitch = switch ($Mode) {
    'scheduled-auto' { '--operations-scheduled-auto' }
    'manual-confirmed' { '--operations-manual-confirmed' }
    'scheduled-auto-manual' { '--operations-scheduled-auto-and-manual' }
    'scheduled-auto-manual-trends' { '--operations-scheduled-auto-and-manual-and-trends' }
    default { '--operations-mock-only' }
  }
  $probe = Get-PublicationStartupStatus
  $status = $probe.value
  if ($probe.exit -eq 0 -and $status -and $status.heartbeat_fresh -and $status.heartbeat.process_id) {
    $table = Get-ProcessTable
    $worker = $table | Where-Object Id -eq ([int]$status.heartbeat.process_id) | Select-Object -First 1
    if ($worker -and (Test-ExactCheckoutServiceProcess $worker 'publication_worker')) {
      if ([string]$worker.CommandLine -match ([regex]::Escape($expectedSwitch) + '(?:\s|$)')) {
        Write-LifecycleLog 'publication_worker' 'already_ready' "pid=$($worker.Id) mode=$Mode"
        return
      }
      Write-LifecycleLog 'publication_worker' 'mode_mismatch' "pid=$($worker.Id) required=$Mode"
      throw "Publication Worker is already running in a different mode. It was left running; review with scripts/status.ps1 before any safe mode transition."
    }
  }
  $found = @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'publication_worker' | Where-Object { Test-ExactCheckoutServiceProcess $_ 'publication_worker' })
  if ($found.Count) {
    $ids = ($found | ForEach-Object Id | Sort-Object -Unique) -join ','
    Write-LifecycleLog 'publication_worker' 'recovery_refused' "matching_pids=$ids heartbeat_verified=false"
    throw "Publication Worker checkout process PID(s) $ids exist without a fresh matching heartbeat; left running."
  }
  for ($attempt=1; $attempt -le $ServiceAttempts; $attempt++) {
    try {
      if ($attempt -gt 1 -and @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'publication_worker').Count) {
        throw 'Publication Worker process appeared after an earlier attempt; no duplicate was started.'
      }
      Invoke-StartupChild @('-Service','publication_worker','-PublicationMode',$Mode)
      return
    } catch { Write-LifecycleLog 'publication_worker' 'start_attempt_failed' "attempt=$attempt error_type=$($_.Exception.GetType().Name)" }
    if ($attempt -lt $ServiceAttempts) { Start-Sleep -Seconds ([Math]::Min(5 * $attempt,20)) }
  }
  throw "Publication Worker failed to start in $Mode mode after $ServiceAttempts attempts."
}

if ($FunctionsOnly) { return }
$startupMutex = New-Object Threading.Mutex($false, (Get-StartupMutexName))
$startupLockHeld = $false
try {
  try { $startupLockHeld = $startupMutex.WaitOne(0) }
  catch [Threading.AbandonedMutexException] { $startupLockHeld = $true }
  if (-not $startupLockHeld) {
    Write-LifecycleLog 'startup' 'already_in_progress' 'another_coordinator_owns_startup_lock=true'
    Write-Output 'Startup already in progress; no duplicate coordinator or services started.'
    return
  }
  if (Test-IntentionalStopForCurrentSession) {
    if (-not $ExplicitUserStart) {
      Write-LifecycleLog 'startup' 'suppressed_after_intentional_stop' 'same_windows_logon_session=true'
      Write-Output 'Startup skipped: all services were intentionally stopped in this Windows logon session. Use the explicit Start shortcut to start them again.'
      return
    }
    Remove-IntentionalStopMarkerForExplicitStart
    Write-LifecycleLog 'startup' 'intentional_stop_cleared' 'explicit_user_start=true'
  }
  $head = Get-CurrentGitCommit
  $validated = Read-ValidatedSource
  $dirty = @(Get-TrackedGitChanges)
  if ($dirty.Count) {
    Write-LifecycleLog 'startup' 'uncommitted_source_changes' "tracked_change_count=$($dirty.Count)"
    throw 'Tracked source changes are not committed; automatic service startup is blocked until verification and explicit service reflection.'
  }
  if (-not $validated -or -not (Test-ValidatedStartupSource ([string]$validated.commit) $head)) {
    $validatedCommit = if ($validated) { [string]$validated.commit } else { 'missing' }
    Write-LifecycleLog 'startup' 'source_not_verified' "head=$head validated_commit=$validatedCommit"
    throw 'Current develop HEAD has not passed scripts/apply-verified-changes.ps1 validation; no service was started.'
  }
  Write-LifecycleLog 'startup' 'begin' 'trigger=windows_user_logon'
  Wait-PostgresReady
  Ensure-HttpService 'api' 8100 'http://127.0.0.1:8100/health'
  Ensure-HttpService 'dashboard' 3100 'http://127.0.0.1:3100/research'
  Ensure-ResearchWorker
  Ensure-PublicationWorker $PublicationMode
  Write-LifecycleLog 'startup' 'complete' 'services=dashboard,api,research_worker,publication_worker'
} catch {
  Write-LifecycleLog 'startup' 'failed' "error_type=$($_.Exception.GetType().Name)"
  throw
} finally {
  if ($startupLockHeld) { $startupMutex.ReleaseMutex() }
  $startupMutex.Dispose()
}

param(
  [ValidateRange(30,900)][int]$DatabaseTimeoutSeconds = 300,
  [ValidateRange(1,10)][int]$ServiceAttempts = 3
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

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
      if (-not $owned.Count) {
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
      & (Join-Path $PSScriptRoot 'start.ps1') -Service $Name
      if ($LASTEXITCODE -eq 0 -and (Test-LoopbackHttp $HealthUrl 5)) { return }
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
      & (Join-Path $PSScriptRoot 'start.ps1') -Service research_worker
      if ($LASTEXITCODE -eq 0) { return }
    } catch { Write-LifecycleLog 'research_worker' 'start_attempt_failed' "attempt=$attempt error_type=$($_.Exception.GetType().Name)" }
    if ($attempt -lt $ServiceAttempts) { Start-Sleep -Seconds ([Math]::Min(5 * $attempt,20)) }
  }
  throw "Research Worker failed to start after $ServiceAttempts attempts."
}

function Ensure-PublicationWorker {
  $python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
  $entry = Join-Path $PSScriptRoot 'publication-worker.py'
  $raw = & $python $entry --status 2>$null
  $exit = $LASTEXITCODE
  $status = $null
  if ($raw) { try { $status = ($raw -join "`n") | ConvertFrom-Json } catch { } }
  if ($exit -eq 0 -and $status -and $status.heartbeat_fresh -and $status.heartbeat.process_id) {
    $table = Get-ProcessTable
    $worker = $table | Where-Object Id -eq ([int]$status.heartbeat.process_id) | Select-Object -First 1
    if ($worker -and (Test-ExactCheckoutServiceProcess $worker 'publication_worker')) {
      if ([string]$worker.CommandLine -match '--operations-scheduled-auto(?:\s|$)') {
        Write-LifecycleLog 'publication_worker' 'already_ready' "pid=$($worker.Id) mode=scheduled-auto"
        return
      }
      Write-LifecycleLog 'publication_worker' 'mode_mismatch' "pid=$($worker.Id) required=scheduled-auto"
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
      & (Join-Path $PSScriptRoot 'start.ps1') -Service publication_worker -PublicationMode scheduled-auto
      if ($LASTEXITCODE -eq 0) { return }
    } catch { Write-LifecycleLog 'publication_worker' 'start_attempt_failed' "attempt=$attempt error_type=$($_.Exception.GetType().Name)" }
    if ($attempt -lt $ServiceAttempts) { Start-Sleep -Seconds ([Math]::Min(5 * $attempt,20)) }
  }
  throw "Publication Worker failed to start in scheduled-auto mode after $ServiceAttempts attempts."
}

try {
  $head = Get-CurrentGitCommit
  $validated = Read-ValidatedSource
  $dirty = @(Get-TrackedGitChanges)
  if ($dirty.Count) {
    Write-LifecycleLog 'startup' 'uncommitted_source_changes' "tracked_change_count=$($dirty.Count)"
    throw 'Tracked source changes are not committed; automatic service startup is blocked until verification and explicit service reflection.'
  }
  if (-not $validated -or [string]$validated.commit -cne $head) {
    $validatedCommit = if ($validated) { [string]$validated.commit } else { 'missing' }
    Write-LifecycleLog 'startup' 'source_not_verified' "head=$head validated_commit=$validatedCommit"
    throw 'Current develop HEAD has not passed scripts/apply-verified-changes.ps1 validation; no service was started.'
  }
  Write-LifecycleLog 'startup' 'begin' 'trigger=windows_user_logon'
  Wait-PostgresReady
  Ensure-HttpService 'api' 8100 'http://127.0.0.1:8100/health'
  Ensure-HttpService 'dashboard' 3100 'http://127.0.0.1:3100/research'
  Ensure-ResearchWorker
  Ensure-PublicationWorker
  Write-LifecycleLog 'startup' 'complete' 'services=dashboard,api,research_worker,publication_worker'
} catch {
  Write-LifecycleLog 'startup' 'failed' "error_type=$($_.Exception.GetType().Name)"
  throw
}

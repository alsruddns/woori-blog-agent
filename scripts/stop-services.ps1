param([ValidateRange(30,600)][int]$TimeoutSeconds = 180)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

$targets = @('publication_worker', 'research_worker', 'dashboard', 'api')
$failures = [System.Collections.Generic.List[string]]::new()

function Assert-HttpGracefulStopReady {
  $table = Get-ProcessTable
  foreach ($name in @('dashboard','api')) {
    foreach ($pidValue in (Get-Listeners ([int]$script:Services[$name].Port))) {
      $process = $table | Where-Object Id -eq ([int]$pidValue) | Select-Object -First 1
      if (-not $process -or -not (Test-ExactCheckoutServiceProcess $process $name)) {
        Write-LifecycleLog $name 'shutdown_preflight_blocked' 'listener_owner_not_verified_for_this_checkout'
        throw "Cannot safely stop all services: $name port owner is not verified as this checkout. No service was stopped."
      }
      $supportsStopFile = if ($name -eq 'api') {
        [string]$process.CommandLine -match '(?i)scripts[\\/]api-service\.py(?:\s|$)'
      } else {
        [string]$process.CommandLine -match '(?i)scripts[\\/]dashboard-service\.js(?:\s|$)'
      }
      if (-not $supportsStopFile) {
        Write-LifecycleLog $name 'shutdown_preflight_blocked' 'legacy_process_has_no_identity_bound_stop_channel'
        throw "Cannot safely stop all services: $name is running without the new cooperative stop channel. No Worker or HTTP service was stopped. Restart this service through the project launcher first."
      }
      $identityPath = Join-Path $script:ProjectRoot ".runtime\service-identity-$name-$([int]$pidValue).json"
      if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf) -or
          ((Get-Item -LiteralPath $identityPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Write-LifecycleLog $name 'shutdown_preflight_blocked' 'cooperative_identity_missing_or_unsafe'
        throw "Cannot safely stop all services: $name stop identity is missing or unsafe. No service was stopped."
      }
      try { $identity = Get-Content -LiteralPath $identityPath -Raw -Encoding utf8 | ConvertFrom-Json }
      catch {
        Write-LifecycleLog $name 'shutdown_preflight_blocked' 'cooperative_identity_unavailable'
        throw "Cannot safely stop all services: $name stop identity is unavailable. No service was stopped."
      }
      if ([int]$identity.pid -ne [int]$pidValue -or [string]$identity.service -cne $name -or
          [string]$identity.checkout_root -ine $script:ProjectRoot -or
          [string]$identity.instance_id -notmatch '^[a-f0-9]{32,64}$') {
        Write-LifecycleLog $name 'shutdown_preflight_blocked' 'cooperative_identity_mismatch'
        throw "Cannot safely stop all services: $name stop identity does not match its listener. No service was stopped."
      }
    }
  }
}

Assert-HttpGracefulStopReady
Write-LifecycleLog 'all_services' 'shutdown_started' "order=$($targets -join ',')"

foreach ($name in $targets) {
  if ($name -in @('publication_worker', 'research_worker')) {
    $kind = if ($name -eq 'publication_worker') { 'publication_worker' } else { 'worker' }
    $processes = @(Get-CheckoutServiceProcesses (Get-ProcessTable) $kind | Where-Object {
      (Test-ExactCheckoutServiceProcess $_ $kind) -and
      ($name -ne 'research_worker' -or [string]$_.CommandLine -notmatch '(?i)(^|\s)--evaluation(?:\s|$)')
    })
    if (-not $processes.Count) {
      Write-LifecycleLog $name 'already_stopped' 'no_verified_checkout_process'
      continue
    }
  } else {
    $port = [int]$script:Services[$name].Port
    $listeners = @(Get-Listeners $port)
    if (-not $listeners.Count) {
      $processes = @(Get-CheckoutServiceProcesses (Get-ProcessTable) $name | Where-Object { Test-ExactCheckoutServiceProcess $_ $name })
      if (-not $processes.Count) {
        Write-LifecycleLog $name 'already_stopped' 'no_listener_or_verified_checkout_process'
        continue
      }
    }
  }

  try {
    Write-LifecycleLog $name 'shutdown_requested' "timeout_seconds=$TimeoutSeconds"
    & (Join-Path $PSScriptRoot 'stop.ps1') -Service $name -TimeoutSeconds $TimeoutSeconds -Confirm:$false
    Write-LifecycleLog $name 'shutdown_command_returned' 'stop_script_completed'
  } catch {
    Write-LifecycleLog $name 'shutdown_failed_safely' "error_type=$($_.Exception.GetType().Name)"
    $failures.Add($name)
    if ($name -in @('publication_worker', 'research_worker')) {
      Write-LifecycleLog 'all_services' 'shutdown_aborted_for_active_worker' "service=$name"
      break
    }
  }
}

Write-Output 'Final service status:'
$status = & (Join-Path $PSScriptRoot 'status.ps1')
$status | Format-List * | Out-String | Write-Output

$stillActive = [System.Collections.Generic.List[string]]::new()
foreach ($name in @('dashboard', 'api')) {
  if (@(Get-Listeners ([int]$script:Services[$name].Port)).Count) { $stillActive.Add($name) }
}
foreach ($name in @('research_worker', 'publication_worker')) {
  $kind = if ($name -eq 'research_worker') { 'worker' } else { 'publication_worker' }
  if (@(Get-CheckoutServiceProcesses (Get-ProcessTable) $kind | Where-Object {
      (Test-ExactCheckoutServiceProcess $_ $kind) -and
      ($name -ne 'research_worker' -or [string]$_.CommandLine -notmatch '(?i)(^|\s)--evaluation(?:\s|$)')
    }).Count) {
    $stillActive.Add($name)
  }
}

if ($stillActive.Count -or $failures.Count) {
  $detail = "active=$($stillActive -join ',') stop_failures=$($failures -join ',')"
  Write-LifecycleLog 'all_services' 'shutdown_incomplete' $detail
  throw "Some Woori services remain active or could not be stopped safely ($detail). See .runtime/logs/service-lifecycle.log. No force termination was attempted."
}
Write-LifecycleLog 'all_services' 'shutdown_complete' 'services=dashboard,api,research_worker,publication_worker'
Write-Output 'All four project services are stopped. The login auto-start task remains registered for the next user logon.'

param([ValidateRange(5,600)][int]$TimeoutSeconds = 25)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')
. (Join-Path $PSScriptRoot 'stop.ps1') -Service api

$targets = @('publication_worker','research_worker','dashboard','api')
$failures = [System.Collections.Generic.List[string]]::new()
$requestId = [guid]::NewGuid().ToString('N')

function Assert-HttpTreeOwned([string]$Name) {
  $port = [int]$script:Services[$Name].Port
  $listeners = @(Get-Listeners $port)
  if ($listeners.Count -gt 1) { throw "$Name has multiple listeners on port $port ($($listeners -join ',')). No service was stopped." }
  if (-not $listeners.Count) { return }
  $table = Get-ProcessTable
  $manifest = Read-ServerManifest
  $listener = $table | Where-Object Id -eq ([int]$listeners[0]) | Select-Object -First 1
  if (-not $listener -or -not (Test-ExactCheckoutServiceProcess $listener $Name)) {
    Write-LifecycleLog $Name 'shutdown_preflight_blocked' 'listener_owner_not_verified_for_this_checkout'
    throw "$Name port $port listener PID $($listeners[0]) does not match the exact checkout executable and command line. No service was stopped."
  }
  $owner = Get-ProcessOwner ([int]$listener.Id)
  if (-not $owner -or $owner -ine "$env:USERDOMAIN\$env:USERNAME") {
    Write-LifecycleLog $Name 'shutdown_preflight_blocked' 'listener_windows_owner_mismatch_or_unavailable'
    throw "$Name listener Windows owner is not verified as the current user. No service was stopped."
  }
  $runner = Get-ManagedRunner $Name $table $manifest
  if (-not $runner) {
    Write-LifecycleLog $Name 'shutdown_preflight_blocked' 'checkout_listener_without_verified_runtime_runner'
    throw "$Name listener has no matching runtime runner record. No service was stopped."
  }
  $tree = Get-ManagedTree $Name $runner $table
  if (-not $tree.safe -or -not @($tree.items | Where-Object Id -eq ([int]$listener.Id)).Count) {
    $why = if ($tree.reason) { [string]$tree.reason } else { 'listener_not_in_runner_tree' }
    Write-LifecycleLog $Name 'shutdown_preflight_blocked' $why
    throw "$Name listener is not in a fully verified runtime process tree ($why). No service was stopped."
  }
  $foreign = @($tree.items | Where-Object { -not $_.Owner -or $_.Owner -ine "$env:USERDOMAIN\$env:USERNAME" })
  if ($foreign.Count) { throw "$Name process tree has unverified owner PID(s): $($foreign.Id -join ','). No service was stopped." }
  $connections = Get-EstablishedConnectionCount @($tree.items.Id)
  if ($connections -gt 0) { throw "$Name has $connections active external connection(s); no service was stopped." }
  $channel = if (($Name -eq 'api' -and $listener.CommandLine -match '(?i)scripts[\\/]api-service\.py(?:\s|$)') -or
      ($Name -eq 'dashboard' -and $listener.CommandLine -match '(?i)scripts[\\/]dashboard-service\.js(?:\s|$)')) { 'identity_bound' } else { 'legacy_verified_tree' }
  if ($channel -eq 'legacy_verified_tree') { Write-LifecycleLog $Name 'legacy_process_verified_for_graceful_then_bounded_stop' "listener_pid=$($listener.Id) tree_pids=$($tree.items.Id -join ',')" }
  Write-LifecycleLog $Name 'shutdown_preflight_verified' "listener_pid=$($listener.Id) runner_pid=$($runner.Id) tree_pids=$($tree.items.Id -join ',') owner=$owner channel=$channel established_external_connections=0"
}

Assert-HttpTreeOwned 'dashboard'
Assert-HttpTreeOwned 'api'
Write-IntentionalStopMarker $requestId
Write-LifecycleLog 'all_services' 'intentional_stop_marker_written' "request_id=$requestId session_id=$(Get-CurrentLogonSessionId)"
Write-LifecycleLog 'all_services' 'shutdown_started' "request_id=$requestId order=$($targets -join ',')"

foreach ($name in $targets) {
  try {
    Write-LifecycleLog $name 'shutdown_requested' "request_id=$requestId timeout_seconds=$TimeoutSeconds"
    $stopArgs = @{ Service=$name; TimeoutSeconds=$TimeoutSeconds; Confirm=$false }
    if ($name -in @('api','dashboard')) { $stopArgs.AllowVerifiedLegacyFallback=$true }
    & (Join-Path $PSScriptRoot 'stop.ps1') @stopArgs
    Write-LifecycleLog $name 'shutdown_command_returned' 'stop_script_completed'
  } catch {
    $detail = ([string]$_.Exception.Message -replace '[\r\n]+',' ') -replace '\s+',' '
    Write-LifecycleLog $name 'shutdown_failed' "request_id=$requestId detail=$($detail.Substring(0,[Math]::Min(240,$detail.Length)))"
    $failures.Add($name)
    if ($name -in @('publication_worker','research_worker')) {
      Write-LifecycleLog 'all_services' 'shutdown_aborted_for_active_worker' "request_id=$requestId service=$name"
      break
    }
  }
}

$stillActive = [System.Collections.Generic.List[string]]::new()
foreach ($name in @('dashboard','api')) {
  $port = [int]$script:Services[$name].Port
  $listeners = @(Get-Listeners $port)
  if ($listeners.Count) {
    $stillActive.Add("$name(pid=$($listeners -join ','),port=$port)")
    Write-LifecycleLog $name 'shutdown_verification_failed' "request_id=$requestId remaining_listener_pids=$($listeners -join ',')"
  }
}
foreach ($name in @('research_worker','publication_worker')) {
  $kind = if ($name -eq 'research_worker') { 'worker' } else { 'publication_worker' }
  $matches = @(Get-CheckoutServiceProcesses (Get-ProcessTable) $kind | Where-Object {
    (Test-ExactCheckoutServiceProcess $_ $kind) -and ($name -ne 'research_worker' -or [string]$_.CommandLine -notmatch '(?i)(^|\s)--evaluation(?:\s|$)')
  })
  if ($matches.Count) {
    $stillActive.Add("$name(pid=$(($matches.Id | Sort-Object -Unique) -join ','))")
    Write-LifecycleLog $name 'shutdown_verification_failed' "request_id=$requestId remaining_pids=$(($matches.Id | Sort-Object -Unique) -join ',')"
  }
}
if ($stillActive.Count -or $failures.Count) {
  $detail = "active=$($stillActive -join ';') stop_failures=$($failures -join ',')"
  Write-LifecycleLog 'all_services' 'shutdown_incomplete' "request_id=$requestId $detail"
  throw "Partial shutdown ($detail). Intentional stop remains recorded to prevent login recovery from restarting services. See .runtime/logs/service-lifecycle.log."
}
foreach ($port in @(3100,8100)) { if (@(Get-Listeners $port).Count) { throw "TCP $port remains in LISTEN state after shutdown." } }
Write-LifecycleLog 'all_services' 'shutdown_complete' "request_id=$requestId services=dashboard,api,research_worker,publication_worker"
Write-Output "All four services stopped; ports 3100 and 8100 are free. Login auto-start remains registered and is suppressed for this logon session. Request: $requestId"

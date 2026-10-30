param([ValidateSet('api','dashboard','worker','research_worker','publication_worker','all')][string]$Service='all',
  [ValidateSet('mock-only','scheduled-auto','manual-confirmed','scheduled-auto-manual')][string]$PublicationMode='mock-only')
. (Join-Path $PSScriptRoot 'server-common.ps1')
if ($Service -eq 'publication_worker') {
  & (Join-Path $PSScriptRoot 'start-publication-worker.ps1') -Mode $PublicationMode
  exit $LASTEXITCODE
}
if ($Service -in @('worker','research_worker')) {
  & (Join-Path $PSScriptRoot 'start-research-worker.ps1')
  exit $LASTEXITCODE
}
$manifest = Read-ServerManifest
$table = Get-ProcessTable
$targets = if ($Service -eq 'all') { @('api','dashboard') } else { @($Service) }
foreach ($name in $targets) {
  $existingProjectProcesses = @(Get-CheckoutServiceProcesses (Get-ProcessTable) $name)
  if ($existingProjectProcesses.Count) {
    $pids = ($existingProjectProcesses | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
    $verified = @(Get-CheckoutServiceProcesses (Get-ProcessTable) $name | Where-Object { Test-ExactCheckoutServiceProcess $_ $name })
    $listeners = @(Get-Listeners ([int]$script:Services[$name].Port))
    $listenerOwnersVerified = $listeners.Count -gt 0 -and @($listeners | Where-Object {
      $listenerPid = [int]$_
      @($verified | Where-Object { [int]$_.Id -eq $listenerPid }).Count -gt 0
    }).Count -eq $listeners.Count
    $healthUrl = if ($name -eq 'api') { 'http://127.0.0.1:8100/health' } else { 'http://127.0.0.1:3100/research' }
    if ($verified.Count -and $listenerOwnersVerified -and (Test-LoopbackHttp $healthUrl 5)) {
      Write-LifecycleLog $name 'already_ready' "pids=$($verified.Id -join ',') port=$($script:Services[$name].Port)"
      Write-Output "$name is already healthy on port $($script:Services[$name].Port); no duplicate was started."
      continue
    }
    throw "$name checkout process(es) already exist (PID $pids) but health/ownership cannot be confirmed. No duplicate was started."
  }
  $port = $script:Services[$name].Port
  $listeners = Get-Listeners $port
  if ($listeners.Count) { throw "Port $port is already occupied. Run scripts/status.ps1 and stop only its verified project-owned process." }
  $runner = (Resolve-Path $script:Services[$name].Script).Path
  $logs = Get-ProjectLogDirectory
  $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + $runner + '"'))
  $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $script:ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "$name.stdout.log") -RedirectStandardError (Join-Path $logs "$name.stderr.log")
  Start-Sleep -Milliseconds 800
  if ($proc.HasExited) { throw "$name startup process exited; inspect its service window and application log." }
  $manifest.services[$name] = @{ pid=$proc.Id; runner=$runner; root=$script:ProjectRoot; started_utc=$proc.StartTime.ToUniversalTime().ToString('o'); applied_commit=(Get-CurrentGitCommit); log_path=(Join-Path $logs "$name.stdout.log") }
  Write-ServerManifest $manifest
  Write-LifecycleLog $name 'starting' "runner_pid=$($proc.Id) port=$port"
  $table = Get-ProcessTable
  if (-not (Test-RecordedRunner ($table | Where-Object Id -eq $proc.Id | Select-Object -First 1) $manifest.services[$name] $name)) { throw "Could not verify $name executable, checkout, and start-time ownership after startup." }
  $deadline = (Get-Date).AddSeconds(30)
  do {
    Start-Sleep -Milliseconds 500
    $listenerReady = (Get-Listeners $port).Count -gt 0
  } while (-not $listenerReady -and (Get-Date) -lt $deadline)
  if (-not $listenerReady) { throw "$name did not bind port $port; process is still tracked and was not force-stopped." }
  $healthUrl = if ($name -eq 'api') { 'http://127.0.0.1:8100/health' } else { 'http://127.0.0.1:3100/research' }
  try { $health = Invoke-WebRequest -Uri $healthUrl -Method Get -TimeoutSec 8 -UseBasicParsing }
  catch { throw "$name is listening but its read-only health route did not respond. Process remains tracked." }
  if ($health.StatusCode -ne 200) { throw "$name health route returned $($health.StatusCode). Process remains tracked." }
  Write-LifecycleLog $name 'ready' "runner_pid=$($proc.Id) port=$port http_status=200"
  Write-Output "$name started; verified HTTP GET $healthUrl returned 200 (runner PID $($proc.Id))."
}

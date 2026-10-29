param([ValidateSet('api','dashboard','publication_worker','all')][string]$Service='all',
  [ValidateSet('mock-only','scheduled-auto')][string]$PublicationMode='mock-only')
. (Join-Path $PSScriptRoot 'server-common.ps1')
if ($Service -eq 'publication_worker') {
  & (Join-Path $PSScriptRoot 'start-publication-worker.ps1') -Mode $PublicationMode
  exit $LASTEXITCODE
}
$manifest = Read-ServerManifest
$table = Get-ProcessTable
$targets = if ($Service -eq 'all') { @('api','dashboard') } else { @($Service) }
foreach ($name in $targets) {
  $existingProjectProcesses = @(Get-CheckoutServiceProcesses (Get-ProcessTable) $name)
  if ($existingProjectProcesses.Count) {
    $pids = ($existingProjectProcesses | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
    throw "$name process(es) from this checkout already exist (PID $pids), possibly on alternate ports. Run scripts/status.ps1 and use the original terminal; no duplicate was started."
  }
  $port = $script:Services[$name].Port
  $listeners = Get-Listeners $port
  if ($listeners.Count) { throw "Port $port is already occupied. Run scripts/status.ps1 and stop only its verified project-owned process." }
  $runner = (Resolve-Path $script:Services[$name].Script).Path
  $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$runner`"") -WorkingDirectory $script:ProjectRoot -PassThru
  Start-Sleep -Milliseconds 800
  if ($proc.HasExited) { throw "$name startup process exited; inspect its service window and application log." }
  $manifest.services[$name] = @{ pid=$proc.Id; runner=$runner; root=$script:ProjectRoot; started_utc=$proc.StartTime.ToUniversalTime().ToString('o') }
  Write-ServerManifest $manifest
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
  Write-Output "$name started; verified HTTP GET $healthUrl returned 200 (runner PID $($proc.Id))."
}

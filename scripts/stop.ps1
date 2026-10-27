param([ValidateSet('api','dashboard','ai','all')][string]$Service='all',[int]$TimeoutSeconds=12)
. (Join-Path $PSScriptRoot 'server-common.ps1')
$manifest = Read-ServerManifest
$targets = if ($Service -eq 'all') { @('dashboard','api','ai') } else { @($Service) }
$table = Get-ProcessTable
$blocked = $false
foreach ($name in $targets) {
  if ($name -eq 'ai') {
    & (Join-Path $script:ProjectRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'stop-local-ai.py')
    if ($LASTEXITCODE -ne 0) { $blocked=$true; Write-Warning 'AI shutdown was not confirmed; runtime record retained.' }
    continue
  }
  $record = $manifest.services[$name]
  if (-not $record) {
    if ((Get-Listeners $script:Services[$name].Port).Count) { $blocked=$true; Write-Warning "$name is unmanaged or its PID record is missing; use Ctrl+C in the verified original project terminal. No process was stopped." }
    continue
  }
  if ([IO.Path]::GetFullPath([string]$record.root) -ne $script:ProjectRoot -or [IO.Path]::GetFullPath([string]$record.runner) -ne [IO.Path]::GetFullPath($script:Services[$name].Script)) {
    throw "$name runtime record does not match this checkout; refusing to stop it."
  }
  $proc = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
  if (-not $proc) {
    if ((Get-Listeners $script:Services[$name].Port).Count) { $blocked=$true; Write-Warning "$name runner ended but its listener remains; refusing PID cleanup because the child may still be active."; continue }
    $manifest.services.Remove($name); Write-Output "$name stale PID cleared after process and listener disappearance."; continue
  }
  $processInfo = $table | Where-Object Id -eq $proc.Id | Select-Object -First 1
  $recordedStart = [DateTimeOffset]::Parse([string]$record.started_utc).UtcDateTime
  $startDelta = [Math]::Abs(($proc.StartTime.ToUniversalTime() - $recordedStart).TotalSeconds)
  if ((-not $processInfo) -or ($processInfo.Path -notmatch '(^|\\)powershell\.exe$') -or ($processInfo.CommandLine.IndexOf([string]$record.runner,[StringComparison]::OrdinalIgnoreCase) -lt 0) -or ($processInfo.CommandLine.IndexOf($script:ProjectRoot,[StringComparison]::OrdinalIgnoreCase) -lt 0) -or ($startDelta -gt 2)) { throw "$name PID executable, checkout path, or start time no longer matches its runtime record; refusing to stop." }
  $servicePort = [int]$script:Services[$name].Port
  $listenerOwners = @(Get-Listeners $servicePort)
  if ($listenerOwners.Count -and @($listenerOwners | Where-Object { -not (Test-DescendantOf $table ([int]$_) $proc.Id) }).Count) {
    throw "$name port $servicePort includes a process outside this managed process tree; refusing to stop."
  }
  try { $activeClients = Get-Connections $servicePort 'Established' }
  catch { $blocked=$true; Write-Warning "$name TCP client state could not be verified; no shutdown was requested."; continue }
  if ($activeClients.Count) { $blocked=$true; Write-Warning "$name has $($activeClients.Count) active TCP client connection(s); no shutdown was requested."; continue }
  if ($proc.MainWindowHandle -eq 0) { $blocked=$true; Write-Warning "$name has no graceful window-control channel. Press Ctrl+C in its original project terminal; it was not terminated."; continue }
  [void]$proc.CloseMainWindow()
  if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) { $blocked=$true; Write-Warning "$name did not exit gracefully. It was left running; no force-stop was attempted."; continue }
  Start-Sleep -Milliseconds 500
  if ((Get-Listeners $script:Services[$name].Port).Count) { $blocked=$true; Write-Warning "$name runner closed but a child still owns its port. PID record retained for manual recovery."; continue }
  $manifest.services.Remove($name)
  Write-Output "$name stopped gracefully."
}
Write-ServerManifest $manifest
if ($blocked) { throw 'One or more services were not stopped. Do not force-kill; follow the original-terminal instruction.' }

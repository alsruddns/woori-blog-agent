param([ValidateSet('mock-only','scheduled-auto','manual-confirmed','scheduled-auto-manual')][string]$Mode='mock-only')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')
$worker = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'scripts\publication-worker.py'))
$python = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'))
$existing = @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'publication_worker')
if ($existing.Count) {
  $pids = ($existing | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
  throw "Publication Worker already exists for this checkout (PID $pids). Use scripts/status.ps1; no duplicate was started."
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $worker -PathType Leaf)) {
  throw 'The project virtual environment or Publication Worker entry point is missing.'
}
$modeArgs = switch ($Mode) {
  'scheduled-auto' { @('--operations-scheduled-auto','--continuous') }
  'manual-confirmed' { @('--operations-manual-confirmed','--continuous') }
  'scheduled-auto-manual' { @('--operations-scheduled-auto-and-manual','--continuous') }
  default { @('--operations-mock-only','--continuous') }
}
if ($Mode -in @('scheduled-auto','scheduled-auto-manual')) {
  $statusOutput = & $python $worker --status 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $statusOutput) {
    throw 'Scheduled Auto Worker status could not be verified; no process was started.'
  }
  try { $status = ($statusOutput -join "`n") | ConvertFrom-Json }
  catch { throw 'Scheduled Auto Worker status was not valid JSON; no process was started.' }
  $policy = $status.scheduled_auto_policy
  if (-not $policy.enabled) {
    throw 'Scheduled Auto is not enabled for any approved blog. No process was started.'
  }
  if ($status.global_mode.emergency_stopped) {
    throw 'The global emergency stop is active; no Scheduled Auto Worker was started.'
  }
}
$runtime = Join-Path $script:ProjectRoot '.runtime'
if (-not (Test-Path -LiteralPath $runtime)) { New-Item -ItemType Directory -Path $runtime | Out-Null }
if ((Get-Item -LiteralPath $runtime -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
  throw '.runtime is a reparse point; refusing to launch the worker.'
}
$logs = Join-Path $runtime 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stdout = Join-Path $logs 'publication-worker.stdout.log'
$stderr = Join-Path $logs 'publication-worker.stderr.log'
$manifest = Read-ServerManifest
$runner = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'start-publication-worker.ps1'))
$proc = Start-Process -FilePath $python `
  -ArgumentList (@("`"$worker`"") + $modeArgs) `
  -WorkingDirectory $script:ProjectRoot -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr
Start-Sleep -Milliseconds 500
if ($proc.HasExited) {
  throw "Publication Worker exited during startup. Inspect $stderr; it was not restarted or force-stopped."
}
$deadline = (Get-Date).AddSeconds(20)
$heartbeatVerified = $false
$actualWorker = $null
do {
  Start-Sleep -Milliseconds 500
  if ($proc.HasExited) { break }
  try {
    $raw = & $python $worker --status 2>$null
    if ($LASTEXITCODE -eq 0 -and $raw) {
      $status = ($raw -join "`n") | ConvertFrom-Json
      $processTable = Get-ProcessTable
      $actualWorker = $processTable | Where-Object Id -eq ([int]$status.heartbeat.process_id) | Select-Object -First 1
      $workerOwned = $actualWorker -and
        (Test-DescendantOf $processTable ([int]$actualWorker.Id) ([int]$proc.Id)) -and
        (Test-ExactCheckoutServiceProcess $actualWorker 'publication_worker')
      $heartbeatVerified = $status.heartbeat -and $status.heartbeat.status -eq 'running' -and
        $status.heartbeat_fresh -and $workerOwned
    }
  } catch { $heartbeatVerified = $false }
} while (-not $heartbeatVerified -and -not $proc.HasExited -and (Get-Date) -lt $deadline)
if (-not $heartbeatVerified) {
  throw "Publication Worker launcher PID $($proc.Id) remains tracked, but its fresh PostgreSQL heartbeat and child identity were not verified. Inspect $stdout and $stderr; it was not force-stopped."
}
$manifest.services['publication_worker'] = @{
  pid=[int]$actualWorker.Id; runner=$runner; root=$script:ProjectRoot; mode=$Mode
  started_utc=(Get-ProcessStarted ([int]$actualWorker.Id))
}
Write-ServerManifest $manifest
$modeLabel = switch ($Mode) {
  'scheduled-auto' { 'scheduled-auto live lane' }
  'manual-confirmed' { 'exactly user-confirmed manual live lane' }
  'scheduled-auto-manual' { 'scheduled-auto plus exactly user-confirmed manual lanes' }
  default { 'mock-only' }
}
Write-Output "Publication Worker started in $modeLabel continuous mode (PID $($actualWorker.Id)); heartbeat verified. Logs: $logs"

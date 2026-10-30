param([ValidateRange(5,300)][int]$ReadyTimeoutSeconds = 45)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

$python = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'))
$statusScript = Join-Path $PSScriptRoot 'service-runtime-status.py'
$logs = Get-ProjectLogDirectory
$stdout = Join-Path $logs 'research-worker.stdout.log'
$stderr = Join-Path $logs 'research-worker.stderr.log'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project virtual environment is missing.' }

$table = Get-ProcessTable
$matches = @(Get-CheckoutServiceProcesses $table 'worker' | Where-Object { Test-ExactCheckoutServiceProcess $_ 'worker' })
$statusRaw = & $python $statusScript --worker research_worker 2>$null
$statusExit = $LASTEXITCODE
$heartbeat = $null
if ($statusRaw) { try { $heartbeat = ($statusRaw -join "`n") | ConvertFrom-Json } catch { } }
if ($heartbeat -and $heartbeat.process_id) {
  $active = $matches | Where-Object Id -eq ([int]$heartbeat.process_id) | Select-Object -First 1
  if ($heartbeat.ready -and $active) {
    Write-LifecycleLog 'research_worker' 'already_running' "pid=$($active.Id) heartbeat_fresh=true"
    Write-Output "Research Worker already running (PID $($active.Id)); no duplicate started."
    exit 0
  }
}
if ($matches.Count) {
  $ids = ($matches | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
  Write-LifecycleLog 'research_worker' 'start_refused' "matching_process_without_fresh_heartbeat pids=$ids status_exit=$statusExit"
  throw "A checkout-owned Research Worker process exists (PID $ids) but its heartbeat cannot be verified. No duplicate was started."
}

$proc = Start-Process -FilePath $python -ArgumentList @('-m','woori.worker') `
  -WorkingDirectory $script:ProjectRoot -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
$verified = $false
$worker = $null
do {
  Start-Sleep -Milliseconds 500
  if ($proc.HasExited) { break }
  $raw = & $python $statusScript --worker research_worker 2>$null
  if ($LASTEXITCODE -eq 0 -and $raw) {
    try { $heartbeat = ($raw -join "`n") | ConvertFrom-Json } catch { $heartbeat = $null }
    if ($heartbeat -and $heartbeat.ready) {
      $table = Get-ProcessTable
      $worker = $table | Where-Object Id -eq ([int]$heartbeat.process_id) | Select-Object -First 1
      $verified = $worker -and (Test-DescendantOf $table ([int]$worker.Id) ([int]$proc.Id)) -and
        (Test-ExactCheckoutServiceProcess $worker 'worker')
    }
  }
} while (-not $verified -and -not $proc.HasExited -and (Get-Date) -lt $deadline)

if (-not $verified) {
  Write-LifecycleLog 'research_worker' 'start_unverified' "launcher_pid=$($proc.Id) process_exit=$($proc.HasExited)"
  throw "Research Worker did not produce a fresh, process-matched heartbeat. No process was terminated. Inspect $stdout and $stderr."
}

$manifest = Read-ServerManifest
$manifest.services['research_worker'] = @{
  pid=[int]$worker.Id; runner=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'start-research-worker.ps1'))
  root=$script:ProjectRoot; started_utc=(Get-ProcessStarted ([int]$worker.Id)); mode='research'
  applied_commit=(Get-CurrentGitCommit); log_path=$stdout
}
Write-ServerManifest $manifest
Write-LifecycleLog 'research_worker' 'started' "pid=$($worker.Id) heartbeat_fresh=true log=$stdout"
Write-Output "Research Worker started (PID $($worker.Id)); heartbeat verified. Logs: $logs"

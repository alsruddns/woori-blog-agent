param([ValidateSet('research','publication-mock')][string]$Service='research')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Service -eq 'publication-mock') {
  $existing = @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'publication_worker')
  if ($existing.Count) {
    $pids = ($existing | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
    throw "Publication Worker already exists for this checkout (PID $pids); no duplicate was started."
  }
  & .venv/Scripts/python.exe .\scripts\publication-worker.py --operations-mock-only --continuous
  exit $LASTEXITCODE
}
$existingWorkers = @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'worker')
if ($existingWorkers.Count) {
  $pids = ($existingWorkers | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
  throw "Research Worker process(es) from this checkout already exist (PID $pids). Use scripts/status.ps1 and the original terminal; no duplicate was started."
}
& .venv/Scripts/python.exe -m woori.worker
exit $LASTEXITCODE

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')
Set-Location (Split-Path $PSScriptRoot -Parent)
$existingWorkers = @(Get-CheckoutServiceProcesses (Get-ProcessTable) 'worker')
if ($existingWorkers.Count) {
  $pids = ($existingWorkers | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', '
  throw "Research Worker process(es) from this checkout already exist (PID $pids). Use scripts/status.ps1 and the original terminal; no duplicate was started."
}
& .venv/Scripts/python.exe -m woori.worker
exit $LASTEXITCODE

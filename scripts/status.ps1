. (Join-Path $PSScriptRoot 'server-common.ps1')
$manifest = Read-ServerManifest
$table = Get-ProcessTable
foreach ($name in @('dashboard', 'api')) {
  $service = $script:Services[$name]
  $listeners = Get-Listeners $service.Port
  if (-not $listeners.Count) { [pscustomobject]@{ Service=$name; Port=$service.Port; State='stopped'; PID=$null; ProjectOwned=$false }; continue }
  foreach ($pidValue in $listeners) {
    $proc = $table | Where-Object Id -eq ([int]$pidValue) | Select-Object -First 1
    $record = $manifest.services[$name]
    $owned = $false
    $runnerInfo = if ($record) { $table | Where-Object Id -eq ([int]$record.pid) | Select-Object -First 1 } else { $null }
    $managedRunner = Test-RecordedRunner $runnerInfo $record $name
    if ($proc -and $record -and $managedRunner -and (Test-DescendantOf $table $proc.Id ([int]$record.pid))) { $owned = $true }
    elseif ($proc -and $proc.CommandLine -and $proc.CommandLine.IndexOf($script:ProjectRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0) { $owned = $true }
    [pscustomobject]@{ Service=$name; Port=$service.Port; State='listening'; PID=[int]$pidValue; Executable=$proc.Path; StartedUtc=(Get-ProcessStarted ([int]$pidValue)); ProjectOwned=$owned }
  }
}

$table = Get-ProcessTable
foreach ($name in @('dashboard','api','worker','publication_worker')) {
  $knownPort = if ($script:Services.ContainsKey($name)) { [int]$script:Services[$name].Port } else { $null }
  $matched = @(Get-CheckoutServiceProcesses $table $name)
  foreach ($proc in $matched) {
    $ports = @()
    try {
      $ports = @(Get-NetTCPConnection -OwningProcess ([int]$proc.Id) -State Listen -ErrorAction Stop |
        Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
    } catch {
      if ($_.FullyQualifiedErrorId -notlike 'CmdletizationQuery_NotFound,*') {
        Write-Warning "Could not inspect listener ports for checkout PID $($proc.Id)."
      }
    }
    $state = if ($null -ne $knownPort -and $ports -contains $knownPort) { 'listening' }
      elseif ($ports.Count) { 'listening-on-alternate-port' }
      else { 'checkout-process-detected' }
    [pscustomobject]@{
      Service=$name; Port=($ports -join ','); State=$state; PID=[int]$proc.Id
      Executable=$proc.Path; StartedUtc=(Get-ProcessStarted ([int]$proc.Id)); ProjectOwned=$true
    }
  }
}

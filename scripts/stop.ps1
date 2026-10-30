[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
  [ValidateSet('api','dashboard','research_worker','worker','evaluation_worker','publication_worker','all')][string]$Service = 'all',
  [ValidateRange(5,3600)][int]$TimeoutSeconds = 60,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
$script:PreviewMode = [bool]$WhatIfPreference
if ($script:PreviewMode) {
  $savedWhatIf = $WhatIfPreference
  $WhatIfPreference = $false
  Import-Module CimCmdlets -ErrorAction Stop
  $WhatIfPreference = $savedWhatIf
}
. (Join-Path $PSScriptRoot 'server-common.ps1')

function Get-ServiceStopKinds([string]$Name) {
  switch ($Name) {
    'api' { return @('api') }
    'dashboard' { return @('dashboard') }
    'research_worker' { return @('worker') }
    'worker' { return @('worker') }
    'evaluation_worker' { return @('evaluation_worker') }
    'publication_worker' { return @('publication_worker') }
    default { throw "Unsupported service: $Name" }
  }
}

function Get-StopCandidates([string]$Name, $ProcessTable) {
  if ($Name -eq 'publication_worker') {
    $matched = @(Get-CheckoutServiceProcesses $ProcessTable 'publication_worker')
    if (-not $matched.Count) { return @() }
    $statusRaw = & (Join-Path $script:ProjectRoot '.venv\Scripts\python.exe') `
      (Join-Path $script:ProjectRoot 'scripts\publication-worker.py') --status
    if ($LASTEXITCODE -ne 0 -or -not $statusRaw) {
      throw 'Could not verify Publication Worker heartbeat identity; no process was stopped.'
    }
    try { $status = ($statusRaw -join "`n") | ConvertFrom-Json }
    catch { throw 'Publication Worker status response was invalid; no process was stopped.' }
    $workerPid = [int]$status.heartbeat.process_id
    $worker = $matched | Where-Object Id -eq $workerPid | Select-Object -First 1
    if (-not $worker -and -not $status.heartbeat_fresh) {
      $venvPython = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'))
      $launcherOnly = $matched | Where-Object {
        [IO.Path]::GetFullPath([string]$_.Path) -ieq $venvPython
      } | Select-Object -First 1
      if ($launcherOnly) {
        return @([pscustomobject]@{
          Id=[int]$launcherOnly.Id; ParentId=[int]$launcherOnly.ParentId; Path=[string]$launcherOnly.Path
          CommandLine=[string]$launcherOnly.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$launcherOnly.Id))
          Kind='publication_worker_stale_launcher'; WorkerService='publication_worker'
          ProcessInfo=$launcherOnly; RelatedLaunchers=@()
        })
      }
    }
    if (-not $worker -or -not (Test-ExactCheckoutServiceProcess $worker 'publication_worker')) {
      throw 'Heartbeat PID does not match an exact Publication Worker process; no process was stopped.'
    }
    $venvPython = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'))
    if ([IO.Path]::GetFullPath([string]$worker.Path) -ieq $venvPython) {
      $launcher = $null
      $related = @()
    } else {
      $launcher = $matched | Where-Object {
        $_.Id -eq [int]$worker.ParentId -and
        [IO.Path]::GetFullPath([string]$_.Path) -ieq $venvPython
      } | Select-Object -First 1
      if (-not $launcher -or -not (Test-DescendantOf $ProcessTable $worker.Id $launcher.Id)) {
        throw 'Publication Worker interpreter parent could not be verified; no process was stopped.'
      }
      $related = @([pscustomobject]@{
        Id=[int]$launcher.Id; ParentId=[int]$launcher.ParentId; Path=[string]$launcher.Path
        CommandLine=[string]$launcher.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$launcher.Id))
        Kind='publication_worker_launcher'; ProcessInfo=$launcher
      })
    }
    return @([pscustomobject]@{
      Id=[int]$worker.Id; ParentId=[int]$worker.ParentId; Path=[string]$worker.Path
      CommandLine=[string]$worker.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$worker.Id))
      Kind='publication_worker'; WorkerService='publication_worker'; ProcessInfo=$worker
      RelatedLaunchers=$related
    })
  }
  if ($Name -in @('worker','research_worker')) {
    $venvPython = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'))
    $matched = @(
      Get-CheckoutServiceProcesses $ProcessTable 'worker' |
        Where-Object {
          (Test-ExactCheckoutServiceProcess $_ 'worker') -and
          ($Name -ne 'research_worker' -or [string]$_.CommandLine -notmatch '(?i)(^|\s)--evaluation(?:\s|$)')
        }
    )
    $candidates = @()
    foreach ($process in $matched | Where-Object { [IO.Path]::GetFullPath([string]$_.Path) -ine $venvPython }) {
      $launcher = $matched | Where-Object {
        $_.Id -eq [int]$process.ParentId -and
          [IO.Path]::GetFullPath([string]$_.Path) -ieq $venvPython
      } | Select-Object -First 1
      if (-not $launcher -or -not (Test-DescendantOf $ProcessTable $process.Id $launcher.Id)) {
        throw 'Research Worker interpreter parent could not be verified; no process was stopped.'
      }
      $service = if ([string]$process.CommandLine -match '(?i)(^|\s)--evaluation(?:\s|$)') {
        'evaluation_worker'
      } else { 'research_worker' }
      $candidates += [pscustomobject]@{
        Id=[int]$process.Id; ParentId=[int]$process.ParentId; Path=[string]$process.Path
        CommandLine=[string]$process.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$process.Id))
        Kind=if ($service -eq 'evaluation_worker') { 'evaluation_worker' } else { 'worker' }
        WorkerService=$service; ProcessInfo=$process
        RelatedLaunchers=@([pscustomobject]@{
          Id=[int]$launcher.Id; ParentId=[int]$launcher.ParentId; Path=[string]$launcher.Path
          CommandLine=[string]$launcher.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$launcher.Id))
          Kind='worker_launcher'; ProcessInfo=$launcher
        })
      }
    }
    if ($matched.Count -and -not $candidates.Count) {
      throw 'Research Worker heartbeat process could not be distinguished from its launcher; no process was stopped.'
    }
    return @($candidates | Sort-Object Id,Kind -Unique)
  }
  $items = @()
  foreach ($kind in (Get-ServiceStopKinds $Name)) {
    foreach ($candidate in (Get-CheckoutServiceProcesses $ProcessTable $kind)) {
      if (Test-ExactCheckoutServiceProcess $candidate $kind) {
        $items += [pscustomobject]@{
          Id=[int]$candidate.Id; ParentId=[int]$candidate.ParentId; Path=[string]$candidate.Path
          CommandLine=[string]$candidate.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$candidate.Id))
          Kind=$kind; WorkerService=if ($kind -eq 'evaluation_worker') { 'evaluation_worker' } elseif ($kind -eq 'worker' -and [string]$candidate.CommandLine -match '(?i)--evaluation') { 'evaluation_worker' } else { 'research_worker' }; ProcessInfo=$candidate
        }
      }
    }
  }
  return @($items | Sort-Object Id,Kind -Unique)
}

function Get-ManagedRunner([string]$Name, $ProcessTable, $Manifest) {
  if ($Name -notin @('api','dashboard')) { return $null }
  $record = $Manifest.services[$Name]
  if (-not $record) { return $null }
  $runner = $ProcessTable | Where-Object Id -eq ([int]$record.pid) | Select-Object -First 1
  if (-not (Test-RecordedRunner $runner $record $Name)) { return $null }
  $started = Get-ProcessStarted ([int]$runner.Id)
  if (-not $started) { return $null }
  return [pscustomobject]@{
    Id=[int]$runner.Id; ParentId=[int]$runner.ParentId; Path=[string]$runner.Path
    CommandLine=[string]$runner.CommandLine; StartedUtc=$started; Kind='runner'; ProcessInfo=$runner
  }
}

function Test-ManifestRecordMatchesRunner($Record, $RunnerSnapshot, [string]$Name) {
  if (-not $Record -or -not $RunnerSnapshot -or [int]$Record.pid -ne [int]$RunnerSnapshot.Id) { return $false }
  try {
    if ([IO.Path]::GetFullPath([string]$Record.root) -ine $script:ProjectRoot) { return $false }
    if ([IO.Path]::GetFullPath([string]$Record.runner) -ine [IO.Path]::GetFullPath($script:Services[$Name].Script)) { return $false }
    $a = [DateTimeOffset]::Parse([string]$Record.started_utc).UtcDateTime
    $b = [DateTimeOffset]::Parse([string]$RunnerSnapshot.StartedUtc).UtcDateTime
    return [Math]::Abs(($a - $b).TotalSeconds) -le 2
  } catch { return $false }
}

function Get-ManagedTree([string]$Name, $Runner, $ProcessTable) {
  if (-not $Runner) { return @{ items=@(); safe=$false; reason='no_verified_managed_runner' } }
  $tree = @(Get-ProcessDescendants $ProcessTable $Runner.Id -IncludeAncestor)
  $allowed = @([pscustomobject]@{ ProcessInfo=$Runner.ProcessInfo; Kind='runner' })
  $serviceKind = if ($Name -eq 'api') { 'api' } else { 'dashboard' }
  foreach ($item in $tree | Where-Object { [int]$_.Id -ne $Runner.Id }) {
    if ([IO.Path]::GetFileName([string]$item.Path) -ieq 'conhost.exe') { continue }
    if (Test-ExactCheckoutServiceProcess $item $serviceKind) {
      $allowed += [pscustomobject]@{ ProcessInfo=$item; Kind=$serviceKind }; continue
    }
    if ($Name -eq 'api' -and [IO.Path]::GetFileName([string]$item.Path) -ieq 'python.exe' -and
        [string]$item.CommandLine -and
        $item.CommandLine.IndexOf([IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe')),[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $item.CommandLine -match '(?i)-m\s+uvicorn\s+woori\.main:app(?:\s|$)') {
      $allowed += [pscustomobject]@{ ProcessInfo=$item; Kind='api' }; continue
    }
    if ($Name -eq 'dashboard' -and [IO.Path]::GetFileName([string]$item.Path) -ieq 'cmd.exe') {
      $nextPaths = @(
        [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'apps\dashboard\node_modules\next\dist\bin\next')),
        [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'apps\dashboard\node_modules\next\dist\server\lib\start-server.js'))
      )
      $matchedNext = @($nextPaths | Where-Object { [string]$item.CommandLine -and $item.CommandLine.IndexOf($_,[StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
      $matchedNext = $matchedNext -or ([string]$item.CommandLine -match '(?i)apps[\\/]dashboard[\\/]node_modules[\\/]\.bin.*next[\\/]dist[\\/]bin[\\/]next')
      $matchedNpm = [string]$item.CommandLine -match '(?i)npm\.cmd.*--prefix\s+apps[\\/]dashboard\s+run\s+start|--prefix\s+apps[\\/]dashboard\s+run\s+start'
      $matchedNextWrapper = [string]$item.CommandLine -match '(?i)cmd.*\/c\s+next\s+start\s+--hostname\s+\S+\s+--port\s+\d+'
      if ($matchedNext -or $matchedNpm -or $matchedNextWrapper) {
        $allowed += [pscustomobject]@{ ProcessInfo=$item; Kind='dashboard_wrapper' }; continue
      }
    }
    if ($Name -eq 'dashboard' -and [IO.Path]::GetFileName([string]$item.Path) -ieq 'node.exe' -and
        [string]$item.CommandLine -match '(?i)npm-cli\.js.*--prefix\s+apps[\\/]dashboard\s+run\s+start') {
      $allowed += [pscustomobject]@{ ProcessInfo=$item; Kind='dashboard_npm' }; continue
    }
    return @{ items=@(); safe=$false; reason="unrecognized_descendant_pid_$($item.Id)" }
  }
  $snapshots = foreach ($entry in $allowed) {
    $item = $entry.ProcessInfo
    [pscustomobject]@{
      Id=[int]$item.Id; ParentId=[int]$item.ParentId; Path=[string]$item.Path
      CommandLine=[string]$item.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$item.Id))
      Kind=[string]$entry.Kind
      ProcessInfo=$item
    }
  }
  if (-not @($snapshots | Where-Object { -not $_.StartedUtc }).Count) {
    return @{ items=@($snapshots); safe=$true; reason=$null }
  }
  return @{ items=@(); safe=$false; reason='process_start_time_unavailable' }
}

function Test-SnapshotStillSame($Snapshot) {
  $current = Get-ProcessTable | Where-Object Id -eq ([int]$Snapshot.Id) | Select-Object -First 1
  if (-not $current) { return $false }
  $currentSnapshot = [pscustomobject]@{
    Id=[int]$current.Id; ParentId=[int]$current.ParentId; Path=[string]$current.Path
    CommandLine=[string]$current.CommandLine; StartedUtc=(Get-ProcessStarted ([int]$current.Id))
  }
  return Test-SameProcessSnapshot $Snapshot $currentSnapshot
}

function Get-EstablishedConnectionCount($ProcessIds) {
  $ids = @($ProcessIds | ForEach-Object { [int]$_ })
  try { $all = @(Get-NetTCPConnection -State Established -ErrorAction Stop) }
  catch {
    if ($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound,*') { return 0 }
    throw 'Could not verify established connections; refusing shutdown.'
  }
  $managed = @($all | Where-Object { $ids -contains [int]$_.OwningProcess })
  $managedLocalEndpoints = @{}
  foreach ($connection in $managed) {
    $key = "{0}|{1}" -f ([string]$connection.LocalAddress).ToLowerInvariant(),[int]$connection.LocalPort
    $managedLocalEndpoints[$key] = [int]$connection.OwningProcess
  }
  $externalCount = 0
  foreach ($connection in $managed) {
    $remoteKey = "{0}|{1}" -f ([string]$connection.RemoteAddress).ToLowerInvariant(),[int]$connection.RemotePort
    if ($managedLocalEndpoints.ContainsKey($remoteKey)) { continue }
    $externalCount++
  }
  return $externalCount
}

function Wait-ForSnapshotsExit($Snapshots, [int]$Seconds) {
  $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
  do {
    $remaining = @($Snapshots | Where-Object { Test-SnapshotStillSame $_ })
    if (-not $remaining.Count) { return @() }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)
  return @($Snapshots | Where-Object { Test-SnapshotStillSame $_ })
}

function Request-GracefulClose($RunnerSnapshot) {
  if (-not (Test-SnapshotStillSame $RunnerSnapshot)) { return $false }
  $process = Get-Process -Id ([int]$RunnerSnapshot.Id) -ErrorAction SilentlyContinue
  if (-not $process -or $process.MainWindowHandle -eq 0) { return $false }
  try { return [bool]$process.CloseMainWindow() }
  catch { return $false }
}

function Write-WorkerStopRequest($Target) {
  $runtimeDir = Join-Path $script:ProjectRoot '.runtime'
  if (-not (Test-Path -LiteralPath $runtimeDir)) { New-Item -ItemType Directory -Path $runtimeDir | Out-Null }
  $runtimeItem = Get-Item -LiteralPath $runtimeDir -Force
  if (($runtimeItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw '.runtime is a reparse point; refusing to write a worker stop request.'
  }
  $path = Join-Path $runtimeDir "worker-stop-$($Target.Id).json"
  $workerServiceName = [string]$Target.WorkerService
  $payload = @{
    pid=[int]$Target.Id; service=$workerServiceName; checkout_root=$script:ProjectRoot
    process_started_at=[DateTimeOffset]::Parse([string]$Target.StartedUtc).ToUniversalTime().ToString('o')
    requested_at=[DateTimeOffset]::UtcNow.ToString('o')
  }
  if (Test-Path -LiteralPath $path) {
    try { $existing = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw "Existing worker request marker is invalid; inspect $path. No overwrite performed." }
    if ([int]$existing.pid -ne [int]$Target.Id -or
        [string]$existing.service -ne $workerServiceName -or
        [string]$existing.checkout_root -ine $script:ProjectRoot -or
        [string]$existing.process_started_at -cne [string]$payload.process_started_at) {
      throw "Existing worker request belongs to another process identity; inspect $path. No overwrite performed."
    }
    return $path
  }
  $temp = "$path.$([guid]::NewGuid().ToString('N')).tmp"
  $json = $payload | ConvertTo-Json -Depth 3 -Compress
  [IO.File]::WriteAllText($temp,$json,(New-Object System.Text.UTF8Encoding($false)))
  try { [IO.File]::Move($temp,$path) }
  catch { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue; throw }
  return $path
}

function Remove-WorkerStopRequestIfOwned($Target) {
  $path = Join-Path (Join-Path $script:ProjectRoot '.runtime') "worker-stop-$($Target.Id).json"
  if (-not (Test-Path -LiteralPath $path)) { return }
  try { $payload = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json }
  catch { return }
  $workerServiceName = [string]$Target.WorkerService
  if ([int]$payload.pid -eq [int]$Target.Id -and
      [string]$payload.service -eq $workerServiceName -and
      [string]$payload.checkout_root -ieq $script:ProjectRoot -and
      [string]$payload.process_started_at -ceq [string]([DateTimeOffset]::Parse([string]$Target.StartedUtc).ToUniversalTime().ToString('o'))) {
    Remove-Item -LiteralPath $path -Force
  }
}

function Confirm-ForceAction([string]$Name, $Snapshots) {
  $pids = (@($Snapshots | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ',')
  Write-Warning "FORCE STOP IMPACT: $Name will terminate only these verified project process PID(s): $pids. In-flight requests may be interrupted; user terminals, PostgreSQL, and other projects are excluded."
  if (-not $Force) { return $false }
  try { $answer = Read-Host "Type FORCE $Name $pids to continue" }
  catch { return $false }
  return $answer -ceq "FORCE $Name $pids"
}

function Invoke-ForceManagedStop([string]$Name, $Snapshots) {
  # The only PowerShell process allowed here is the separately launched runner
  # whose manifest, runner script, checkout and start time were verified.
  $ordered = @($Snapshots | Sort-Object @{Expression={
    $depth=0; $cursor=$_.ProcessInfo; $seen=@{};
    while ($cursor -and $depth -lt 32 -and -not $seen.ContainsKey([int]$cursor.Id)) {
      $seen[[int]$cursor.Id]=$true; $depth++
      $cursor=$script:StopProcessTable | Where-Object Id -eq ([int]$cursor.ParentId) | Select-Object -First 1
    }
    $depth
  }} -Descending)
  foreach ($snapshot in $ordered) {
    if (-not (Test-SnapshotStillSame $snapshot)) { continue }
    $allowed = if ($snapshot.Kind -eq 'runner') {
      [IO.Path]::GetFileName([string]$snapshot.Path) -match '^(powershell|pwsh)\.exe$' -and
        ([string]$snapshot.CommandLine).IndexOf([string]$script:Services[$Name].Script,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        ([string]$snapshot.CommandLine).IndexOf($script:ProjectRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0
    } elseif ($snapshot.Kind -eq 'dashboard_wrapper') {
      [IO.Path]::GetFileName([string]$snapshot.Path) -ieq 'cmd.exe' -and
        ([string]$snapshot.CommandLine -match '(?i)npm\.cmd.*--prefix\s+apps[\\/]dashboard\s+run\s+start|--prefix\s+apps[\\/]dashboard\s+run\s+start|apps[\\/]dashboard[\\/]node_modules[\\/]\.bin.*next[\\/]dist[\\/]bin[\\/]next|cmd.*\/c\s+next\s+start\s+--hostname\s+\S+\s+--port\s+\d+')
    } elseif ($snapshot.Kind -eq 'dashboard_npm') {
      [IO.Path]::GetFileName([string]$snapshot.Path) -ieq 'node.exe' -and
        [string]$snapshot.CommandLine -match '(?i)npm-cli\.js.*--prefix\s+apps[\\/]dashboard\s+run\s+start'
    } elseif ($Name -eq 'api' -and [IO.Path]::GetFileName([string]$snapshot.Path) -ieq 'python.exe') {
      [string]$snapshot.CommandLine -and
        ([string]$snapshot.CommandLine).IndexOf([IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe')),[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        [string]$snapshot.CommandLine -match '(?i)-m\s+uvicorn\s+woori\.main:app(?:\s|$)'
    } else { Test-ExactCheckoutServiceProcess $snapshot.ProcessInfo $Name }
    if (-not $allowed) { throw "PID $($snapshot.Id) no longer matches the verified $Name process identity; refusing force stop." }
    Stop-Process -Id ([int]$snapshot.Id) -ErrorAction Stop
  }
}

function Invoke-ProjectStop {
  [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
  param([string]$Name, [int]$TimeoutSeconds, [bool]$AllowForce)
  $table = Get-ProcessTable
  $script:StopProcessTable = $table
  $manifest = Read-ServerManifest
  $candidates = @(Get-StopCandidates $Name $table)
  $runner = Get-ManagedRunner $Name $table $manifest
  $managed = if ($runner) { Get-ManagedTree $Name $runner $table } else { @{items=@();safe=$false;reason='no_verified_managed_runner'} }

  if ($Name -in @('api','dashboard')) {
    if ($candidates.Count -and -not $runner) {
      foreach ($candidate in $candidates) {
        Write-Warning "$Name PID $($candidate.Id) is a verified checkout service process but not a manifest-owned runner. Parent PID $($candidate.ParentId), executable '$($candidate.Path)'. Use Ctrl+C in its original verified terminal; this script will not terminate it."
      }
      return $false
    }
    if (-not $runner) {
      if ($manifest.services.ContainsKey($Name)) {
        Write-Warning "$Name has a stale or reused manifest PID. No PID was stopped and the record was retained."
        return $false
      }
      Write-Host "${Name}: no verified managed process found."
      return $true
    }
    if (-not $managed.safe) {
      Write-Warning "$Name managed tree is not fully verified ($($managed.reason)); no process was stopped."
      return $false
    }
    $snapshots = @($managed.items)
    $pids = @($snapshots | ForEach-Object { $_.Id })
    $active = Get-EstablishedConnectionCount $pids
    if ($active -gt 0) {
      Write-Warning "$Name has $active established connection(s) on verified process PID(s) $($pids -join ','). Close clients and retry; no shutdown was requested."
      return $false
    }
    $targetText = ($snapshots | ForEach-Object { "PID $($_.Id) [$($_.Kind)] $($_.Path) :: $($_.CommandLine)" }) -join [Environment]::NewLine
    if (-not $PSCmdlet.ShouldProcess($targetText,"Request graceful shutdown of $Name")) { return $false }
    [void](Request-GracefulClose $runner)
    $remaining = @(Wait-ForSnapshotsExit $snapshots $TimeoutSeconds)
    if (-not $remaining.Count) {
      $freshManifest = Read-ServerManifest
      $currentRecord = $freshManifest.services[$Name]
      if (Test-ManifestRecordMatchesRunner $currentRecord $runner $Name) {
        $freshManifest.services.Remove($Name)
        Write-ServerManifest $freshManifest
      }
      Write-Host "$Name stopped gracefully; verified service process tree exited."
      return $true
    }
    Write-Warning "$Name did not stop gracefully within $TimeoutSeconds seconds. Remaining verified PID(s): $($remaining.Id -join ', ')."
    if (-not $AllowForce -or -not (Confirm-ForceAction $Name $remaining)) {
      Write-Warning "$Name was left running. Re-run with -Force and confirm the exact PID phrase, or use its dedicated service terminal."
      return $false
    }
    Invoke-ForceManagedStop $Name $remaining
    $afterForce = @(Wait-ForSnapshotsExit $remaining 10)
    if ($afterForce.Count) {
      Write-Warning "$Name still has process PID(s) $($afterForce.Id -join ','); no further action was attempted."
      return $false
    }
    $freshManifest = Read-ServerManifest
    if (Test-ManifestRecordMatchesRunner $freshManifest.services[$Name] $runner $Name) {
      $freshManifest.services.Remove($Name); Write-ServerManifest $freshManifest
    }
    Write-Warning "$Name stopped after explicit force confirmation."
    return $true
  }

  $complete = $true
  foreach ($candidate in $candidates) {
    $targetText = "PID $($candidate.Id) [$($candidate.Kind)] parent PID $($candidate.ParentId) executable '$($candidate.Path)' command '$($candidate.CommandLine)'"
    if (-not $PSCmdlet.ShouldProcess($targetText,"Request safe stop of $($candidate.Kind)")) { $complete=$false; continue }
    if ($candidate.Kind -in @('worker','evaluation_worker','publication_worker')) {
      $requestPath = Write-WorkerStopRequest $candidate
      Write-Host "Graceful stop requested for Worker PID $($candidate.Id); it will finish its current synchronous work cycle first. Request: $requestPath"
      $remaining = @(Wait-ForSnapshotsExit @($candidate) $TimeoutSeconds)
      if ($remaining.Count) {
        Write-Warning "Worker PID $($candidate.Id) is still active. The stop request remains pending; no force termination is supported. It may be processing a task."
        $complete=$false
      } else {
        Remove-WorkerStopRequestIfOwned $candidate
        $related = @($candidate.RelatedLaunchers | Where-Object { $_ })
        $relatedRemaining = if ($related.Count) { @(Wait-ForSnapshotsExit $related 5) } else { @() }
        if ($relatedRemaining.Count) {
          Write-Warning "Publication Worker process PID $($candidate.Id) stopped, but its verified Python launcher PID(s) $($relatedRemaining.Id -join ', ') remain. They were left untouched."
          $complete=$false
        } else {
          Write-Host "Worker PID $($candidate.Id) exited after its current work cycle."
        }
      }
    } else {
      # The publication worker is a single-run external-effect dispatcher. It
      # has no cooperative cancellation channel; wait for its job to finish.
      $remaining = @(Wait-ForSnapshotsExit @($candidate) $TimeoutSeconds)
      if ($remaining.Count) {
        Write-Warning "Publication Worker PID $($candidate.Id) is still running, possibly inside a Blogger request. It was not interrupted."
        $complete=$false
      } else {
        Write-Host "Publication Worker PID $($candidate.Id) completed and exited."
      }
    }
  }
  if (-not $candidates.Count) { Write-Host 'worker: no verified project worker process found.' }
  return $complete
}

function Invoke-StopCommand([string]$SelectedService, [int]$Timeout, [bool]$AllowForce) {
  $preview = [bool]$WhatIfPreference
  $targets = if ($SelectedService -eq 'all') { @('dashboard','api','research_worker','publication_worker') } else { @($SelectedService) }
  $result = $true
  foreach ($name in $targets) {
    try { if (-not (Invoke-ProjectStop $name $Timeout $AllowForce)) { $result=$false } }
    catch { Write-Warning "$name stop failed safely: $($_.Exception.Message)"; $result=$false }
  }
  Write-Output 'Post-stop status verification:'
  & (Join-Path $PSScriptRoot 'status.ps1')
  foreach ($name in $targets) {
    $table = Get-ProcessTable
    $remaining = @(Get-StopCandidates $name $table)
    if ($remaining.Count) {
      Write-Warning "Verification: $name still has matching process PID(s) $($remaining.Id -join ', ')."
      $result=$false
    } else {
      Write-Output "Verification: no matching $name service process remains."
    }
  }
  if (-not $result -and -not $preview) { throw 'One or more services remain active or could not be verified as stopped.' }
}

if ($MyInvocation.InvocationName -ne '.') {
  Invoke-StopCommand $Service $TimeoutSeconds ([bool]$Force)
}

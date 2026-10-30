$ErrorActionPreference = 'Stop'
$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:RuntimeDir = Join-Path $script:ProjectRoot '.runtime'
$script:ManifestPath = Join-Path $script:RuntimeDir 'servers.json'
$script:ValidatedSourcePath = Join-Path $script:RuntimeDir 'validated-source.json'
$script:IntentionalStopPath = Join-Path $script:RuntimeDir 'intentional-stop.json'
$script:Services = @{
  api = @{ Port = 8100; Script = (Join-Path $PSScriptRoot 'run-api.ps1') }
  dashboard = @{ Port = 3100; Script = (Join-Path $PSScriptRoot 'run-dashboard.ps1') }
}

function Read-ServerManifest {
  if (-not (Test-Path -LiteralPath $script:ManifestPath)) { return @{ services = @{} } }
  try {
    $parsed = Get-Content -LiteralPath $script:ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    $services = @{}
    if ($parsed.services) {
      foreach ($property in $parsed.services.PSObject.Properties) {
        $services[$property.Name] = @{
          pid = [int]$property.Value.pid; runner = [string]$property.Value.runner
          root = [string]$property.Value.root; started_utc = [string]$property.Value.started_utc
          mode = [string]$property.Value.mode
          applied_commit = [string]$property.Value.applied_commit
          log_path = [string]$property.Value.log_path
        }
      }
    }
    return @{ services = $services }
  }
  catch { throw 'Runtime manifest is invalid. Inspect .runtime/servers.json before managing servers.' }
}

function Write-ServerManifest($Manifest) {
  New-Item -ItemType Directory -Path $script:RuntimeDir -Force | Out-Null
  $temp = "$($script:ManifestPath).tmp"
  $Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temp -Encoding utf8
  Move-Item -LiteralPath $temp -Destination $script:ManifestPath -Force
}

function Get-CurrentGitCommit {
  try {
    $output = & git -C $script:ProjectRoot rev-parse HEAD 2>$null
    $gitExit = $LASTEXITCODE
    $commit = ([string]$output).Trim()
    if ($gitExit -eq 0 -and $commit -match '^[0-9a-f]{40}$') { return $commit }
  } catch { }
  return 'unknown'
}

function Get-TrackedGitChanges {
  try { return @(& git -C $script:ProjectRoot status --porcelain --untracked-files=no) }
  catch { throw 'Could not verify the tracked Git worktree state.' }
}

function Read-ValidatedSource {
  if (-not (Test-Path -LiteralPath $script:ValidatedSourcePath -PathType Leaf)) { return $null }
  try { return (Get-Content -LiteralPath $script:ValidatedSourcePath -Raw -Encoding utf8 | ConvertFrom-Json) }
  catch { throw 'Validated source marker is invalid; inspect .runtime/validated-source.json.' }
}

function Write-ValidatedSource([string]$Commit, [string[]]$Services, [string]$DashboardBuildDir = '') {
  [void](Get-ProjectLogDirectory)
  $payload = [ordered]@{ commit=$Commit; validated_at_utc=[DateTimeOffset]::UtcNow.ToString('o'); services=@($Services | Sort-Object -Unique); dashboard_build_dir=$DashboardBuildDir }
  $temp = "$($script:ValidatedSourcePath).$([guid]::NewGuid().ToString('N')).tmp"
  [IO.File]::WriteAllText($temp,($payload | ConvertTo-Json -Depth 3),(New-Object System.Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temp -Destination $script:ValidatedSourcePath -Force
}

function Write-LifecycleLog([string]$ServiceName, [string]$Event, [string]$Detail = '') {
  $logs = Get-ProjectLogDirectory
  $log = Join-Path $logs 'service-lifecycle.log'
  if ((Test-Path -LiteralPath $log -PathType Leaf) -and (Get-Item -LiteralPath $log).Length -gt 2MB) {
    Move-Item -LiteralPath $log -Destination (Join-Path $logs 'service-lifecycle.previous.log') -Force
  }
  $record = [ordered]@{
    at_utc = [DateTimeOffset]::UtcNow.ToString('o'); service = $ServiceName
    event = $Event; detail = $Detail; git_commit = (Get-CurrentGitCommit)
  } | ConvertTo-Json -Compress
  [IO.File]::AppendAllText($log, $record + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-CurrentLogonSessionId {
  try { return [int](Get-Process -Id $PID -ErrorAction Stop).SessionId }
  catch { throw 'Could not identify the current Windows logon session.' }
}

function Test-IntentionalStopForCurrentSession {
  if (-not (Test-Path -LiteralPath $script:IntentionalStopPath -PathType Leaf)) { return $false }
  $item = Get-Item -LiteralPath $script:IntentionalStopPath -Force
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Intentional-stop marker is a reparse point; inspect it before starting services.' }
  try { $marker = Get-Content -LiteralPath $script:IntentionalStopPath -Raw -Encoding utf8 | ConvertFrom-Json }
  catch { throw 'Intentional-stop marker is unreadable; inspect it before starting services.' }
  if ([string]$marker.checkout_root -ine $script:ProjectRoot -or [string]$marker.owner -ine "$env:USERDOMAIN\$env:USERNAME" -or
      [int]$marker.session_id -le 0 -or -not [string]$marker.request_id) {
    throw 'Intentional-stop marker identity is invalid; refusing automatic service startup.'
  }
  return [int]$marker.session_id -eq (Get-CurrentLogonSessionId)
}

function Write-IntentionalStopMarker([string]$RequestId) {
  $runtime = Get-Item -LiteralPath $script:RuntimeDir -Force
  if (($runtime.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw '.runtime is a reparse point.' }
  $payload = [ordered]@{ checkout_root=$script:ProjectRoot; owner="$env:USERDOMAIN\$env:USERNAME"; session_id=(Get-CurrentLogonSessionId); request_id=$RequestId; requested_at_utc=[DateTimeOffset]::UtcNow.ToString('o') }
  $temp = "$($script:IntentionalStopPath).$([guid]::NewGuid().ToString('N')).tmp"
  [IO.File]::WriteAllText($temp,($payload | ConvertTo-Json -Compress),(New-Object System.Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temp -Destination $script:IntentionalStopPath -Force
}

function Remove-IntentionalStopMarkerForExplicitStart {
  if (-not (Test-Path -LiteralPath $script:IntentionalStopPath -PathType Leaf)) { return }
  $item = Get-Item -LiteralPath $script:IntentionalStopPath -Force
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Intentional-stop marker is a reparse point.' }
  $marker = Get-Content -LiteralPath $script:IntentionalStopPath -Raw -Encoding utf8 | ConvertFrom-Json
  if ([string]$marker.checkout_root -ine $script:ProjectRoot -or [string]$marker.owner -ine "$env:USERDOMAIN\$env:USERNAME") { throw 'Intentional-stop marker belongs to another checkout or user.' }
  Remove-Item -LiteralPath $script:IntentionalStopPath -Force
}

function Get-ProjectLogDirectory {
  if (-not (Test-Path -LiteralPath $script:RuntimeDir)) { New-Item -ItemType Directory -Path $script:RuntimeDir -Force | Out-Null }
  $runtimeItem = Get-Item -LiteralPath $script:RuntimeDir -Force
  if (($runtimeItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
      [IO.Path]::GetFullPath($runtimeItem.FullName).TrimEnd('\') -ine [IO.Path]::GetFullPath($script:RuntimeDir).TrimEnd('\')) {
    throw '.runtime is not a project-owned directory; refusing service lifecycle writes.'
  }
  $logs = Join-Path $script:RuntimeDir 'logs'
  if (-not (Test-Path -LiteralPath $logs)) { New-Item -ItemType Directory -Path $logs -Force | Out-Null }
  $logItem = Get-Item -LiteralPath $logs -Force
  if (($logItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
      [IO.Path]::GetFullPath($logItem.FullName).TrimEnd('\') -ine [IO.Path]::GetFullPath($logs).TrimEnd('\')) {
    throw '.runtime/logs is not a project-owned directory; refusing service lifecycle writes.'
  }
  return $logs
}

function Test-LoopbackHttp([string]$Url, [int]$TimeoutSeconds = 5) {
  try {
    $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec $TimeoutSeconds -UseBasicParsing
    return $response.StatusCode -eq 200
  } catch { return $false }
}

function Get-ProcessTable {
  @(Get-CimInstance Win32_Process | ForEach-Object {
    @{ Id = [int]$_.ProcessId; ParentId = [int]$_.ParentProcessId; Path = [string]$_.ExecutablePath; CommandLine = [string]$_.CommandLine }
  })
}

function Get-ProcessOwner([int]$Id) {
  try {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction Stop
    $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner -ErrorAction Stop
    if ($owner.ReturnValue -ne 0) { return $null }
    return "$($owner.Domain)\$($owner.User)"
  } catch { return $null }
}

function Test-DescendantOf($ProcessTable, [int]$Candidate, [int]$Ancestor) {
  $byId = @{}; foreach ($p in $ProcessTable) { $byId[$p.Id] = $p }
  $cursor = $Candidate
  for ($i = 0; $i -lt 32 -and $byId.ContainsKey($cursor); $i++) {
    if ($cursor -eq $Ancestor) { return $true }
    $parent = $byId[$cursor].ParentId
    if ($parent -eq $cursor -or $parent -le 0) { break }
    $cursor = $parent
  }
  return $Candidate -eq $Ancestor
}

function Get-Listeners([int]$Port) {
  try {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
    return @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
  } catch {
    if ($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound,*') { return @() }
    throw "Could not verify listener ownership for port $Port; refusing lifecycle action."
  }
}

function Get-Connections([int]$Port, [string]$State) {
  try { return @(Get-NetTCPConnection -LocalPort $Port -State $State -ErrorAction Stop) }
  catch {
    if ($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound,*') { return @() }
    throw "Could not inspect $State connections for port $Port."
  }
}

function Get-ProcessStarted([int]$Id) {
  try { (Get-Process -Id $Id -ErrorAction Stop).StartTime.ToUniversalTime().ToString('o') } catch { $null }
}

function Test-RecordedRunner($ProcessInfo, $Record, [string]$ServiceName) {
  if (-not $ProcessInfo -or -not $Record) { return $false }
  if (([IO.Path]::GetFullPath([string]$Record.root) -ne $script:ProjectRoot) -or ([IO.Path]::GetFullPath([string]$Record.runner) -ne [IO.Path]::GetFullPath($script:Services[$ServiceName].Script))) { return $false }
  if (($ProcessInfo.Path -notmatch '(^|\\)powershell\.exe$') -or ($ProcessInfo.CommandLine.IndexOf([string]$Record.runner,[StringComparison]::OrdinalIgnoreCase) -lt 0) -or ($ProcessInfo.CommandLine.IndexOf($script:ProjectRoot,[StringComparison]::OrdinalIgnoreCase) -lt 0)) { return $false }
  try {
    $expected = [DateTimeOffset]::Parse([string]$Record.started_utc).UtcDateTime
    $actual = (Get-Process -Id $ProcessInfo.Id -ErrorAction Stop).StartTime.ToUniversalTime()
    return [Math]::Abs(($actual - $expected).TotalSeconds) -le 2
  } catch { return $false }
}

function Get-CheckoutServiceProcesses($ProcessTable, [string]$ServiceName) {
  $rootMarker = $script:ProjectRoot.TrimEnd('\') + '\'
  foreach ($processInfo in $ProcessTable) {
    if (-not $processInfo.CommandLine) { continue }
    $command = [string]$processInfo.CommandLine
    $checkoutMatch = $command.IndexOf($rootMarker,[StringComparison]::OrdinalIgnoreCase) -ge 0
    if (-not $checkoutMatch) { continue }
    $matchesService = switch ($ServiceName) {
      'api' { ($command -match 'scripts[\\/]api-service\.py' -or $command -match 'uvicorn\s+woori\.main:app') -and $command -match '\.venv[\\/]Scripts[\\/]python\.exe' }
      'dashboard' { $command -match 'scripts[\\/]dashboard-service\.js|apps[\\/]dashboard[\\/]node_modules[\\/].*next[\\/]dist[\\/]bin[\\/]next|--prefix\s+apps[\\/]dashboard' }
      'worker' { $command -match '\.venv[\\/]Scripts[\\/]python\.exe.*-m\s+woori\.worker' }
      'evaluation_worker' { $command -match 'scripts[\\/]run_evaluation_worker\.py' }
      'publication_worker' { $command -match 'scripts[\\/]publication-worker\.py' }
      default { $false }
    }
    if ($matchesService) { $processInfo }
  }
}

function Test-ExactCheckoutServiceProcess($ProcessInfo, [string]$ServiceName) {
  if (-not $ProcessInfo -or -not $ProcessInfo.CommandLine -or -not $ProcessInfo.Path) { return $false }
  $command = [string]$ProcessInfo.CommandLine
  $path = [IO.Path]::GetFullPath([string]$ProcessInfo.Path)
  $rootMarker = $script:ProjectRoot.TrimEnd('\') + '\'
  if ($command.IndexOf($rootMarker,[StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
  $python = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'))
  switch ($ServiceName) {
    'api' {
      $venvPythonCommand = $command -match ('(?i)^"' + [regex]::Escape($python) + '"\s+')
      $expectedInterpreter = $path -ieq $python -or
        ([IO.Path]::GetFileName($path) -ieq 'python.exe' -and $venvPythonCommand)
      return $expectedInterpreter -and (
        $command -match '(?i)(^|\s)scripts[\\/]api-service\.py(?:\s|$)' -or
        $command -match '(?i)(^|\s)-m\s+uvicorn\s+woori\.main:app(?:\s|$)'
      )
    }
    'dashboard' {
      $nextPaths = @(
        [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'apps\dashboard\node_modules\next\dist\bin\next')),
        [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'apps\dashboard\node_modules\next\dist\server\lib\start-server.js'))
      )
      $knownNext = @($nextPaths | Where-Object { $command.IndexOf($_,[StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
      if (-not $knownNext) { $knownNext = $command -match '(?i)apps[\\/]dashboard[\\/]node_modules[\\/]\.bin.*next[\\/]dist[\\/]bin[\\/]next' }
      $managedDashboardRunner = $command -match '(?i)(^|\s)scripts[\\/]dashboard-service\.js(?:\s|$)'
      return [IO.Path]::GetFileName($path) -ieq 'node.exe' -and ($knownNext -or $managedDashboardRunner) -and
        ($managedDashboardRunner -or $command -match '(?i)(?:^|\s)(dev|start)(?:\s|$)')
    }
    'worker' {
      $basePython = $null
      $venvConfig = Join-Path $script:ProjectRoot '.venv\pyvenv.cfg'
      if (Test-Path -LiteralPath $venvConfig -PathType Leaf) {
        $executableLine = Get-Content -LiteralPath $venvConfig -Encoding utf8 |
          Where-Object { $_ -match '^\s*executable\s*=\s*(.+?)\s*$' } | Select-Object -First 1
        if ($executableLine -match '^\s*executable\s*=\s*(.+?)\s*$') {
          try { $basePython = [IO.Path]::GetFullPath($Matches[1]) } catch { $basePython = $null }
        }
      }
      $pathIsProjectInterpreter = $path -ieq $python -or ($basePython -and $path -ieq $basePython)
      $quotedVenv = [regex]::Escape('"' + $python + '"')
      $workerOptions = '(?:\s+--(?:evaluation|once|diagnostic-only)|\s+--run-seconds\s+\d+)'
      return $pathIsProjectInterpreter -and
        $command -match ('^\s*' + $quotedVenv + '\s+-m\s+woori\.worker' + $workerOptions + '*\s*$')
    }
    'evaluation_worker' {
      $evaluationScript = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'scripts\run_evaluation_worker.py'))
      return $path -ieq $python -and $command.IndexOf($evaluationScript,[StringComparison]::OrdinalIgnoreCase) -ge 0
    }
    'publication_worker' {
      $workerScript = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot 'scripts\publication-worker.py'))
      $basePython = $null
      $venvConfig = Join-Path $script:ProjectRoot '.venv\pyvenv.cfg'
      if (Test-Path -LiteralPath $venvConfig -PathType Leaf) {
        $executableLine = Get-Content -LiteralPath $venvConfig -Encoding utf8 |
          Where-Object { $_ -match '^\s*executable\s*=\s*(.+?)\s*$' } | Select-Object -First 1
        if ($executableLine -match '^\s*executable\s*=\s*(.+?)\s*$') {
          try { $basePython = [IO.Path]::GetFullPath($Matches[1]) } catch { $basePython = $null }
        }
      }
      $pathIsProjectInterpreter = $path -ieq $python -or ($basePython -and $path -ieq $basePython)
      $quotedVenv = [regex]::Escape('"' + $python + '"')
      $absoluteScript = [regex]::Escape('"' + $workerScript + '"')
      $relativeScript = '(?:\.\\scripts\\publication-worker\.py|scripts\\publication-worker\.py)'
      $knownOption = '(?:--operations-(?:mock-only|confirmed-private-drafts|approved-live-publications|scheduled-auto|manual-confirmed|scheduled-auto-and-manual)|--continuous|--poll-seconds\s+\d+|--backoff-seconds\s+\d+)'
      $expectedInvocation = '^\s*' + $quotedVenv + '\s+(?:' + $absoluteScript + '|' + $relativeScript + ')(?:\s+' + $knownOption + ')*\s*$'
      return [IO.Path]::GetFileName($path) -ieq 'python.exe' -and $pathIsProjectInterpreter -and
        $command -match $expectedInvocation
    }
    default { return $false }
  }
}

function Get-ProcessDescendants($ProcessTable, [int]$Ancestor, [switch]$IncludeAncestor) {
  $byId = @{}
  foreach ($processInfo in $ProcessTable) { $byId[[int]$processInfo.Id] = $processInfo }
  $found = @{}
  $changed = $true
  while ($changed) {
    $changed = $false
    foreach ($processInfo in $ProcessTable) {
      $id = [int]$processInfo.Id
      if ($id -eq $Ancestor -or $found.ContainsKey($id)) { continue }
      $parent = [int]$processInfo.ParentId
      if ($parent -eq $Ancestor -or $found.ContainsKey($parent)) {
        $found[$id] = $processInfo
        $changed = $true
      }
    }
  }
  $result = @($found.Values | Sort-Object Id)
  if ($IncludeAncestor -and $byId.ContainsKey($Ancestor)) { $result = @($byId[$Ancestor]) + $result }
  return $result
}

function Test-SameProcessSnapshot($Original, $Current, [double]$StartTimeToleranceSeconds = 0.01) {
  if (-not $Original -or -not $Current) { return $false }
  if ([int]$Original.Id -ne [int]$Current.Id -or [int]$Original.ParentId -ne [int]$Current.ParentId) { return $false }
  if ([string]$Original.Path -ine [string]$Current.Path -or [string]$Original.CommandLine -cne [string]$Current.CommandLine) { return $false }
  if (-not $Original.StartedUtc -or -not $Current.StartedUtc) { return $false }
  try {
    $a = [DateTimeOffset]::Parse([string]$Original.StartedUtc).UtcDateTime
    $b = [DateTimeOffset]::Parse([string]$Current.StartedUtc).UtcDateTime
    return [Math]::Abs(($a - $b).TotalSeconds) -le $StartTimeToleranceSeconds
  } catch { return $false }
}

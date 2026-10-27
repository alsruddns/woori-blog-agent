$ErrorActionPreference = 'Stop'
$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:RuntimeDir = Join-Path $script:ProjectRoot '.runtime'
$script:ManifestPath = Join-Path $script:RuntimeDir 'servers.json'
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

function Get-ProcessTable {
  @(Get-CimInstance Win32_Process | ForEach-Object {
    @{ Id = [int]$_.ProcessId; ParentId = [int]$_.ParentProcessId; Path = [string]$_.ExecutablePath; CommandLine = [string]$_.CommandLine }
  })
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

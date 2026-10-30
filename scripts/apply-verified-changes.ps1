[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

function Invoke-GitText([string[]]$GitArgs) {
  $result = & git -C $script:ProjectRoot @GitArgs
  if ($LASTEXITCODE -ne 0) { throw "Git command failed: git $($GitArgs -join ' ')" }
  return @($result | ForEach-Object { [string]$_ })
}

function Invoke-CheckedCommand([string]$Executable, [string[]]$Arguments) {
  & $Executable @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Validation failed: $Executable $($Arguments -join ' ')" }
}

function Invoke-IsolatedDashboardBuild {
  $generatedFiles = @('apps/dashboard/next-env.d.ts','apps/dashboard/tsconfig.json')
  $snapshots = @{}
  foreach ($relative in $generatedFiles) {
    $path = Join-Path $script:ProjectRoot $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) { $snapshots[$path] = [IO.File]::ReadAllBytes($path) }
  }
  try { Invoke-CheckedCommand 'npm.cmd' @('run','build') }
  finally {
    foreach ($path in $snapshots.Keys) { [IO.File]::WriteAllBytes($path,[byte[]]$snapshots[$path]) }
  }
}

function Invoke-RepositoryValidation([string]$BuildDirectory, [string[]]$ChangedPaths, [string[]]$Targets) {
  $hadValue = Test-Path Env:WOORI_DASHBOARD_DIST_DIR
  $oldValue = $env:WOORI_DASHBOARD_DIST_DIR
  $generatedFiles = @('apps/dashboard/next-env.d.ts','apps/dashboard/tsconfig.json')
  $snapshots = @{}
  foreach ($relative in $generatedFiles) {
    $path = Join-Path $script:ProjectRoot $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) { $snapshots[$path] = [IO.File]::ReadAllBytes($path) }
  }
  $env:WOORI_DASHBOARD_DIST_DIR = $BuildDirectory
  try {
    $python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
    $psFiles = @($ChangedPaths | Where-Object { $_ -match '\.ps1$' } | ForEach-Object { Join-Path $script:ProjectRoot $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    foreach ($file in $psFiles) {
      $tokens=$null; $parseErrors=$null
      [System.Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$parseErrors) | Out-Null
      if ($parseErrors.Count) { throw "PowerShell parse failed: $file ($($parseErrors[0].Message))" }
    }
    if ($psFiles.Count) {
      $pester = Invoke-Pester -Script @((Join-Path $script:ProjectRoot 'scripts/tests/service-lifecycle.Tests.ps1'),(Join-Path $script:ProjectRoot 'scripts/tests/stop.Tests.ps1')) -PassThru
      if ($pester.FailedCount -gt 0) { throw "Pester failed ($($pester.FailedCount) failed tests)." }
    }

    $pythonFiles = @($ChangedPaths | Where-Object { $_ -match '\.py$' -and (Test-Path -LiteralPath (Join-Path $script:ProjectRoot $_) -PathType Leaf) })
    foreach ($file in $pythonFiles) {
      Invoke-CheckedCommand $python @('-m','ruff','check',(Join-Path $script:ProjectRoot $file))
      Invoke-CheckedCommand $python @('-m','py_compile',(Join-Path $script:ProjectRoot $file))
    }

    if (@($Targets | Where-Object { $_ -in @('api','research_worker','publication_worker') }).Count -or @($ChangedPaths | Where-Object { $_ -match '^services/api/' }).Count) {
      Invoke-CheckedCommand $python @('-m','ruff','check',(Join-Path $script:ProjectRoot 'services/api/woori'))
      $changedPythonModules = @($ChangedPaths | Where-Object { $_ -match '^services/api/woori/.*\.py$' } | ForEach-Object { Join-Path $script:ProjectRoot $_ })
      if ($changedPythonModules.Count) {
        Invoke-CheckedCommand $python (@('-m','mypy','--follow-imports=silent') + $changedPythonModules)
      }
      $changedApiTests = @($ChangedPaths | Where-Object { $_ -match '^services/api/tests/test_[^/]+\.py$' } | ForEach-Object { Join-Path $script:ProjectRoot $_ })
      if ($changedApiTests.Count) {
        Invoke-CheckedCommand $python (@('-m','pytest','-q') + $changedApiTests)
      } else {
        Invoke-CheckedCommand $python @('-m','pytest','-q')
      }
      Invoke-CheckedCommand $python @('scripts/build-wheel.py')
    }

    $dashboardChanged = @($Targets | Where-Object { $_ -eq 'dashboard' }).Count -or @($ChangedPaths | Where-Object { $_ -match '^apps/dashboard/' }).Count
    if ($dashboardChanged) {
      Invoke-CheckedCommand 'npm.cmd' @('run','lint')
      Invoke-CheckedCommand 'npm.cmd' @('run','typecheck')
    }
    # Always prepare a commit-specific isolated Production Build for the next
    # Dashboard start; never mutate the dist directory used by a running server.
    Invoke-IsolatedDashboardBuild
    $script:RepositoryVerificationExitCode = 0
  } finally {
    foreach ($path in $snapshots.Keys) { [IO.File]::WriteAllBytes($path,[byte[]]$snapshots[$path]) }
    if ($hadValue) { $env:WOORI_DASHBOARD_DIST_DIR = $oldValue }
    else { Remove-Item Env:WOORI_DASHBOARD_DIST_DIR -ErrorAction SilentlyContinue }
  }
}

if (-not $Apply) {
  Write-Output 'Preview only. Review the inferred diff, then pass -Apply to run verification and safely reflect committed changes.'
}
$branch = (Invoke-GitText @('branch','--show-current') | Select-Object -First 1)
if ($branch -cne 'develop') { throw 'Service reflection is restricted to the develop branch.' }
$head = (Invoke-GitText @('rev-parse','HEAD') | Select-Object -First 1)
if ($head -notmatch '^[0-9a-f]{40}$') { throw 'HEAD commit identity could not be verified.' }
$trackedChanges = @(Invoke-GitText @('status','--porcelain','--untracked-files=no'))
if ($trackedChanges.Count) { throw 'Commit or revert tracked work before service reflection; current source changes are not committed.' }

$manifest = Read-ServerManifest
$baselines = @($manifest.services.Values | ForEach-Object { [string]$_.applied_commit } | Where-Object { $_ -match '^[0-9a-f]{40}$' })
$base = $null
$longestDiff = -1
foreach ($candidate in ($baselines | Select-Object -Unique)) {
  $isAncestor = (& git -C $script:ProjectRoot merge-base --is-ancestor $candidate $head 2>$null); $ancestorExit=$LASTEXITCODE
  if ($ancestorExit -ne 0) { continue }
  $count = [int]((& git -C $script:ProjectRoot rev-list --count "$candidate..$head") -join '')
  if ($count -gt $longestDiff) { $base=$candidate; $longestDiff=$count }
}
if (-not $base) { $base = (Invoke-GitText @('rev-parse','HEAD^') | Select-Object -First 1) }
$paths = Invoke-GitText @('diff','--name-only',"$base..$head")
$dashboardBuildDir = '.next-p5-' + $head.Substring(0,12)
if (-not $paths.Count) {
  Write-Output "No committed source changes since runtime baseline $base; no service was restarted."
  return
}
 $migrationPaths = @($paths | Where-Object { $_ -match '(^|/)\d{3}_[^/]+\.sql$|(^|/)migrations?/' })
if ($migrationPaths.Count) {
  $requiredVersion = ($migrationPaths | ForEach-Object { [int]([regex]::Match($_,'(?:^|/)(\d{3})_').Groups[1].Value) } | Measure-Object -Maximum).Maximum
  $python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
  $statusOutput = & $python (Join-Path $script:ProjectRoot 'scripts\migrate.py') --status
  if ($LASTEXITCODE -ne 0) { throw 'Could not verify the operations schema version; no service was stopped.' }
  try { $schemaStatus = ($statusOutput -join "`n") | ConvertFrom-Json }
  catch { throw 'Operations schema status was not valid JSON; no service was stopped.' }
  if ($schemaStatus.database -cne 'woori_blog_agent' -or [int]$schemaStatus.schema_version -lt [int]$requiredVersion) {
    throw "Migration $requiredVersion is not applied to the expected operations database; run the backed-up migration procedure before service reflection. No service was stopped."
  }
}

$affected = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($path in $paths) {
  if ($path -match '^apps/dashboard/') { [void]$affected.Add('dashboard'); continue }
  if ($path -match '^services/api/woori/') {
    if ($path -match '^services/api/woori/(main|.*_routes|operations_dashboard)\.py$') { [void]$affected.Add('api'); continue }
    [void]$affected.Add('api')
    if ($path -match '(worker|pipeline|collection|topics|scheduled_import|trends|research|source|content|evidence)') { [void]$affected.Add('research_worker') }
    elseif ($path -match '(publication|blogger|post_publication)') { [void]$affected.Add('publication_worker') }
    else { [void]$affected.Add('research_worker'); [void]$affected.Add('publication_worker') }
    continue
  }
  if ($path -match '^scripts/publication-worker\.py$') { [void]$affected.Add('publication_worker'); continue }
  if ($path -match '^scripts/.*\.ps1$|^scripts/service-runtime-status\.py$|^scripts/tests/') { continue }
  if ($path -match '^apps/dashboard/(package|next|tsconfig)|^(package\.json|package-lock\.json|pnpm-lock\.yaml)$') { [void]$affected.Add('dashboard'); continue }
  if ($path -match '^scripts/(server-common|start|stop|status|start-services|manage-autostart|apply-verified-changes)\.ps1$') { continue }
}
if (-not $affected.Count) {
  if (-not $Apply) {
    Write-Output "No running service is affected by committed paths since $base; preview only and no service was restarted."
    return
  }
  $targets = @()
  Write-LifecycleLog 'service_reflection' 'validation_started' "commit=$head services=none"
  Invoke-RepositoryValidation $dashboardBuildDir $paths $targets
  if ($script:RepositoryVerificationExitCode -ne 0) {
    Write-LifecycleLog 'service_reflection' 'validation_failed' "commit=$head services=none"
    throw 'Repository verification failed; existing services were left running.'
  }
  if (@(Get-TrackedGitChanges).Count) { throw 'Verification left tracked source changes; no startup marker was recorded.' }
  Write-ValidatedSource $head @() $dashboardBuildDir
  Write-LifecycleLog 'service_reflection' 'validation_passed' "commit=$head services=none"
  Write-Output "Committed paths do not affect running services. Verification passed and HEAD $head was authorized for future startup; no service was restarted."
  return
}
$targets = @($affected | Sort-Object)
Write-Output "HEAD: $head`nRuntime baseline: $base`nAffected services: $($targets -join ', ')`nChanged paths:`n$($paths -join "`n")"

if ($Apply) {
  Write-LifecycleLog 'service_reflection' 'validation_started' "commit=$head services=$($targets -join ',')"
  # Run change-scoped PowerShell/Python/API/Dashboard checks before any stop
  # request, so a failed test or isolated production build leaves current
  # service processes untouched.
  Invoke-RepositoryValidation $dashboardBuildDir $paths $targets
  if ($script:RepositoryVerificationExitCode -ne 0) {
    Write-LifecycleLog 'service_reflection' 'validation_failed' "commit=$head services=$($targets -join ',')"
    throw 'Repository verification failed; existing services were left running.'
  }
  if (@(Get-TrackedGitChanges).Count) { throw 'Verification left tracked source changes; no startup marker was recorded and no service was stopped.' }
  Write-LifecycleLog 'service_reflection' 'validation_passed' "commit=$head services=$($targets -join ',')"
  Write-ValidatedSource $head $targets $dashboardBuildDir
}

if (-not $Apply) { return }
if (-not $PSCmdlet.ShouldProcess("$($targets -join ', ') at $head",'Safely stop and restart only affected services after successful verification')) { return }

foreach ($name in $targets) {
  $stopName = $name
  try {
    & (Join-Path $PSScriptRoot 'stop.ps1') -Service $stopName -Confirm:$false -TimeoutSeconds 180
    if ($LASTEXITCODE -ne 0) { throw 'graceful_stop_not_confirmed' }
  } catch {
    Write-LifecycleLog $name 'restart_aborted_on_stop' "commit=$head error_type=$($_.Exception.GetType().Name)"
    throw "Could not confirm graceful stop for $name. No force termination was attempted; remaining requested restarts were cancelled."
  }
}

foreach ($name in $targets) {
  try {
    switch ($name) {
      'dashboard' { & (Join-Path $PSScriptRoot 'start.ps1') -Service dashboard }
      'api' { & (Join-Path $PSScriptRoot 'start.ps1') -Service api }
      'research_worker' { & (Join-Path $PSScriptRoot 'start.ps1') -Service research_worker }
      'publication_worker' { & (Join-Path $PSScriptRoot 'start.ps1') -Service publication_worker -PublicationMode scheduled-auto-manual }
    }
    if ($LASTEXITCODE -ne 0) { throw 'start_script_failed' }
    Write-LifecycleLog $name 'source_reflected' "commit=$head"
  } catch {
    Write-LifecycleLog $name 'restart_failed' "commit=$head error_type=$($_.Exception.GetType().Name)"
    throw "Verified $name code could not be started. Inspect service logs; unrelated and already-started services were left untouched."
  }
}

Write-Output 'Post-reflection status:'
& (Join-Path $PSScriptRoot 'status.ps1')

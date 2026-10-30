[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param([ValidateSet('status','install','on','off','remove')][string]$Action='status')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')
$taskName = 'WooriBlogAgent-Worker'
$scriptPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'start-services.ps1'))
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Test-TaskOwnedByProject($Task) {
  try {
    if (-not $Task -or -not $Task.Actions -or $Task.Actions.Count -ne 1 -or -not $Task.Triggers) { return $false }
    $action = $Task.Actions[0]
    $arguments = [string]$action.Arguments
    $expectedScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'start-services.ps1'))
    $oldKnownScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'run-worker.ps1'))
    $normalizedArguments = $arguments.Replace('/','\')
    $pointsToProject = $normalizedArguments.IndexOf($expectedScript.Replace('/','\'),[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
      $normalizedArguments.IndexOf($oldKnownScript.Replace('/','\'),[StringComparison]::OrdinalIgnoreCase) -ge 0
    $workingDirectoryMatches = [string]$action.WorkingDirectory -and ([IO.Path]::GetFullPath([string]$action.WorkingDirectory) -ieq $script:ProjectRoot)
    $principalMatches = [string]$Task.Principal.UserId -ieq $currentUser -or
      [string]$Task.Triggers[0].UserId -ieq $currentUser
    $hasLogonTrigger = @($Task.Triggers | Where-Object { $_.CimClass.CimClassName -like '*LogonTrigger*' }).Count -gt 0
  } catch { return $false }
  return ([string]$action.Execute -match '(?i)(^|\\)powershell(?:\.exe)?$') -and $pointsToProject -and $workingDirectoryMatches -and $principalMatches -and $hasLogonTrigger
}

function Get-ProjectAutoTasks {
  $all = @(Get-ScheduledTask -ErrorAction SilentlyContinue)
  @($all | Where-Object {
    @($_.Actions | Where-Object {
      ([string]$_.Arguments).IndexOf($script:ProjectRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
      ([string]$_.Arguments -match '(?i)start-services\.ps1|run-worker\.ps1')
    }).Count -gt 0
  })
}

switch ($Action) {
  'status' {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) { [pscustomobject]@{ TaskName=$taskName; State='not_registered'; Enabled=$false; LogonTrigger=$false; Action=$scriptPath }; break }
    [pscustomobject]@{
      TaskName=$task.TaskName; State=$task.State; Enabled=[bool]$task.Settings.Enabled
      LogonTrigger=[bool](@($task.Triggers | Where-Object { $_.CimClass.CimClassName -like '*LogonTrigger*' }).Count)
      Action=$task.Actions[0].Arguments; OwnedByProject=(Test-TaskOwnedByProject $task)
      LastRun=(Get-ScheduledTaskInfo -TaskName $taskName).LastRunTime
      LastResult=(Get-ScheduledTaskInfo -TaskName $taskName).LastTaskResult
    }
  }
  'install' {
    foreach ($required in @('start-services.ps1','start.ps1','stop.ps1','status.ps1','start-research-worker.ps1','start-publication-worker.ps1','service-runtime-status.py')) {
      if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $required) -PathType Leaf)) { throw "Required service lifecycle file is missing: $required" }
    }
    $validated = Read-ValidatedSource
    if (-not $validated -or [string]$validated.commit -cne (Get-CurrentGitCommit) -or @(Get-TrackedGitChanges).Count) {
      throw 'Install the login task only after the current clean develop HEAD passes scripts/apply-verified-changes.ps1 -Apply.'
    }
    $projectTasks = @(Get-ProjectAutoTasks)
    if ($projectTasks.Count -gt 1) { throw "Multiple project login tasks exist ($($projectTasks.TaskName -join ', ')); no task was changed." }
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task -and -not (Test-TaskOwnedByProject $task)) { throw "Task '$taskName' exists but its ownership cannot be proved. No task was changed." }
    if ($task) {
      if ($task.Actions[0].Arguments.IndexOf($scriptPath,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        if (-not $task.Settings.Enabled -and $PSCmdlet.ShouldProcess($taskName,'Enable the existing login auto-start task')) { Enable-ScheduledTask -TaskName $taskName | Out-Null }
        Write-Output "Task '$taskName' already points to this project's startup coordinator; registration was not duplicated."
        break
      }
      if ($PSCmdlet.ShouldProcess($taskName,'Replace the existing project-owned worker-only action with the four-service startup coordinator while preserving its login trigger and settings')) {
        $actionObject = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`"" -WorkingDirectory $script:ProjectRoot
        Set-ScheduledTask -TaskName $taskName -Action $actionObject | Out-Null
        Enable-ScheduledTask -TaskName $taskName | Out-Null
        Write-Output "Updated existing project-owned task '$taskName'; its user-logon trigger, principal, and retry settings were preserved."
      }
      break
    }
    if ($projectTasks.Count -eq 1) { throw "Project startup task '$($projectTasks[0].TaskName)' already exists under a different name; refusing duplicate registration." }
    if ($PSCmdlet.ShouldProcess($taskName,"Register a current-user interactive logon task for $scriptPath")) {
      $actionObject = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`"" -WorkingDirectory $script:ProjectRoot
      $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
      $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
      $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
      Register-ScheduledTask -TaskName $taskName -Action $actionObject -Trigger $trigger -Settings $settings -Principal $principal -Description 'Start the four local Woori Blog Agent services after the current user logs in.' | Out-Null
      Write-Output "Registered '$taskName' for interactive user logon."
    }
  }
  'on' {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not (Test-TaskOwnedByProject $task) -or $task.Actions[0].Arguments.IndexOf($scriptPath,[StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'The verified four-service startup task is not installed; run -Action install first.' }
    if ($PSCmdlet.ShouldProcess($taskName,'Enable login auto-start')) {
      Enable-ScheduledTask -TaskName $taskName | Out-Null
      Write-Output "Login auto-start is enabled for '$taskName'."
    } else { Write-Output "WhatIf only: login auto-start state was not changed for '$taskName'." }
  }
  'off' {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not (Test-TaskOwnedByProject $task)) { throw 'The project startup task is absent or ownership cannot be proved.' }
    if ($PSCmdlet.ShouldProcess($taskName,'Disable login auto-start without stopping running services')) {
      Disable-ScheduledTask -TaskName $taskName | Out-Null
      Write-Output "Login auto-start is disabled. Running services were not stopped."
    } else { Write-Output 'WhatIf only: auto-start was not disabled and running services were not changed.' }
  }
  'remove' {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not (Test-TaskOwnedByProject $task)) { throw 'The project startup task is absent or ownership cannot be proved.' }
    if ($PSCmdlet.ShouldProcess($taskName,'Remove the verified project login task without stopping running services')) {
      Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
      Write-Output "Login task '$taskName' removed; running services were not stopped."
    } else {
      Write-Output "WhatIf only: login task '$taskName' remains registered; running services were not stopped."
    }
  }
}

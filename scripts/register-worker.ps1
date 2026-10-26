# Opt-in local Task Scheduler registration. Run explicitly after reviewing.
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$PSScriptRoot/run-worker.ps1`"" -WorkingDirectory (Split-Path $PSScriptRoot -Parent)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'WooriBlogAgent-Worker' -Action $action -Trigger $trigger -Settings $settings -Description 'Local diagnostic worker; no external publishing' -ErrorAction Stop

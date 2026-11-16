$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
foreach ($kind in @('Worker','Backup')) {
    $name = "WooriBlogAgent-$kind"
    $script = if ($kind -eq 'Worker') { "$PSScriptRoot/run-worker.ps1" } else { "$PSScriptRoot/run-maintenance.ps1" }
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) { throw "Task $name already exists; review it before changes" }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$script`"" -WorkingDirectory $root
    $triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $user)
    if ($kind -eq 'Backup') { $triggers += New-ScheduledTaskTrigger -Daily -At '03:00' }
    $duration = if ($kind -eq 'Worker') { [TimeSpan]::Zero } else { New-TimeSpan -Hours 1 }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit $duration -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Woori Blog Agent local project task' | Out-Null
    Start-ScheduledTask -TaskName $name
    Write-Output "$name registered and started"
}

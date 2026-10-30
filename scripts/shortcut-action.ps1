param(
  [ValidateSet('start_all','start_dashboard','start_api','start_research','start_publication','status','stop_all','restart_all')]
  [string]$Action
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

try {
  switch ($Action) {
    'start_all' {
      Remove-IntentionalStopMarkerForExplicitStart
      $states = @(& (Join-Path $PSScriptRoot 'status.ps1'))
      $processes = Get-ProcessTable
      $allReady = $true
      foreach ($serviceName in @('api','dashboard','research_worker','publication_worker')) {
        $stateName = if ($serviceName -eq 'research_worker') { 'worker' } else { $serviceName }
        $state = $states | Where-Object Service -eq $stateName | Select-Object -First 1
        if (-not $state -or -not $state.ProjectOwned -or -not $state.PID) { $allReady = $false; break }
        $process = $processes | Where-Object Id -eq ([int]$state.PID) | Select-Object -First 1
        $processKind = if ($serviceName -eq 'research_worker') { 'worker' } else { $serviceName }
        if (-not $process -or -not (Test-ExactCheckoutServiceProcess $process $processKind)) { $allReady = $false; break }
        if ($serviceName -in @('api','dashboard')) {
          $healthUrl = if ($serviceName -eq 'api') { 'http://127.0.0.1:8100/health' } else { 'http://127.0.0.1:3100/research' }
          if ($state.State -ne 'listening' -or -not (Test-LoopbackHttp $healthUrl 5)) { $allReady = $false; break }
        } elseif ($state.HeartbeatState -ne 'fresh') {
          $allReady = $false; break
        } elseif ($serviceName -eq 'publication_worker' -and $state.ExecutionMode -ne 'scheduled-auto-manual-trends') {
          $allReady = $false; break
        } elseif ($serviceName -eq 'research_worker' -and $state.ExecutionMode -ne 'research') {
          $allReady = $false; break
        }
      }
      if ($allReady) {
        Write-LifecycleLog 'all_services' 'already_ready' 'all_four_services_healthy_no_process_started'
        Write-Output 'All four services are already healthy; no duplicate process was started.'
      } else {
        & (Join-Path $PSScriptRoot 'start-services.ps1') -ExplicitUserStart
      }
    }
    'start_dashboard' { Remove-IntentionalStopMarkerForExplicitStart; & (Join-Path $PSScriptRoot 'start.ps1') -Service dashboard }
    'start_api' { Remove-IntentionalStopMarkerForExplicitStart; & (Join-Path $PSScriptRoot 'start.ps1') -Service api }
    'start_research' { Remove-IntentionalStopMarkerForExplicitStart; & (Join-Path $PSScriptRoot 'start.ps1') -Service research_worker }
    'start_publication' {
      Remove-IntentionalStopMarkerForExplicitStart
      & (Join-Path $PSScriptRoot 'start.ps1') -Service publication_worker -PublicationMode scheduled-auto-manual-trends
    }
    'status' {
      $status = & (Join-Path $PSScriptRoot 'status.ps1')
      $report = Join-Path (Get-ProjectLogDirectory) 'service-status.txt'
      $contents = "Woori Blog Agent service status`r`nChecked: $([DateTimeOffset]::Now.ToString('yyyy-MM-dd HH:mm:ss zzz'))`r`nCommit: $(Get-CurrentGitCommit)`r`n`r`n" + ($status | Format-List * | Out-String)
      [IO.File]::WriteAllText($report,$contents,(New-Object System.Text.UTF8Encoding($false)))
      Write-LifecycleLog 'desktop_shortcut' 'status_report_written' "path=$report"
      Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $report + '"')
      return
    }
    'stop_all' { & (Join-Path $PSScriptRoot 'stop-services.ps1') }
    'restart_all' { & (Join-Path $PSScriptRoot 'restart-services.ps1') }
  }
  Write-LifecycleLog 'desktop_shortcut' 'action_completed' "action=$Action"
} catch {
  $message = ([string]$_.Exception.Message -replace '[\r\n]+',' ') -replace '\s+',' '
  Write-LifecycleLog 'desktop_shortcut' 'action_failed' "action=$Action error_type=$($_.Exception.GetType().Name) detail=$($message.Substring(0,[Math]::Min(300,$message.Length)))"
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $logPath = Join-Path $script:RuntimeDir 'logs\service-lifecycle.log'
    [void][System.Windows.Forms.MessageBox]::Show("$Action failed`r`n$message`r`n`r`nLog: $logPath",'Woori Blog Agent',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Error)
  } catch { Write-Host "ACTION FAILED: $Action; $message" }
  exit 1
}

if ($Action -in @('stop_all','restart_all')) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $verb = if ($Action -eq 'stop_all') { 'All services stopped' } else { 'All services restarted' }
    [void][System.Windows.Forms.MessageBox]::Show("$verb`r`nService state and PIDs were recorded in .runtime/logs/service-lifecycle.log",'Woori Blog Agent',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Information)
  } catch { }
}

param(
  [ValidateSet('start_all','start_dashboard','start_api','start_research','start_publication','status','stop_all','restart_all')]
  [string]$Action
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

try {
  switch ($Action) {
    'start_all' {
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
        } elseif ($serviceName -eq 'publication_worker' -and $state.ExecutionMode -ne 'scheduled-auto-and-manual') {
          $allReady = $false; break
        } elseif ($serviceName -eq 'research_worker' -and $state.ExecutionMode -ne 'research') {
          $allReady = $false; break
        }
      }
      if ($allReady) {
        Write-LifecycleLog 'all_services' 'already_ready' 'all_four_services_healthy_no_process_started'
        Write-Output 'All four services are already healthy; no duplicate process was started.'
      } else {
        & (Join-Path $PSScriptRoot 'start-services.ps1')
      }
    }
    'start_dashboard' { & (Join-Path $PSScriptRoot 'start.ps1') -Service dashboard }
    'start_api' { & (Join-Path $PSScriptRoot 'start.ps1') -Service api }
    'start_research' { & (Join-Path $PSScriptRoot 'start.ps1') -Service research_worker }
    'start_publication' {
      & (Join-Path $PSScriptRoot 'start.ps1') -Service publication_worker -PublicationMode scheduled-auto-manual
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
  exit 1
}

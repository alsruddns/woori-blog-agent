. (Join-Path $PSScriptRoot '..\server-common.ps1')
. (Join-Path $PSScriptRoot '..\stop.ps1')
. (Join-Path $PSScriptRoot '..\manage-autostart.ps1') -Action status

Describe 'Windows service lifecycle ownership and startup policy' {
  It 'classifies an exact project Python Worker and excludes a different checkout' {
    $python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
    $owned = [pscustomobject]@{ Id=410; ParentId=1; Path=$python; CommandLine="`"$python`" -m woori.worker" }
    $foreign = [pscustomobject]@{ Id=411; ParentId=1; Path='C:\other\.venv\Scripts\python.exe'; CommandLine='"C:\other\.venv\Scripts\python.exe" -m woori.worker' }
    (Test-ExactCheckoutServiceProcess $owned 'worker') | Should Be $true
    (Test-ExactCheckoutServiceProcess $foreign 'worker') | Should Be $false
  }

  It 'does not count a Python launcher ancestor as a second Worker process' {
    $table = @(
      [pscustomobject]@{ Id=420; ParentId=1; Path='C:\Python\python.exe'; CommandLine='"C:\repo\.venv\Scripts\python.exe" -m woori.worker' },
      [pscustomobject]@{ Id=421; ParentId=420; Path='C:\Python\python.exe'; CommandLine='"C:\repo\.venv\Scripts\python.exe" -m woori.worker' }
    )
    (Test-DescendantOf $table 421 420) | Should Be $true
  }

  It 'keeps research-worker shutdown separate from the evaluation worker' {
    $root=$script:ProjectRoot; $venv=Join-Path $root '.venv\Scripts\python.exe'
    $base='C:\Users\achie\AppData\Local\Programs\Python\Python313\python.exe'
    $launcher=[pscustomobject]@{ Id=510; ParentId=1; Path=$venv; CommandLine="`"$venv`" -m woori.worker" }
    $research=[pscustomobject]@{ Id=511; ParentId=510; Path=$base; CommandLine="`"$venv`" -m woori.worker" }
    $evaluation=[pscustomobject]@{ Id=512; ParentId=1; Path=$venv; CommandLine="`"$venv`" -m woori.worker --evaluation" }
    Mock Get-ProcessStarted { '2026-10-30T00:00:00.0000000Z' }
    $found=@(Get-StopCandidates research_worker @($launcher,$research,$evaluation))
    @($found.Id).Count | Should Be 1
    $found[0].Id | Should Be 511
    $found[0].WorkerService | Should Be 'research_worker'
    $legacy=@(Get-StopCandidates worker @($launcher,$research,$evaluation))
    @($legacy.Id).Count | Should Be 1
    $legacy[0].WorkerService | Should Be 'research_worker'
  }

  It 'recognizes only the current project logon action and refuses another checkout' {
    $current = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $path = Join-Path $script:ProjectRoot 'scripts\start-services.ps1'
    $task = [pscustomobject]@{
      Actions=@([pscustomobject]@{ Execute='powershell.exe'; Arguments="-File `"$path`""; WorkingDirectory=$script:ProjectRoot })
      Principal=[pscustomobject]@{ UserId=$current }
      Triggers=@([pscustomobject]@{ UserId=$current; CimClass=[pscustomobject]@{ CimClassName='MSFT_TaskLogonTrigger' } })
    }
    (Test-TaskOwnedByProject $task) | Should Be $true
    $task.Actions[0].Arguments = '-File "C:\other\scripts\start-services.ps1"'
    (Test-TaskOwnedByProject $task) | Should Be $false
  }

  It 'keeps startup detached from per-save triggers and gates scheduled Auto explicitly' {
    $bootstrap = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\start-services.ps1') -Raw
    $bootstrap | Should Match 'start-publication-worker\.ps1|start\.ps1'
    $bootstrap | Should Match 'scheduled-auto'
    $bootstrap | Should Match 'Postgres'
    $bootstrap | Should Match 'already_ready'
    $autostart = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\manage-autostart.ps1') -Raw
    $autostart | Should Match 'MultipleInstances IgnoreNew'
    $autostart | Should Match 'AtLogOn'
  }

  It 'builds Dashboard into an isolated commit-specific directory before reflection' {
    $apply=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\apply-verified-changes.ps1') -Raw
    $runner=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\run-dashboard.ps1') -Raw
    $apply | Should Match 'WOORI_DASHBOARD_DIST_DIR'
    $apply | Should Match '\.next-p5-'
    $runner | Should Match 'validated-source\.json'
    $runner | Should Match 'dashboard_build_dir'
  }

  It 'requires a clean committed develop state and runs verification before stop requests' {
    $apply = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\apply-verified-changes.ps1') -Raw
    $apply.IndexOf('Invoke-RepositoryValidation $dashboardBuildDir $paths $targets') | Should BeLessThan $apply.IndexOf("'stop.ps1'")
    $apply | Should Match "branch.*develop"
    $apply | Should Match 'migrations?'
  $apply | Should Match 'migrate\.py.*--status'
  $apply | Should Match 'schemaStatus\.schema_version'
  }

  It 'keeps login startup publication mode aligned with the verified combined worker mode' {
    $bootstrap = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\start-services.ps1') -Raw
    $bootstrap | Should Match 'scheduled-auto-and-manual'
    $bootstrap | Should Match 'start\.ps1.*PublicationMode scheduled-auto-manual'
    $bootstrap | Should Not Match 'PublicationMode scheduled-auto(?:\s|$)'
  }

  It 'defines the eight project desktop shortcuts and hides the PowerShell launcher' {
    $creator = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\create-desktop-shortcuts.ps1') -Raw
    $creator | Should Match 'DesktopDirectory'
    $creator | Should Match 'WindowStyle Hidden'
    foreach ($action in @('start_all','start_dashboard','start_api','start_research','start_publication','status','stop_all','restart_all')) {
      $creator | Should Match ([regex]::Escape("Action='$action'"))
    }
    $creator | Should Match 'shortcut_created_or_updated'
  }

  It 'makes whole-start idempotent against already healthy services without requiring reflection restart' {
    $launcher=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\shortcut-action.ps1') -Raw
    $launcher | Should Match 'all_four_services_healthy_no_process_started'
    $launcher | Should Match 'Test-ExactCheckoutServiceProcess'
    $launcher | Should Match 'HeartbeatState -ne ''fresh'''
    $launcher | Should Match 'scheduled-auto-and-manual'
  }

  It 'uses cooperative identity-bound stop channels for API and Dashboard processes' {
    $api = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\api-service.py') -Raw
    $dashboard = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\dashboard-service.js') -Raw
    $stopper = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\stop.ps1') -Raw
    $api | Should Match 'server\.should_exit = True'
    $dashboard | Should Match 'server\.close\('
    $stopper | Should Match 'Write-HttpServiceStopRequest'
    $stopper | Should Not Match 'Stop-Process -Id.*\$serviceSnapshot'
  }

  It 'stops workers before HTTP services and only starts after verified full shutdown' {
    $stopper = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\stop-services.ps1') -Raw
    $restarter = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\restart-services.ps1') -Raw
    $stopper.IndexOf("'publication_worker'") | Should BeLessThan $stopper.IndexOf("'dashboard'")
    $stopper | Should Match 'shutdown_aborted_for_active_worker'
    $restarter.IndexOf('stop-services.ps1') | Should BeLessThan $restarter.IndexOf('start-services.ps1')
  }

  It 'reads the current commit before any pipeline changes the native exit code' {
    (Get-CurrentGitCommit) | Should Match '^[0-9a-f]{40}$'
  }
}

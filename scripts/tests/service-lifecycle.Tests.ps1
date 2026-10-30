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

  It 'recognizes the Windows venv Python shim using its exact checkout command path' {
    $venv = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
    $basePython = [pscustomobject]@{ Id=412; ParentId=1; Path='C:\Users\achie\AppData\Local\Programs\Python\Python313\python.exe'; CommandLine="`"$venv`" -m uvicorn woori.main:app --host 127.0.0.1 --port 8100" }
    (Test-ExactCheckoutServiceProcess $basePython 'api') | Should Be $true
    $basePython.CommandLine = '"C:\other\.venv\Scripts\python.exe" -m uvicorn woori.main:app'
    (Test-ExactCheckoutServiceProcess $basePython 'api') | Should Be $false
  }

  It 'recognizes the project API and Dashboard cooperative launch commands by exact absolute script path' {
    $root=$script:ProjectRoot
    $venv=Join-Path $root '.venv\Scripts\python.exe'
    $api=[pscustomobject]@{Id=413;ParentId=1;Path='C:\Users\achie\AppData\Local\Programs\Python\Python313\python.exe';CommandLine="`"$venv`" `"$(Join-Path $root 'scripts\api-service.py')`""}
    $dashboard=[pscustomobject]@{Id=414;ParentId=1;Path='C:\nvm4w\nodejs\node.exe';CommandLine="`"C:\nvm4w\nodejs\node.exe`" $(Join-Path $root 'scripts\dashboard-service.js')"}
    (Test-ExactCheckoutServiceProcess $api 'api') | Should Be $true
    (Test-ExactCheckoutServiceProcess $dashboard 'dashboard') | Should Be $true
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
    $bootstrap | Should Match 'start\.ps1.*PublicationMode scheduled-auto-manual-trends'
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
    $launcher | Should Match 'scheduled-auto-manual-trends'
  }

  It 'uses cooperative stop channels when available and bounds verified legacy shutdown' {
    $api = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\api-service.py') -Raw
    $dashboard = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\dashboard-service.js') -Raw
    $stopper = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\stop.ps1') -Raw
    $api | Should Match 'server\.should_exit = True'
    $dashboard | Should Match 'server\.close\('
    $stopper | Should Match 'Write-HttpServiceStopRequest'
    $stopper | Should Not Match 'Stop-Process -Id.*\$serviceSnapshot'
    $stopper | Should Match 'AllowVerifiedLegacyFallback'
    $stopper | Should Match 'verified_legacy_fallback_started'
    $stopper | Should Match 'Get-ProcessOwner'
  }

  It 'stops workers before HTTP services and only starts after verified full shutdown' {
    $stopper = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\stop-services.ps1') -Raw
    $restarter = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\restart-services.ps1') -Raw
    $stopper.IndexOf("'publication_worker'") | Should BeLessThan $stopper.IndexOf("'dashboard'")
    $stopper | Should Match 'shutdown_aborted_for_active_worker'
    $stopper.IndexOf('Assert-HttpTreeOwned') | Should BeLessThan $stopper.IndexOf('foreach ($name in $targets)')
    $stopper | Should Match 'legacy_process_verified_for_graceful_then_bounded_stop'
    $restarter.IndexOf('stop-services.ps1') | Should BeLessThan $restarter.IndexOf('start-services.ps1')
  }

  It 'suppresses logon recovery after a user stop and only clears it for explicit starts' {
    $common=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\server-common.ps1') -Raw
    $bootstrap=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\start-services.ps1') -Raw
    $stopper=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\stop-services.ps1') -Raw
    $common | Should Match 'intentional-stop\.json'
    $common | Should Match 'session_id'
    $bootstrap | Should Match 'suppressed_after_intentional_stop'
    $bootstrap | Should Match 'ExplicitUserStart'
    $stopper | Should Match 'Write-IntentionalStopMarker'
    $stopper | Should Match '\$wholeStopTimeoutSeconds = \$TimeoutSeconds'
    $stopper | Should Match '\$TimeoutSeconds = \$wholeStopTimeoutSeconds'
    $reflection=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\apply-verified-changes.ps1') -Raw
    $reflection | Should Match 'restart_suppressed_after_intentional_stop'
  }

  It 'verifies full shutdown and new PID replacement before restart success' {
    $restarter=Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'scripts\restart-services.ps1') -Raw
    $restarter | Should Match 'restart_stop_verified'
    $restarter | Should Match 'old_pids'
    $restarter | Should Match 'new_pids'
    $restarter | Should Match 'operations-scheduled-auto-and-manual-and-trends'
    $restarter | Should Match 'Test-LoopbackHttp'
  }

  It 'reads the current commit before any pipeline changes the native exit code' {
    (Get-CurrentGitCommit) | Should Match '^[0-9a-f]{40}$'
  }
}

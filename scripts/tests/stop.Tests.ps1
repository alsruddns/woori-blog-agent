 . (Join-Path $PSScriptRoot '..\stop.ps1')
function Initialize-StopTestContext {
  $script:Root = $script:ProjectRoot
  $script:Python = Join-Path $script:Root '.venv\Scripts\python.exe'
  $script:Started = '2026-10-29T03:00:00.0000000Z'
}

function Initialize-ManagedApiFixture {
  $script:RunnerProcess = [pscustomobject]@{
    Id=601; ParentId=1; Path='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    CommandLine="powershell -File `"$script:Root\scripts\run-api.ps1`""
  }
  $script:ApiProcess = [pscustomobject]@{
    Id=602; ParentId=601; Path=$script:Python
    CommandLine="`"$script:Python`" -m uvicorn woori.main:app --host 127.0.0.1 --port 8100"
  }
  $script:ApiRecord = @{ pid=601; runner=(Join-Path $script:Root 'scripts\run-api.ps1'); root=$script:Root; started_utc=$script:Started }
  $script:ApiManifest = @{ services=@{ api=$script:ApiRecord } }
}

Describe 'Safe stop process discovery' {
  BeforeEach { Initialize-StopTestContext }
  It 'includes only exact checkout service executables and excludes unrelated apps' {
    $table = @(
      [pscustomobject]@{ Id=101; ParentId=1; Path=$script:Python; CommandLine="`"$script:Python`" -m uvicorn woori.main:app --app-dir `"$script:Root\services\api`"" },
      [pscustomobject]@{ Id=102; ParentId=1; Path='C:\other\.venv\Scripts\python.exe'; CommandLine='C:\other\.venv\Scripts\python.exe -m uvicorn woori.main:app C:\other\services\api' },
      [pscustomobject]@{ Id=103; ParentId=1; Path='C:\Program Files\PostgreSQL\16\bin\postgres.exe'; CommandLine='postgres -D C:\db' },
      [pscustomobject]@{ Id=104; ParentId=1; Path='C:\Program Files\Microsoft VS Code\Code.exe'; CommandLine="Code.exe $script:Root\scripts\run-worker.ps1" },
      [pscustomobject]@{ Id=105; ParentId=1; Path='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'; CommandLine="powershell -File $script:Root\scripts\run-worker.ps1" }
    )

    $found = @(Get-StopCandidates api $table)
    @($found.Id).Count | Should Be 1
    $found[0].Id | Should Be 101
  }

  It 'deduplicates repeated process snapshots but retains distinct service instances' {
    $command = "`"$script:Python`" -m uvicorn woori.main:app --app-dir `"$script:Root\services\api`""
    $one = [pscustomobject]@{ Id=111; ParentId=1; Path=$script:Python; CommandLine=$command }
    $two = [pscustomobject]@{ Id=112; ParentId=1; Path=$script:Python; CommandLine=$command }
    Mock Get-ProcessStarted { $script:Started }

    $found = @(Get-StopCandidates api @($one,$one,$two))

    @($found.Id).Count | Should Be 2
    (@($found.Id) -contains 111) | Should Be $true
    (@($found.Id) -contains 112) | Should Be $true
  }

  It 'recognizes the checkout Next process launched through npm.cmd wrappers' {
    $node = [pscustomobject]@{
      Id=115; ParentId=114; Path='C:\nvm4w\nodejs\node.exe'
      CommandLine="`"node`" `"$script:Root\apps\dashboard\node_modules\.bin\..\next\dist\bin\next`" start --hostname 127.0.0.1 --port 3100"
    }
    (Test-ExactCheckoutServiceProcess $node dashboard) | Should Be $true
  }

  It 'does not treat a reused PID as the original process snapshot' {
    $old = [pscustomobject]@{ Id=101; ParentId=1; Path=$script:Python; CommandLine='python -m woori.worker'; StartedUtc=$script:Started }
    $reused = [pscustomobject]@{ Id=101; ParentId=1; Path=$script:Python; CommandLine='python -m unrelated.app'; StartedUtc='2026-10-29T03:02:00.0000000Z' }
    (Test-SameProcessSnapshot $old $reused) | Should Be $false
  }

  It 'returns descendants without including an ancestor PowerShell terminal' {
    $table = @(
      [pscustomobject]@{ Id=200; ParentId=10; Path='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'; CommandLine='powershell -NoExit' },
      [pscustomobject]@{ Id=201; ParentId=200; Path='C:\Program Files\nodejs\node.exe'; CommandLine='node project next dev' },
      [pscustomobject]@{ Id=202; ParentId=201; Path='C:\Windows\System32\cmd.exe'; CommandLine='cmd /c next dev' }
    )
    $tree = @(Get-ProcessDescendants $table 201)
    @($tree.Id).Count | Should Be 1
    $tree[0].Id | Should Be 202
    (@((Get-ProcessDescendants $table 201 -IncludeAncestor).Id) -contains 201) | Should Be $true
    (@((Get-ProcessDescendants $table 201 -IncludeAncestor).Id) -contains 200) | Should Be $false
  }

  It 'does not count an established connection between two managed service processes as an external client' {
    Mock Get-NetTCPConnection {
      @(
        [pscustomobject]@{ OwningProcess=501; LocalAddress='127.0.0.1'; LocalPort=57854; RemoteAddress='127.0.0.1'; RemotePort=57853 },
        [pscustomobject]@{ OwningProcess=502; LocalAddress='127.0.0.1'; LocalPort=57853; RemoteAddress='127.0.0.1'; RemotePort=57854 },
        [pscustomobject]@{ OwningProcess=501; LocalAddress='127.0.0.1'; LocalPort=57855; RemoteAddress='127.0.0.1'; RemotePort=57856 }
      )
    }

    (Get-EstablishedConnectionCount @(501,502)) | Should Be 1
  }
}

Describe 'Worker stop behavior' {
  BeforeEach { Initialize-StopTestContext }
  It 'requests cooperative stop and never force terminates an active worker' {
    $worker = [pscustomobject]@{
      Id=301; ParentId=1; Path=$script:Python
      CommandLine="`"$script:Python`" -m woori.worker"; StartedUtc=$script:Started
      Kind='worker'; ProcessInfo=[pscustomobject]@{ Id=301; ParentId=1; Path=$script:Python; CommandLine="`"$script:Python`" -m woori.worker" }
    }
    Mock Get-ProcessTable { @($worker.ProcessInfo) }
    Mock Get-ProcessStarted { $script:Started }
    Mock Read-ServerManifest { @{ services=@{} } }
    Mock Write-WorkerStopRequest { Join-Path $TestDrive 'worker-stop-301.json' }
    Mock Wait-ForSnapshotsExit { @($worker) }
    Mock Stop-Process { throw 'Stop-Process must never be called for workers.' }

    $ok = Invoke-ProjectStop worker 1 $true -Confirm:$false

    $ok | Should Be $false
    Assert-MockCalled Write-WorkerStopRequest -Times 1
    Assert-MockCalled Stop-Process -Times 0
  }
}

Describe 'Explicit force confirmation' {
  BeforeEach { Initialize-StopTestContext }

  It 'requires the exact service and PID phrase after -Force' {
    $snapshot = [pscustomobject]@{ Id=401 }
    $script:Force = $true
    Mock Read-Host { 'FORCE api 401' }
    (Confirm-ForceAction api @($snapshot)) | Should Be $true
    Assert-MockCalled Read-Host -Times 1 -ParameterFilter { $Prompt -eq 'Type FORCE api 401 to continue' }
  }

  It 'does not request force termination without the -Force switch' {
    $snapshot = [pscustomobject]@{ Id=401 }
    $script:Force = $false
    Mock Read-Host { throw 'Read-Host must not be called without -Force.' }
    (Confirm-ForceAction api @($snapshot)) | Should Be $false
    Assert-MockCalled Read-Host -Times 0 -Scope It
  }

  It 'force helper targets only a still-identical exact API process snapshot' {
    Initialize-ManagedApiFixture
    $script:StopProcessTable = @($script:RunnerProcess,$script:ApiProcess)
    $snapshot = [pscustomobject]@{
      Id=602; ParentId=601; Path=$script:Python; CommandLine=$script:ApiProcess.CommandLine
      StartedUtc=$script:Started; Kind='api'; ProcessInfo=$script:ApiProcess
    }
    Mock Test-SnapshotStillSame { $true }
    Mock Stop-Process { }

    Invoke-ForceManagedStop api @($snapshot)

    Assert-MockCalled Stop-Process -Times 1 -Scope It -ParameterFilter { $Id -eq 602 }
  }
}

Describe 'Managed API shutdown flow' {
  BeforeEach {
    Initialize-StopTestContext
    Initialize-ManagedApiFixture
    Mock Get-ProcessTable { @($script:RunnerProcess,$script:ApiProcess) }
    Mock Get-ProcessStarted { $script:Started }
    Mock Test-RecordedRunner { $true }
    Mock Read-ServerManifest { $script:ApiManifest }
    Mock Write-ServerManifest { }
    Mock Get-EstablishedConnectionCount { 0 }
  }

  It 'tries graceful close first and clears only the matching manifest after exit' {
    Mock Request-GracefulClose { $true }
    Mock Wait-ForSnapshotsExit { @() }

    $ok = Invoke-ProjectStop api 5 $false -Confirm:$false

    $ok | Should Be $true
    Assert-MockCalled Request-GracefulClose -Times 1 -Scope It
    Assert-MockCalled Wait-ForSnapshotsExit -Times 1 -Scope It
    Assert-MockCalled Write-ServerManifest -Times 1 -Scope It
  }

  It 'leaves the verified process tree intact when force confirmation is declined' {
    Mock Request-GracefulClose { $false }
    Mock Wait-ForSnapshotsExit { @($script:RunnerProcess) }
    Mock Confirm-ForceAction { $false }
    Mock Stop-Process { throw 'A denied force confirmation must not stop anything.' }

    $ok = Invoke-ProjectStop api 5 $true -Confirm:$false

    $ok | Should Be $false
    Assert-MockCalled Confirm-ForceAction -Times 1 -Scope It
    Assert-MockCalled Stop-Process -Times 0 -Scope It
  }
}

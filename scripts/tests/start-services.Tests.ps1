. (Join-Path $PSScriptRoot '..\start-services.ps1') -FunctionsOnly

Describe 'Startup coordinator regressions' {
  BeforeEach {
    Mock Write-LifecycleLog { }
    Mock Start-Sleep { }
  }

  It 'accepts only documentation descendants of the tested commit' {
    (Test-ValidatedStartupSource 'fb724962463182809aacbd7f5ee54ba833313fab' 'ac769952f1dd1af9eb498a0bd1f35a129cbc6999') | Should Be $true
    (Test-ValidatedStartupSource 'bb088c485194856f41da17a79983a45c73f2289b' 'ac769952f1dd1af9eb498a0bd1f35a129cbc6999') | Should Be $false
    (Test-ValidatedStartupSource 'invalid' 'ac769952f1dd1af9eb498a0bd1f35a129cbc6999') | Should Be $false
  }

  It 'does not launch a duplicate healthy API' {
    Mock Get-Listeners { @(110) }
    Mock Get-ProcessTable { @([pscustomobject]@{Id=110}) }
    Mock Test-ExactCheckoutServiceProcess { $true }
    Mock Test-LoopbackHttp { $true }
    Mock Invoke-StartupChild { throw 'must not run' }
    Ensure-HttpService 'api' 8100 'http://127.0.0.1:8100/health'
    Assert-MockCalled Invoke-StartupChild -Times 0 -Exactly -Scope It
  }

  It 'rejects mixed local and foreign listeners even when HTTP succeeds' {
    Mock Get-Listeners { @(110,111) }
    Mock Get-ProcessTable { @([pscustomobject]@{Id=110},[pscustomobject]@{Id=111}) }
    Mock Test-ExactCheckoutServiceProcess { $ProcessInfo.Id -eq 110 }
    Mock Invoke-StartupChild { throw 'must not run' }
    { Ensure-HttpService 'api' 8100 'http://127.0.0.1:8100/health' } | Should Throw
    Assert-MockCalled Invoke-StartupChild -Times 0 -Exactly -Scope It
  }

  It 'leaves an unhealthy existing API untouched' {
    Mock Get-Listeners { @(110) }
    Mock Get-ProcessTable { @([pscustomobject]@{Id=110}) }
    Mock Test-ExactCheckoutServiceProcess { $true }
    Mock Test-LoopbackHttp { $false }
    Mock Invoke-StartupChild { throw 'must not run' }
    { Ensure-HttpService 'api' 8100 'http://127.0.0.1:8100/health' } | Should Throw
    Assert-MockCalled Invoke-StartupChild -Times 0 -Exactly -Scope It
  }

  It 'preserves a healthy manual publication worker without a mode transition' {
    Mock Get-ProcessTable { @([pscustomobject]@{Id=110;CommandLine='python publication-worker.py --operations-manual-confirmed --continuous'}) }
    Mock Test-ExactCheckoutServiceProcess { $true }
    Mock Get-PublicationStartupStatus { @{exit=0;value=@{heartbeat_fresh=$true;heartbeat=@{process_id=110}}} }
    Mock Invoke-StartupChild { throw 'must not run' }
    Ensure-PublicationWorker
    Assert-MockCalled Invoke-StartupChild -Times 0 -Exactly -Scope It
  }

  It 'refuses a stale existing Research Worker without starting another' {
    Mock Invoke-ReadinessJson { @{exit=5;value=@{process_id=110;ready=$false}} }
    Mock Get-ProcessTable { @([pscustomobject]@{Id=110}) }
    Mock Get-CheckoutServiceProcesses { @([pscustomobject]@{Id=110}) }
    Mock Test-ExactCheckoutServiceProcess { $true }
    Mock Invoke-StartupChild { throw 'must not run' }
    { Ensure-ResearchWorker } | Should Throw
    Assert-MockCalled Invoke-StartupChild -Times 0 -Exactly -Scope It
  }

  It 'uses the immediate native child failure code' {
    $path=Join-Path $TestDrive 'failure.ps1'
    Set-Content -LiteralPath $path -Value 'exit 17'
    (Invoke-StartupProcess $path @()) | Should Be 17
  }

  It 'does not reuse a stale caller failure code after child success' {
    $global:LASTEXITCODE=19
    $path=Join-Path $TestDrive 'success.ps1'
    Set-Content -LiteralPath $path -Value 'exit 0'
    (Invoke-StartupProcess $path @()) | Should Be 0
  }

  It 'uses the same checkout and owner scoped global mutex name' {
    (Get-StartupMutexName) | Should Match '^Global\\WooriBlogAgent-Startup-[A-F0-9]{64}$'
    (Get-StartupMutexName) | Should Be (Get-StartupMutexName)
  }

  It 'waits only for the launcher when a hidden detached child remains alive' {
    $path=Join-Path $TestDrive 'detached.ps1'
    Set-Content -LiteralPath $path -Value @'
Start-Process powershell.exe -ArgumentList '-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 4"' -WindowStyle Hidden
exit 0
'@
    $timer=[Diagnostics.Stopwatch]::StartNew()
    (Invoke-StartupProcess $path @()) | Should Be 0
    $timer.Elapsed.TotalSeconds | Should BeLessThan 4
  }
}

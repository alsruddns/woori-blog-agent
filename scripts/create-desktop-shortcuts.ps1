[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')

$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if (-not $desktop -or -not (Test-Path -LiteralPath $desktop -PathType Container)) {
  throw 'The current Windows user Desktop directory could not be resolved.'
}
$launcher = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'shortcut-action.ps1'))
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$workingDirectory = $script:ProjectRoot
$definitions = @(
  @{ Name='Woori Blog Agent 전체 시작'; Action='start_all' },
  @{ Name='Woori Blog Agent Dashboard 시작'; Action='start_dashboard' },
  @{ Name='Woori Blog Agent Backend API 시작'; Action='start_api' },
  @{ Name='Woori Blog Agent Research Worker 시작'; Action='start_research' },
  @{ Name='Woori Blog Agent Publication Worker 시작'; Action='start_publication' },
  @{ Name='Woori Blog Agent 전체 상태 확인'; Action='status' },
  @{ Name='Woori Blog Agent 전체 종료'; Action='stop_all' },
  @{ Name='Woori Blog Agent 전체 재시작'; Action='restart_all' }
)

$shell = New-Object -ComObject WScript.Shell
try {
  foreach ($definition in $definitions) {
    $shortcutPath = Join-Path $desktop ($definition.Name + '.lnk')
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
      $current = $shell.CreateShortcut($shortcutPath)
      $currentArgs = [string]$current.Arguments
      $currentDirectory = [string]$current.WorkingDirectory
      $currentTarget = [string]$current.TargetPath
      if ($currentArgs.IndexOf($launcher,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or
          -not $currentDirectory -or [IO.Path]::GetFullPath($currentDirectory) -ine $workingDirectory -or
          [IO.Path]::GetFileName($currentTarget) -ine 'powershell.exe') {
        throw "A same-name Desktop shortcut is not owned by this project and was left unchanged: $shortcutPath"
      }
    } elseif (-not $PSCmdlet.ShouldProcess($shortcutPath,'Create project-owned background service shortcut')) {
      continue
    }

    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -Action $($definition.Action)"
    $shortcut.WorkingDirectory = $workingDirectory
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Manage the local Woori Blog Agent services.'
    $shortcut.IconLocation = "$powershell,0"
    $shortcut.Save()
    Write-LifecycleLog 'desktop_shortcut' 'shortcut_created_or_updated' "name=$($definition.Name) action=$($definition.Action)"
    Write-Output "$($definition.Name): $shortcutPath"
  }
} finally {
  if ($shell) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) }
}

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ((git branch --show-current) -ne 'develop') { throw 'Verification/development must run on develop' }
$commands = @(
    @{ Exe='.venv/Scripts/python.exe'; Args=@('-m','ruff','check','.') },
    @{ Exe='.venv/Scripts/python.exe'; Args=@('-m','mypy','services/api/woori') },
    @{ Exe='.venv/Scripts/python.exe'; Args=@('-m','pytest','-q') },
    @{ Exe='.venv/Scripts/python.exe'; Args=@('scripts/build-wheel.py') },
    @{ Exe='npm.cmd'; Args=@('run','lint') },
    @{ Exe='npm.cmd'; Args=@('run','build') },
    @{ Exe='npm.cmd'; Args=@('run','typecheck') }
)
foreach ($step in $commands) {
    & $step.Exe @($step.Args)
    if ($LASTEXITCODE -ne 0) { throw "Validation failed: $($step.Exe) $($step.Args -join ' ')" }
}
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Whitespace validation failed' }

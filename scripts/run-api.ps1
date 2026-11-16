$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $python (Join-Path $PSScriptRoot 'api-service.py')
exit $LASTEXITCODE

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .venv/Scripts/python.exe -m woori.worker
exit $LASTEXITCODE

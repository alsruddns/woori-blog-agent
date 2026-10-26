$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .venv/Scripts/python.exe -m uvicorn woori.main:app --host 127.0.0.1 --port 8000
exit $LASTEXITCODE

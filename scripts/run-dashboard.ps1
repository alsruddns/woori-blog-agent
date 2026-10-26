$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& npm.cmd --prefix apps/dashboard run start
exit $LASTEXITCODE

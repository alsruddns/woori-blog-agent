param([ValidateSet('api','dashboard','all')][string]$Service='all')
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'stop.ps1') -Service $Service
if ($LASTEXITCODE -ne 0) { throw 'Graceful stop was not confirmed; restart cancelled.' }
& (Join-Path $PSScriptRoot 'start.ps1') -Service $Service

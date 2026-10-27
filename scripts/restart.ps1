param([ValidateSet('api','dashboard','ai','all')][string]$Service='all',[string]$AiModel,[ValidateSet(1,2,3,4)][int]$AiThreads=4,[ValidateSet('cpu','vulkan')][string]$AiBackend='cpu')
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'stop.ps1') -Service $Service
if ($LASTEXITCODE -ne 0) { throw 'Graceful stop was not confirmed; restart cancelled.' }
& (Join-Path $PSScriptRoot 'start.ps1') -Service $Service -AiModel $AiModel -AiThreads $AiThreads -AiBackend $AiBackend

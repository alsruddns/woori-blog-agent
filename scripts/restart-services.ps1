$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'server-common.ps1')
Write-LifecycleLog 'all_services' 'restart_started' 'stop_then_start'
& (Join-Path $PSScriptRoot 'stop-services.ps1')
& (Join-Path $PSScriptRoot 'start-services.ps1')
Write-LifecycleLog 'all_services' 'restart_complete' 'services=dashboard,api,research_worker,publication_worker'

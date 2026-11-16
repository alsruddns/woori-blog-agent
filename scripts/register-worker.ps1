# Backward-compatible entry point. Registration is idempotent and manages the
# four local services through the single current-user logon task.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'manage-autostart.ps1') -Action install
exit $LASTEXITCODE

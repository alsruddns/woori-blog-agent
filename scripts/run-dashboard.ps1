$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$validatedSource = Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime\validated-source.json'
if (Test-Path -LiteralPath $validatedSource -PathType Leaf) {
  try { $marker = Get-Content -LiteralPath $validatedSource -Raw -Encoding utf8 | ConvertFrom-Json }
  catch { throw 'Validated source marker is invalid; Dashboard did not start.' }
  $buildDir = [string]$marker.dashboard_build_dir
  if ($buildDir -notmatch '^\.next-p5-[a-z0-9-]+$' -or -not (Test-Path -LiteralPath (Join-Path (Get-Location) "apps\dashboard\$buildDir") -PathType Container)) {
    throw 'A validated isolated Production Build is not available; Dashboard did not start.'
  }
  $env:WOORI_DASHBOARD_DIST_DIR = $buildDir
}
& npm.cmd --prefix apps/dashboard run start
exit $LASTEXITCODE

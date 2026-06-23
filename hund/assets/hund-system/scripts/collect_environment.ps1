Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Compatibility entrypoint for environment collection.
& (Join-Path $PSScriptRoot 'init_hund.ps1')
exit $LASTEXITCODE

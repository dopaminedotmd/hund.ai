Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Compatibility entrypoint for validation.
& (Join-Path $PSScriptRoot 'validate_hund.ps1')
exit $LASTEXITCODE

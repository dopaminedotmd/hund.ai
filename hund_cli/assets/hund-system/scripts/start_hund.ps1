Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Official compatibility entrypoint. Delegates to boot_hund.ps1.
& (Join-Path $PSScriptRoot 'boot_hund.ps1')
exit $LASTEXITCODE

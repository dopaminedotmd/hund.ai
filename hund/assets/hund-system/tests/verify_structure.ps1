Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '..\scripts\validate_hund.ps1')
exit $LASTEXITCODE

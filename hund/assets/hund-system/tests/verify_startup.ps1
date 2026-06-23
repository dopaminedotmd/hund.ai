Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workParent = Join-Path ([System.IO.Path]::GetTempPath()) ('hund-startup-test-' + (Get-Date).ToString('yyyyMMddHHmmss'))
New-Item -ItemType Directory -Path $workParent -Force | Out-Null
$testRoot = Join-Path $workParent (Split-Path -Leaf $root)
Copy-Item -Path $root -Destination $testRoot -Recurse -Force
& (Join-Path $testRoot 'scripts\boot_hund.ps1')
$code = $LASTEXITCODE
if ($code -ne 0) { exit $code }
$envPath = Join-Path $testRoot '.state\environment.json'
if (-not (Test-Path $envPath)) {
    Write-Host 'FAIL: environment.json missing after startup test'
    exit 3
}
Write-Host "STARTUP TEST PASSED: $testRoot"
exit 0

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\hund_common.ps1')

$root = Get-HundRoot
$bank = Read-HundText (Join-Path $root 'REASONING_BANK.md')
$summary = Read-HundText (Join-Path $root 'memory_summary.md')
if ($bank -notmatch '(?m)^\[\d{4}-\d{2}-\d{2}\] \[[A-Z]+\] Lärdom:' -or $bank -notmatch 'Kontext:' -or $bank -notmatch 'Regel:') {
    Write-Host 'FAIL: reasoning bank format incomplete'
    exit 4
}
if ($summary -notmatch 'Lärdom:' -or $summary -notmatch 'Kontext:' -or $summary -notmatch 'Regel:') {
    Write-Host 'FAIL: memory summary lost block fields'
    exit 4
}
Write-Host 'MEMORY TEST PASSED'
exit 0

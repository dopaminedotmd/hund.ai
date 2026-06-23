Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\hund_common.ps1')

$root = Get-HundRoot
$failed = $false
Get-ChildItem -Path $root -Recurse -File -Include *.md,*.ps1,*.json |
    Where-Object { $_.FullName -notlike '*\_backups\*' } |
    ForEach-Object {
        try {
            $text = Read-HundText $_.FullName
            if (Test-HundMojibake $text) {
                Write-Host "FAIL: mojibake $($_.FullName)"
                $script:failed = $true
            }
        }
        catch {
            Write-Host "FAIL: utf8 $($_.FullName) $($_.Exception.Message)"
            $script:failed = $true
        }
    }
if ($failed) { exit 2 }
Write-Host 'ENCODING TEST PASSED'
exit 0

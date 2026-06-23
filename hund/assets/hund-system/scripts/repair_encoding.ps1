Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hund_common.ps1')

$root = Get-HundRoot
$targets = Get-ChildItem -Path $root -Recurse -File -Include *.md,*.ps1,*.json |
    Where-Object { $_.FullName -notlike '*\_backups\*' }

$backup = New-HundBackup -Reason 'repair-encoding' -Files @(
    'hund.md', 'RUNTIME_POLICY.md', 'SKILL.md', 'REASONING_BANK.md', 'memory_summary.md',
    'AGENTS.md', 'rules\PROTECTED_PATHS.md', 'rules\FILE_ROUTING.md', 'skills\SKILL_INDEX.md'
)

foreach ($file in $targets) {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $text = $null
    try {
        $strict = Get-HundUtf8StrictEncoding
        $text = $strict.GetString($bytes)
    }
    catch {
        $text = [System.Text.Encoding]::Default.GetString($bytes)
    }

    if (Test-HundMojibake $text) {
        Write-Host "WARN: possible mojibake remains in $($file.FullName)"
    }

    if ($file.Extension -ieq '.ps1') {
        $utf8Bom = New-Object System.Text.UTF8Encoding -ArgumentList $true
        [System.IO.File]::WriteAllText($file.FullName, $text, $utf8Bom)
    }
    else {
        Write-HundText -Path $file.FullName -Content $text
    }
}

Write-HundStatus "Encoding normalization complete. Backup: $backup"

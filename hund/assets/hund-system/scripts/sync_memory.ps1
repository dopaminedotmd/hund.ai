Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hund_common.ps1')

function Convert-HundMemoryEntries {
    param([Parameter(Mandatory=$true)][string]$Content)

    $entries = New-Object System.Collections.Generic.List[string]
    $current = New-Object System.Collections.Generic.List[string]
    $lines = $Content -split "`r?`n"

    foreach ($line in $lines) {
        if ($line -match '^\[\d{4}-\d{2}-\d{2}\] \[[A-Z]+\] Lärdom:') {
            if ($current.Count -gt 0) {
                $entries.Add(($current -join [Environment]::NewLine).Trim())
                $current.Clear()
            }
            $current.Add($line)
            continue
        }

        if ($current.Count -gt 0) {
            if ($line -match '^(Kontext|Regel):') {
                $current.Add($line)
            }
            elseif ([string]::IsNullOrWhiteSpace($line)) {
                $entries.Add(($current -join [Environment]::NewLine).Trim())
                $current.Clear()
            }
        }
    }

    if ($current.Count -gt 0) {
        $entries.Add(($current -join [Environment]::NewLine).Trim())
    }

    return @($entries.ToArray())
}

function Format-HundEntryForSummary {
    param([Parameter(Mandatory=$true)][string]$Entry)

    $lines = $Entry -split "`r?`n"
    $head = $lines[0]
    if ($head -notmatch '^\[(?<date>\d{4}-\d{2}-\d{2})\] \[(?<domain>[A-Z]+)\] Lärdom: (?<lesson>.*)$') {
        return $null
    }

    $date = $Matches['date']
    $domain = $Matches['domain']
    $lesson = $Matches['lesson']
    $context = ''
    $rule = ''

    foreach ($line in $lines[1..($lines.Count - 1)]) {
        if ($line -match '^Kontext: (?<value>.*)$') { $context = $Matches['value'] }
        if ($line -match '^Regel: (?<value>.*)$') { $rule = $Matches['value'] }
    }

    $block = "### [$date] [$domain]" + [Environment]::NewLine
    $block += "Lärdom: $lesson" + [Environment]::NewLine
    if ($context) { $block += "Kontext: $context" + [Environment]::NewLine }
    if ($rule) { $block += "Regel: $rule" + [Environment]::NewLine }
    return $block.TrimEnd()
}

$root = Get-HundRoot
$bankPath = Join-Path $root 'REASONING_BANK.md'
$summaryPath = Join-Path $root 'memory_summary.md'

Assert-HundInsideRoot $bankPath
Assert-HundInsideRoot $summaryPath

Write-HundStatus 'Syncing memory bank into memory_summary.md.'

$bank = Read-HundText $bankPath
if (Test-HundMojibake $bank) {
    throw 'REASONING_BANK.md contains mojibake markers. Refusing to sync corrupted memory.'
}

$entries = Convert-HundMemoryEntries $bank
$formatted = New-Object System.Collections.Generic.List[string]
foreach ($entry in $entries) {
    $block = Format-HundEntryForSummary $entry
    if ($null -ne $block) { $formatted.Add($block) }
}

$body = ''
if ($formatted.Count -gt 0) {
    $body = ($formatted.ToArray() -join ([Environment]::NewLine + [Environment]::NewLine))
}
else {
    $body = '_Inga minnesposter ännu._'
}

$newContent = @"
# hund — Konsoliderat Långtidsminne

Denna fil innehåller hunds konsoliderade minne, lärdomar och etablerade mönster över tid. Den uppdateras via `scripts/sync_memory.ps1`.

---

## KÄRNMINNEN & LÄRDOMAR

$body

---

## AKTUELT FOKUS & INSTRUKTIONER

- Tala alltid i tredje person som "hund".
- Inga emojis eller slang.
- Bibehåll en filosofisk men varm och precis underton.
- Använd verktyg när verkligheten behöver verifieras.
- Läs före skriv, backup före risk, verifiera efter handling.
"@

$backup = New-HundBackup -Reason 'sync-memory' -Files @('memory_summary.md')
Write-HundText -Path $summaryPath -Content $newContent

$verify = Read-HundText $summaryPath
if (Test-HundMojibake $verify) {
    throw 'Verification failed: memory_summary.md contains mojibake markers after sync.'
}
if ($entries.Count -gt 0 -and ($verify -notmatch 'Kontext:' -or $verify -notmatch 'Regel:')) {
    throw 'Verification failed: summary lost Kontext or Regel lines.'
}

Write-HundStatus "memory_summary.md synced with $($formatted.Count) entries. Backup: $backup"

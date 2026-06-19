Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hund_common.ps1')

$root = Get-HundRoot
$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Message)
    $script:failures.Add($Message)
    Write-Host ("FAIL: " + $Message)
}

function Add-Pass {
    param([string]$Message)
    Write-Host ("PASS: " + $Message)
}

$required = @(
    'hund.md',
    'RUNTIME_POLICY.md',
    'SKILL.md',
    'REASONING_BANK.md',
    'memory_summary.md',
    'AGENTS.md',
    'rules\PROTECTED_PATHS.md',
    'rules\FILE_ROUTING.md',
    'skills\SKILL_INDEX.md',
    '.state\manifest.json',
    'scripts\hund_common.ps1',
    'scripts\init_hund.ps1',
    'scripts\sync_memory.ps1',
    'scripts\validate_hund.ps1',
    'scripts\boot_hund.ps1',
    'scripts\start_hund.ps1',
    'scripts\collect_environment.ps1',
    'scripts\verify_hund.ps1',
    'scripts\repair_encoding.ps1',
    'tests\verify_structure.ps1',
    'tests\verify_encoding.ps1',
    'tests\verify_memory.ps1',
    'tests\verify_startup.ps1'
)

foreach ($rel in $required) {
    $path = Join-Path $root $rel
    if (Test-Path $path) { Add-Pass "exists $rel" } else { Add-Failure "missing $rel" }
}

$textFiles = @($required | Where-Object { $_ -match '\.(md|ps1|json)$' })
foreach ($rel in $textFiles) {
    $path = Join-Path $root $rel
    if (-not (Test-Path $path)) { continue }
    try {
        $txt = Read-HundText $path
        Add-Pass "utf8 $rel"
        if (Test-HundMojibake $txt) {
            Add-Failure "mojibake markers in $rel"
        }
    }
    catch {
        Add-Failure "invalid utf8 $rel : $($_.Exception.Message)"
    }
}

try {
    $manifestPath = Join-Path $root '.state\manifest.json'
    $manifest = Read-HundText $manifestPath | ConvertFrom-Json
    if ($manifest.system_name -eq 'hund-system' -and $manifest.persona_file -eq 'hund.md') {
        Add-Pass 'manifest json valid'
    }
    else {
        Add-Failure 'manifest json missing expected identity fields'
    }
}
catch {
    Add-Failure "manifest json invalid : $($_.Exception.Message)"
}

try {
    $hund = Read-HundText (Join-Path $root 'hund.md')
    if ($hund -match '<!-- HUND_ENVIRONMENT_BEGIN -->' -and $hund -match '<!-- HUND_ENVIRONMENT_END -->') {
        Add-Pass 'environment markers in hund.md'
    }
    else {
        Add-Failure 'environment markers missing in hund.md'
    }
    if ($hund -match 'hund talar \*\*alltid i tredje person\*\*') {
        Add-Pass 'persona third-person rule present'
    }
    else {
        Add-Failure 'persona third-person rule missing'
    }
}
catch {
    Add-Failure "could not inspect hund.md : $($_.Exception.Message)"
}

$scriptFiles = Get-ChildItem -Path (Join-Path $root 'scripts') -Filter '*.ps1' -File
$testScriptFiles = Get-ChildItem -Path (Join-Path $root 'tests') -Filter '*.ps1' -File -ErrorAction SilentlyContinue
foreach ($script in @($scriptFiles) + @($testScriptFiles)) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors -and $errors.Count -gt 0) {
        Add-Failure "parse errors in $($script.FullName): $($errors.Count)"
    }
    else {
        Add-Pass "parse $($script.Name)"
    }
}

if ($failures.Count -gt 0) {
    Write-Host ''
    Write-Host "VALIDATION FAILED: $($failures.Count) issue(s)."
    exit 1
}

Write-Host ''
Write-Host 'VALIDATION PASSED'
exit 0

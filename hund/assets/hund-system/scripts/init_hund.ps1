Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hund_common.ps1')

function Get-SafeValue {
    param(
        [Parameter(Mandatory=$true)][scriptblock]$ScriptBlock,
        [string]$Fallback = 'unknown'
    )
    try {
        $value = & $ScriptBlock
        if ($null -eq $value) { return $Fallback }
        if ($value -is [array]) {
            $items = @($value | ForEach-Object { if ($null -ne $_) { $_.ToString().Trim() } } | Where-Object { $_ })
            if ($items.Count -eq 0) { return $Fallback }
            return ($items -join ' + ')
        }
        $text = $value.ToString().Trim()
        if ([string]::IsNullOrWhiteSpace($text)) { return $Fallback }
        return $text
    }
    catch {
        return $Fallback
    }
}

$root = Get-HundRoot
$hundPath = Join-Path $root 'hund.md'
$stateDir = Join-Path $root '.state'
$statePath = Join-Path $stateDir 'environment.json'

Assert-HundInsideRoot $hundPath
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

Write-HundStatus 'Analyzing current Windows environment.'

$os = Get-SafeValue { (Get-CimInstance Win32_OperatingSystem).Caption }
$cpu = Get-SafeValue { Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name }
$ramKb = Get-SafeValue { (Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize }
$ramGb = 'unknown'
if ($ramKb -ne 'unknown') {
    $ramGb = [math]::Round(([double]$ramKb / 1MB), 0).ToString()
}
$gpu = Get-SafeValue { Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name }
$hostName = Get-SafeValue { hostname }
$psVersion = $PSVersionTable.PSVersion.ToString()
$generatedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')

$envInfo = [ordered]@{
    generated_at = $generatedAt
    os = $os
    powershell_version = $psVersion
    hostname = $hostName
    cpu = $cpu
    ram_gb = $ramGb
    gpu = $gpu
    hund_root = $root
}

$backup = New-HundBackup -Reason 'init' -Files @('hund.md', '.state\environment.json')

$content = Read-HundText $hundPath
$begin = '<!-- HUND_ENVIRONMENT_BEGIN -->'
$end = '<!-- HUND_ENVIRONMENT_END -->'
$pattern = '(?s)' + [regex]::Escape($begin) + '.*?' + [regex]::Escape($end)
if ($content -notmatch $pattern) {
    throw 'Environment marker block missing in hund.md. Refusing unsafe edit.'
}

$newBlock = @"
$begin
**Körmiljö:** Windows PowerShell $psVersion på $os
**Hårdvara:** $cpu, $ramGb GB RAM, $gpu ($hostName)
**Senast analyserad:** $generatedAt
$end
"@

$updated = [regex]::Replace($content, $pattern, $newBlock, 1)
Write-HundText -Path $hundPath -Content $updated

$json = $envInfo | ConvertTo-Json -Depth 5
Write-HundText -Path $statePath -Content ($json + [Environment]::NewLine)

$verify = Read-HundText $hundPath
if ($verify -notmatch [regex]::Escape($hostName)) {
    throw 'Verification failed: hostname was not written to hund.md.'
}
if (Test-HundMojibake $verify) {
    throw 'Verification failed: hund.md contains mojibake markers after init.'
}

Write-HundStatus "Environment written to hund.md and .state/environment.json. Backup: $backup"
Write-HundStatus "Detected: $os | $cpu | $ramGb GB RAM | $gpu | $hostName"

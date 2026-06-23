Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:HundRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Get-HundRoot {
    return $script:HundRoot
}

function Get-HundTimestamp {
    return (Get-Date).ToString('yyyyMMdd-HHmmss')
}

function Get-HundUtf8NoBomEncoding {
    return New-Object System.Text.UTF8Encoding -ArgumentList $false
}

function Get-HundUtf8StrictEncoding {
    return New-Object System.Text.UTF8Encoding -ArgumentList @($false, $true)
}

function Read-HundText {
    param([Parameter(Mandatory=$true)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $enc = Get-HundUtf8StrictEncoding
    return [System.IO.File]::ReadAllText($full, $enc)
}

function Write-HundText {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Content
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $dir = [System.IO.Path]::GetDirectoryName($full)
    if (-not [System.IO.Directory]::Exists($dir)) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
    }
    $enc = Get-HundUtf8NoBomEncoding
    [System.IO.File]::WriteAllText($full, $Content, $enc)
}

function New-HundBackup {
    param(
        [Parameter(Mandatory=$true)][string]$Reason,
        [Parameter(Mandatory=$true)][string[]]$Files
    )
    $safeReason = ($Reason -replace '[^a-zA-Z0-9_-]', '-')
    $backupRoot = Join-Path (Get-HundRoot) '_backups'
    $backupDir = Join-Path $backupRoot ('auto-' + (Get-HundTimestamp) + '-' + $safeReason)
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    foreach ($file in $Files) {
        $source = Join-Path (Get-HundRoot) $file
        if (Test-Path $source) {
            $target = Join-Path $backupDir $file
            $targetDir = Split-Path -Parent $target
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            Copy-Item -Path $source -Destination $target -Force
        }
    }
    return $backupDir
}

function Assert-HundInsideRoot {
    param([Parameter(Mandatory=$true)][string]$Path)
    $root = [System.IO.Path]::GetFullPath((Get-HundRoot))
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside hund root: $full"
    }
}

function Test-HundMojibake {
    param([Parameter(Mandatory=$true)][string]$Content)
    $patterns = @(
        ([string][char]0x00C3 + [string][char]0x00A4),
        ([string][char]0x00C3 + [string][char]0x00A5),
        ([string][char]0x00C3 + [string][char]0x00B6),
        ([string][char]0x00C3 + [string][char]0x0084),
        ([string][char]0x00C3 + [string][char]0x0085),
        ([string][char]0x00C3 + [string][char]0x0096),
        ([string][char]0x00E2 + [string][char]0x20AC),
        ([string][char]0xFFFD)
    )
    foreach ($pattern in $patterns) {
        if ($Content.Contains($pattern)) { return $true }
    }
    return $false
}

function Write-HundStatus {
    param([Parameter(Mandatory=$true)][string]$Message)
    Write-Host ("[hund] " + $Message)
}

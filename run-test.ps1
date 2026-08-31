# run-test.ps1 — interactive isolated launcher for reproducible test homes
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)][Alias('Home')][string]$Persona,
    [string]$Workspace,
    [switch]$Fresh,
    [switch]$Reset,
    [string]$ConfirmResetPath,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$HundArgs
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/test-home-boundary.ps1')
$repoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$testRoot = Get-TestHomeRoot -RepoRoot $repoRoot
$homesRoot = Join-Path $testRoot 'homes'
$workspacesRoot = Join-Path $testRoot 'workspaces'
$personaBase = Get-ConfinedTestPath -BasePath $homesRoot -Segment $Persona -Name 'Home'
$workspaceName = if ($Workspace) { $Workspace } else { $Persona }
$workspacePath = Get-ConfinedTestPath -BasePath $workspacesRoot -Segment $workspaceName -Name 'Workspace'
$hundHome = Join-Path $personaBase 'hund'
$hundExe = Join-Path $repoRoot '.venv/Scripts/hund.exe'

if (-not (Test-Path -LiteralPath $hundExe -PathType Leaf)) { throw "Cannot start Hund: executable not found at '$hundExe'." }
if ($Reset -and -not $Fresh) { throw 'Reset requires Fresh.' }
if ($ConfirmResetPath -and (-not $Reset -or -not $Fresh)) { throw 'ConfirmResetPath requires Fresh and Reset.' }
if ($Fresh -and (Test-Path -LiteralPath $personaBase)) {
    if (-not ($Reset -and $ConfirmResetPath)) {
        throw "Fresh requires a missing persona base, or Fresh Reset and the exact printed confirmation path: $personaBase"
    }
    Assert-SafePersonaReset -PersonaBase $personaBase -HomesRoot $homesRoot -TestRoot $testRoot -RepoRoot $repoRoot -Confirmation $ConfirmResetPath
    Remove-Item -LiteralPath $personaBase -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $personaBase, $workspacePath | Out-Null
$runId = [guid]::NewGuid().ToString('N')
$runPath = Join-Path $testRoot "runs/$runId"
New-Item -ItemType Directory -Force -Path $runPath | Out-Null
$gitCommit = (& git -C $repoRoot rev-parse HEAD 2>$null)
$dirtyStatus = [string](& git -C $repoRoot status --porcelain 2>$null)
$dirtyBytes = [System.Text.Encoding]::UTF8.GetBytes($dirtyStatus)
$dirtyStream = [System.IO.MemoryStream]::new($dirtyBytes)
$dirtyFingerprint = Get-FileHash -Algorithm SHA256 -InputStream $dirtyStream
$manifest = [ordered]@{
    schema_version = 1; run_id = $runId; started_at_utc = [DateTime]::UtcNow.ToString('o'); timezone = [TimeZoneInfo]::Local.Id
    persona = $Persona; localappdata = $personaBase; hund_home = $hundHome; workspace = $workspacePath
    fresh = [bool]$Fresh; mode = 'interactive'; live = 'unknown'; provider = 'unknown'; model = 'unknown'; day = $null
    git_commit = [string]$gitCommit; dirty_fingerprint = [string]$dirtyFingerprint.Hash; python_version = (& $repoRoot\.venv\Scripts\python.exe --version 2>&1)
    hund_version = (& $hundExe --version 2>&1); script_hash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
    ended_at_utc = $null; exit_code = $null; completed = $false; exit_reason = 'started'
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runPath 'manifest.json') -Encoding utf8

Write-Host "LOCALAPPDATA: $personaBase"
Write-Host "HundHome: $hundHome"
Write-Host "Workspace: $workspacePath"
Write-Host "Mode: interactive provider/model unknown until Hund starts"
$previousLocalAppData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = $personaBase
    Push-Location -LiteralPath $workspacePath
    & $hundExe @HundArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    $env:LOCALAPPDATA = $previousLocalAppData
}
$manifest.ended_at_utc = [DateTime]::UtcNow.ToString('o')
$manifest.exit_code = $exitCode
$manifest.completed = ($exitCode -eq 0)
$manifest.exit_reason = if ($exitCode -eq 0) { 'completed' } else { 'aborted' }
$tempManifest = Join-Path $runPath 'manifest.tmp.json'
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tempManifest -Encoding utf8
Move-Item -LiteralPath $tempManifest -Destination (Join-Path $runPath 'manifest.json') -Force
exit $exitCode

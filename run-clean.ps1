# run-clean.ps1 — Safe isolated launcher for hund.ai test home
[CmdletBinding()]
param (
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$HundArgs
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts/test-home-boundary.ps1")

# 1. Verify that .venv\Scripts\hund.exe exists
$hundExe = Join-Path $repoRoot ".venv" "Scripts" "hund.exe"
if (-not (Test-Path -Path $hundExe -PathType Leaf)) {
    Write-Error "Cannot start Hund: executable not found at '$hundExe'. Please set up .venv first."
    exit 1
}

# 2. Create isolated timestamped test-home
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$testRoot = Get-TestHomeRoot -RepoRoot $repoRoot
$testHome = Get-ConfinedTestPath -BasePath $testRoot -Segment "hund-$timestamp" -Name "test home"

if (-not (Test-Path -Path $testHome)) {
    New-Item -ItemType Directory -Path $testHome -Force | Out-Null
}

# 3. Configure process-local environment variables
$env:LOCALAPPDATA = $testHome

# 4. Print exact test-home location
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Starting Hund with isolated test home:" -ForegroundColor Cyan
Write-Host " $testHome" -ForegroundColor Yellow
Write-Host " (Existing database and production skills remain untouched)" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

# 5. Start hund.exe with process-local environment
& $hundExe @HundArgs
exit $LASTEXITCODE

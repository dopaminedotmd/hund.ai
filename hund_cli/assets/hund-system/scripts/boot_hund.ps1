Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot

Write-Host '[hund] Boot sequence started.'
& (Join-Path $scriptDir 'init_hund.ps1')
& (Join-Path $scriptDir 'sync_memory.ps1')
& (Join-Path $scriptDir 'validate_hund.ps1')

Write-Host ''
Write-Host '[hund] Boot sequence complete.'
Write-Host '[hund] Load these files into the AI client:'
Write-Host '  hund.md'
Write-Host '  RUNTIME_POLICY.md'
Write-Host '  memory_summary.md'
Write-Host '  SKILL.md'
Write-Host '  rules/PROTECTED_PATHS.md'
Write-Host '  rules/FILE_ROUTING.md'
Write-Host '  skills/SKILL_INDEX.md'

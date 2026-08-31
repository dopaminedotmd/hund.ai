Set-StrictMode -Version Latest

function Get-TestHomeRoot {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot '.test-home'))
}

function Assert-TestSegment {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Name)
    if ($Value -notmatch '^[a-z0-9-]+$' -or $Value.Contains('..') -or $Value.Contains('/') -or $Value.Contains('\')) {
        throw "$Name must match [a-z0-9-]+ and must not contain path traversal."
    }
}

function Get-ConfinedTestPath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$Segment,
        [Parameter(Mandatory = $true)][string]$Name
    )
    Assert-TestSegment -Value $Segment -Name $Name
    $base = [System.IO.Path]::GetFullPath($BasePath).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $base $Segment))
    $prefix = $base + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name resolves outside the approved test boundary."
    }
    return $candidate
}

function Assert-SafePersonaReset {
    param(
        [Parameter(Mandatory = $true)][string]$PersonaBase,
        [Parameter(Mandatory = $true)][string]$HomesRoot,
        [Parameter(Mandatory = $true)][string]$TestRoot,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Confirmation
    )
    if (-not [System.IO.Path]::IsPathRooted($Confirmation) -or $Confirmation.Contains('..')) { throw 'ConfirmResetPath must be a literal rooted path without traversal.' }
    $persona = [System.IO.Path]::GetFullPath($PersonaBase)
    $homes = [System.IO.Path]::GetFullPath($HomesRoot)
    $testRoot = [System.IO.Path]::GetFullPath($TestRoot)
    $repo = [System.IO.Path]::GetFullPath($RepoRoot)
    $confirmed = [System.IO.Path]::GetFullPath($Confirmation)
    if ($confirmed -cne $persona) { throw 'ConfirmResetPath must exactly equal the printed canonical persona base path.' }
    if ($persona -in @($homes, $testRoot, $repo)) { throw 'Refusing to reset a boundary root.' }
    $prefix = $homes.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $persona.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Persona reset target is outside homes root.' }
}

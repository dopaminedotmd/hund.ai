<#
.SYNOPSIS
  Hund CLI installer for Windows (PowerShell 5.1+).
.DESCRIPTION
  Bootstraps uv, clones hund-cli, installs a global `hund` command.
  SECURITY TODO (review): pin to a release commit-SHA + verify a checksum on
  this script before `iex`. Currently fetches latest main — acceptable for
  pre-release dev, not for public stable.
.EXAMPLE
  irm https://raw.githubusercontent.com/dopaminedotmd/hund-cli/main/install.ps1 | iex
#>
$ErrorActionPreference = 'Stop'

$Repo    = 'https://github.com/dopaminedotmd/hund-cli'
$Target  = Join-Path $env:LOCALAPPDATA 'hund-cli'

function Assert-PowerShell {
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        throw "Hund kräver PowerShell 5.1+. Du har $($PSVersionTable.PSVersion)."
    }
    Write-Host "PowerShell $($PSVersionTable.PSVersion) OK"
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "uv finns: $(uv --version)"
        return
    }
    Write-Host "installerar uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    # refresh PATH for this session
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv installerades ej. Starta ny terminal och kör igen."
    }
}

function Get-HundCli {
    if (Test-Path (Join-Path $Target 'pyproject.toml')) {
        Write-Host "uppdaterar $Target ..."
        git -C $Target pull
        return
    }
    Write-Host "klonar till $Target ..."
    git clone $Repo $Target
}

Assert-PowerShell
Ensure-Uv
Get-HundCli

Write-Host "installerar globalt kommando `hund` ..."
uv tool install --force --from $Target hund-cli

if (Get-Command hund -ErrorAction SilentlyContinue) {
    Write-Host "Klar. Testa:"
    Write-Host "  hund --version"
    Write-Host "  setx HUND_API_KEY `"sk-...`"   (ny terminal efteråt)"
    Write-Host "  hund"
} else {
    Write-Warning "`hund` ej i PATH än. Starta ny terminal (PATH uppdateras)."
}

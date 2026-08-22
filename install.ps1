<#
.SYNOPSIS
  Hund CLI installer for Windows (PowerShell 5.1+).

.DESCRIPTION
  Bootstraps uv, clones hund.ai, installs a global `hund` command.

  SECURITY: Detta skript hämtar och exekverar kod från internet.
  För produktionsanvändning, pinna till en release-SHA och verifiera
  SHA256-checksumman för detta skript innan du kör det.

  SHA-PINNING (rekommenderas för stable):
    Sätt $env:HUND_RELEASE_SHA till önskat commit SHA (minst 7 tecken).
    Installeraren checkar ut den pinnade committen istf branch-HEAD.
    Exempel:
      $env:HUND_RELEASE_SHA = "37947cb"
      irm https://raw.githubusercontent.com/.../install.ps1 | iex

  CHECKSUM-VERIFIERING (för CI/release-pipeline):
    Verifiera detta skript mot release-manifestet innan exekvering:
      $manifest = Invoke-RestMethod https://your-release-host/manifest.json
      $actual = (Get-FileHash install.ps1 -Algorithm SHA256).Hash.ToLower()
      if ($actual -ne $manifest.install_ps1_sha256) { throw "SHA256 MISMATCH" }

  DEV-LÄGE: Utan HUND_RELEASE_SHA hämtas latest main — OK för dev, EJ för publik stable.

.EXAMPLE
  # Dev (latest main):
  irm https://raw.githubusercontent.com/dopaminedotmd/hund.ai/main/install.ps1 | iex

  # Stable (pinnad):
  $env:HUND_RELEASE_SHA = "37947cb"; irm .../install.ps1 | iex
#>
$ErrorActionPreference = 'Stop'

$Repo    = 'https://github.com/dopaminedotmd/hund.ai'
$Target  = Join-Path $env:LOCALAPPDATA 'hund.ai'
# Läs optional release-SHA från miljövariabel (sätts av CI eller användare)
$ReleaseSha = $env:HUND_RELEASE_SHA

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
        git -C $Target fetch origin
    } else {
        Write-Host "klonar till $Target ..."
        git clone $Repo $Target
    }

    if ($ReleaseSha) {
        Write-Host "pinnar till release SHA: $ReleaseSha"
        git -C $Target checkout $ReleaseSha
    } else {
        Write-Warning "HUND_RELEASE_SHA ej satt — hämtar latest main (dev-läge, ej för publik stable)"
        git -C $Target pull
    }
}

Assert-PowerShell
Ensure-Uv
Get-HundCli

Write-Host "installerar globalt kommando ``hund`` ..."
uv tool install --force --from $Target hund

if (Get-Command hund -ErrorAction SilentlyContinue) {
    Write-Host "Klar. Testa:"
    Write-Host "  hund --version"
    Write-Host "  setx HUND_API_KEY `"sk-...`"   (ny terminal efteråt)"
    Write-Host "  hund"
} else {
    Write-Warning "``hund`` ej i PATH än. Starta ny terminal (PATH uppdateras)."
}

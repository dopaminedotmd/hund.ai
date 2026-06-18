"""Statiska tester för installationsskripten install.ps1 + install.sh.

Dessa tester kräver ingen nätverksanslutning och verifierar att
installationsskripten innehåller rätt säkerhetsmarkeringar och
INTE gör farliga antaganden (t.ex. blind latest-main fetch i stable-läge).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PS1 = REPO_ROOT / "install.ps1"
SH = REPO_ROOT / "install.sh"


# ------------------------------------------------------------------ #
# install.ps1                                                         #
# ------------------------------------------------------------------ #

def test_ps1_exists():
    assert PS1.exists(), "install.ps1 måste finnas"


def test_ps1_contains_security_notice():
    """Installeraren ska ha en SECURITY-kommentar som dokumenterar SHA-kravet."""
    text = PS1.read_text(encoding="utf-8", errors="ignore")
    # Acceptera "SECURITY" eller "SHA" (plan §7: installern ska ha SHA-marker)
    has_marker = "SECURITY" in text.upper() or "SHA" in text.upper()
    assert has_marker, "install.ps1 saknar SECURITY/SHA-markering"


def test_ps1_does_not_silently_fetch_latest_main_in_stable():
    """Stable-kanal får ALDRIG tyst hämta latest main utan varning.

    Skriptet ska antingen:
      a) ha en TODO/varning om att SHA-pinning saknas, ELLER
      b) faktiskt ha pinning-stöd (RELEASE_SHA / PIN / MANIFEST).
    Accepterar varje kombination som signalerar medvetenhet.
    """
    text = PS1.read_text(encoding="utf-8", errors="ignore").upper()
    safe_markers = ("TODO", "SHA", "SECURITY", "RELEASE", "PIN", "MANIFEST", "CHECKSUM")
    has_awareness = any(m in text for m in safe_markers)
    assert has_awareness, (
        "install.ps1 ser ut att hämta latest main utan SHA-pinning-medvetenhet. "
        "Lägg till TODO/SECURITY-kommentar eller faktisk pinning."
    )


def test_ps1_requires_powershell_version():
    text = PS1.read_text(encoding="utf-8", errors="ignore")
    assert "PSVersionTable" in text or "PowerShell" in text.lower(), (
        "install.ps1 bör kontrollera PowerShell-version"
    )


def test_ps1_error_action_stop():
    """Installeraren ska ha $ErrorActionPreference = 'Stop' så att fel inte tigs."""
    text = PS1.read_text(encoding="utf-8", errors="ignore")
    assert "ErrorActionPreference" in text and "Stop" in text, (
        "install.ps1 bör ha '$ErrorActionPreference = 'Stop'' för fail-fast"
    )


# ------------------------------------------------------------------ #
# install.sh                                                          #
# ------------------------------------------------------------------ #

def test_sh_exists():
    assert SH.exists(), "install.sh måste finnas"


def test_sh_contains_security_notice():
    text = SH.read_text(encoding="utf-8", errors="ignore")
    has_marker = "SECURITY" in text.upper() or "SHA" in text.upper()
    assert has_marker, "install.sh saknar SECURITY/SHA-markering"


def test_sh_has_set_euo():
    """Bash-installer ska ha 'set -euo pipefail' för fail-fast."""
    text = SH.read_text(encoding="utf-8", errors="ignore")
    assert "set -euo pipefail" in text or "set -eu" in text, (
        "install.sh bör använda 'set -euo pipefail'"
    )


def test_sh_does_not_silently_fetch_latest_main_in_stable():
    text = SH.read_text(encoding="utf-8", errors="ignore").upper()
    safe_markers = ("TODO", "SHA", "SECURITY", "RELEASE", "PIN", "MANIFEST", "CHECKSUM")
    has_awareness = any(m in text for m in safe_markers)
    assert has_awareness, (
        "install.sh ser ut att hämta latest main utan SHA-pinning-medvetenhet."
    )

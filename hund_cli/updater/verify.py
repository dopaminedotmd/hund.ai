"""SHA256-verifiering av installationsskript — TCB.

Används av installeraren för att bekräfta att nedladdat skript matchar
det checksumma som manifesten anger.

TCB: Ingen LLM-genererad kod får appliceras här utan mänsklig granskning.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .manifest import ReleaseManifest


class VerificationError(Exception):
    """Höjs när SHA256-kontroll misslyckas."""


def sha256_file(path: Path) -> str:
    """Beräkna SHA256 för en fil. Returnerar hex-sträng (64 tecken)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Beräkna SHA256 för en byte-sträng. Returnerar hex-sträng (64 tecken)."""
    return hashlib.sha256(data).hexdigest()


def verify_installer(
    script_path: Path,
    expected_sha256: str,
    *,
    raise_on_fail: bool = True,
) -> bool:
    """Verifiera att ett installationsskript matchar förväntat SHA256.

    Args:
        script_path: Sökväg till skriptfilen.
        expected_sha256: Förväntat checksumma (64-teckens hex).
        raise_on_fail: Om True höjs VerificationError vid mismatch.

    Returns:
        True om checksumman matchar, annars False (eller undantag).
    """
    if not script_path.exists():
        msg = f"installationsskript hittades ej: {script_path}"
        if raise_on_fail:
            raise VerificationError(msg)
        return False

    actual = sha256_file(script_path)
    if actual != expected_sha256.lower():
        msg = (
            f"SHA256-mismatch för {script_path.name}:\n"
            f"  förväntat: {expected_sha256.lower()}\n"
            f"  faktiskt:  {actual}"
        )
        if raise_on_fail:
            raise VerificationError(msg)
        return False
    return True


def verify_manifest(manifest: ReleaseManifest, repo_root: Path) -> list[str]:
    """Verifiera att manifestets checksummor stämmer mot faktiska filer.

    Returnerar lista med fel (tom = allt OK).
    - För stable-kanal: filerna måste finnas och checksummorna stämma.
    - För dev-kanal: checksummor och filexistens är valfria.
    """
    errors = manifest.validate()
    # Dev-kanal: hoppa över fil- och checksummakontroller
    if manifest.channel != "stable":
        return errors
    for fname, expected in (
        ("install.ps1", manifest.install_ps1_sha256),
        ("install.sh", manifest.install_sh_sha256),
    ):
        p = repo_root / fname
        if not p.exists():
            errors.append(f"{fname} hittades ej under {repo_root}")
            continue
        if expected and len(expected) == 64:
            try:
                verify_installer(p, expected, raise_on_fail=True)
            except VerificationError as e:
                errors.append(str(e))
    return errors

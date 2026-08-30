"""Idempotent Windows desktop shortcut for the Hund Windows Terminal profile.

The model cannot choose a path or name: the shortcut is always
``%Desktop%\\hund.lnk`` targeting ``wt.exe`` with the fixed Hund profile GUID.
Values cross the PowerShell boundary through the process environment, never
via string interpolation into script source, and subprocess runs shell-less.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .font_setup import PROFILE_GUID, installed_icon_path

SHORTCUT_NAME = "hund.lnk"

_CREATE_LNK_SCRIPT = (
    "$WshShell = New-Object -ComObject WScript.Shell\n"
    "$Shortcut = $WshShell.CreateShortcut($env:HUND_LNK_PATH)\n"
    "$Shortcut.TargetPath = $env:HUND_WT_EXE\n"
    "$Shortcut.Arguments = $env:HUND_LNK_ARGS\n"
    "$Shortcut.IconLocation = $env:HUND_ICON_PATH\n"
    "$Shortcut.WorkingDirectory = $env:HUND_WORK_DIR\n"
    "$Shortcut.Save()\n"
)


def _find_wt() -> str:
    """Locate wt.exe (Windows app-execution alias) without a hardcoded path."""
    return shutil.which("wt.exe") or shutil.which("wt") or "wt.exe"


def resolve_desktop(run: Callable = subprocess.run) -> Path:
    """Resolve the real Desktop via the Windows known-folder API."""
    out = run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True, timeout=8,
    )
    if out.returncode != 0 or not (out.stdout or "").strip():
        raise OSError("Could not resolve the Windows Desktop folder.")
    return Path(out.stdout.strip())


def create_desktop_shortcut(
    *,
    desktop: Path | None = None,
    icon: Path | None = None,
    working_dir: Path | None = None,
    run: Callable = subprocess.run,
) -> Path:
    """Create ``%Desktop%\\hund.lnk`` pointing at wt.exe with the Hund profile.

    Idempotent: re-running recreates the identical link. ``desktop``, ``icon``
    and ``working_dir`` are injectable for tests; in production they resolve to
    the real Desktop, the installed icon, and the current directory.
    """
    if os.name != "nt":
        raise OSError("Hund's desktop shortcut is supported on Windows only.")

    target_dir = desktop or resolve_desktop(run)
    link_path = target_dir / SHORTCUT_NAME
    icon_path = icon or installed_icon_path()
    work_dir = working_dir or Path.cwd()

    env = dict(os.environ)
    env["HUND_LNK_PATH"] = str(link_path)
    env["HUND_WT_EXE"] = _find_wt()
    env["HUND_LNK_ARGS"] = f"-p {PROFILE_GUID}"
    env["HUND_ICON_PATH"] = str(icon_path)
    env["HUND_WORK_DIR"] = str(work_dir)

    run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _CREATE_LNK_SCRIPT],
        capture_output=True, text=True, timeout=30, check=True, env=env,
    )
    if not link_path.exists():
        raise OSError("The desktop shortcut was not created.")
    return link_path


def make_desktop_handler():
    """Return a registry handler that creates the shortcut and sanitizes errors."""

    def handler(args: dict) -> str:
        try:
            link = create_desktop_shortcut()
        except (OSError, subprocess.SubprocessError) as exc:
            return f"[error] Could not create the desktop shortcut: {exc}"
        return f"Created {link.name} on the Desktop."

    return handler

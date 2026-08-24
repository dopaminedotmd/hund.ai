"""Optional, reversible DejaVu Nerd Font setup for Windows Terminal."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any


FONT_FAMILY = "DejaVuSansM Nerd Font Mono"
FONT_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "fonts" / "dejavu-nerd-font"
FONT_FILES = (
    "DejaVuSansMNerdFontMono-Regular.ttf",
    "DejaVuSansMNerdFontMono-Bold.ttf",
)
PROFILE_GUID = "{ca840a7c-6cc8-5d4b-a8df-788955160ee9}"


def terminal_fragment_path(local_app_data: Path | None = None) -> Path:
    root = local_app_data or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "Microsoft" / "Windows Terminal" / "Fragments" / "Hund" / "hund.json"


def user_font_dir(local_app_data: Path | None = None) -> Path:
    root = local_app_data or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "Microsoft" / "Windows" / "Fonts"


def ownership_manifest_path(local_app_data: Path | None = None) -> Path:
    root = local_app_data or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "Hund" / "font-setup.json"


def terminal_profile_fragment() -> dict[str, Any]:
    """Return the deterministic Windows Terminal fragment installed by Hund."""
    return {
        "profiles": [
            {
                "guid": PROFILE_GUID,
                "name": "Hund",
                "commandline": "hund",
                "font": {"face": FONT_FAMILY},
            }
        ]
    }


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="hund-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def _same_content(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False

    def digest(path: Path) -> str:
        checksum = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        return checksum.hexdigest()

    return digest(left) == digest(right)


def _read_manifest() -> dict[str, Any]:
    try:
        payload = json.loads(ownership_manifest_path().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _broadcast_font_change() -> None:
    try:
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            0xFFFF, 0x001D, 0, 0, 0x0002, 1000, None
        )
    except Exception:
        pass


def install_terminal_font_profile() -> tuple[Path, ...]:
    """Install bundled fonts per-user and add a separate Hund terminal profile."""
    if sys.platform != "win32":
        raise RuntimeError("Hund's bundled terminal profile is currently supported on Windows only.")
    import winreg

    missing = [name for name in FONT_FILES if not (FONT_ASSET_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError("Bundled font assets are missing: " + ", ".join(missing))

    destination = user_font_dir()
    destination.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    previous = _read_manifest()
    owned_fonts = list(previous.get("owned_fonts", []))
    owned_registry_values = list(previous.get("owned_registry_values", []))
    labels = (f"{FONT_FAMILY} (TrueType)", f"{FONT_FAMILY} Bold (TrueType)")
    key_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, access) as key:
        for filename, label in zip(FONT_FILES, labels):
            target = destination / filename
            source = FONT_ASSET_DIR / filename
            if target.exists():
                if not _same_content(source, target):
                    raise FileExistsError(f"A different font already exists at {target}")
            else:
                shutil.copy2(source, target)
                if filename not in owned_fonts:
                    owned_fonts.append(filename)
            try:
                current, _kind = winreg.QueryValueEx(key, label)
            except FileNotFoundError:
                current = None
            if current is None:
                winreg.SetValueEx(key, label, 0, winreg.REG_SZ, str(target))
                if label not in owned_registry_values:
                    owned_registry_values.append(label)
            installed.append(target)

    fragment = terminal_fragment_path()
    _atomic_json_write(fragment, terminal_profile_fragment())
    _atomic_json_write(
        ownership_manifest_path(),
        {
            "owned_fonts": owned_fonts,
            "owned_registry_values": owned_registry_values,
            "fragment": str(fragment),
        },
    )
    _broadcast_font_change()
    installed.append(fragment)
    return tuple(installed)


def remove_terminal_font_profile() -> tuple[Path, ...]:
    """Remove only the font files, registry values, and fragment owned by Hund."""
    if sys.platform != "win32":
        raise RuntimeError("Hund's bundled terminal profile is currently supported on Windows only.")
    import winreg

    removed: list[Path] = []
    key_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    labels = (f"{FONT_FAMILY} (TrueType)", f"{FONT_FAMILY} Bold (TrueType)")
    manifest_path = ownership_manifest_path()
    manifest = _read_manifest()
    owned_labels = set(manifest.get("owned_registry_values", []))
    owned_fonts = set(manifest.get("owned_fonts", []))

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            for label in labels:
                if label not in owned_labels:
                    continue
                try:
                    winreg.DeleteValue(key, label)
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        pass

    for filename in FONT_FILES:
        if filename not in owned_fonts:
            continue
        target = user_font_dir() / filename
        if target.exists():
            target.unlink()
            removed.append(target)
    fragment = terminal_fragment_path()
    if fragment.exists():
        fragment.unlink()
        removed.append(fragment)
    if manifest_path.exists():
        manifest_path.unlink()
        removed.append(manifest_path)
    _broadcast_font_change()
    return tuple(removed)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hund.font_setup import (
    FONT_ASSET_DIR,
    FONT_FAMILY,
    FONT_FILES,
    bundled_icon_path,
    ensure_installed_icon,
    installed_icon_path,
    ownership_manifest_path,
    terminal_fragment_path,
    terminal_profile_fragment,
    user_font_dir,
)

_ICO_SIZES = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)}


def test_bundled_terminal_fonts_and_notices_exist() -> None:
    assert all((FONT_ASSET_DIR / name).is_file() for name in FONT_FILES)
    assert (FONT_ASSET_DIR / "LICENSE.txt").is_file()
    assert (FONT_ASSET_DIR / "README.md").is_file()


def test_bundled_icon_is_single_frame_sized() -> None:
    Image = pytest.importorskip("PIL.Image")
    ico = bundled_icon_path()
    assert ico.is_file()
    assert set(Image.open(ico).ico.sizes()) == _ICO_SIZES


def test_terminal_profile_uses_lowercase_name_and_installed_icon() -> None:
    fragment = terminal_profile_fragment()
    profile = fragment["profiles"][0]
    assert profile["name"] == "hund"
    assert profile["commandline"] == "hund"
    assert profile["font"]["face"] == FONT_FAMILY
    icon = Path(profile["icon"])
    assert icon.name == "hund.ico"
    assert icon.parent.name == "Hund"
    json.dumps(fragment)


def test_setup_paths_are_scoped_to_local_app_data(tmp_path: Path) -> None:
    assert user_font_dir(tmp_path) == tmp_path / "Microsoft" / "Windows" / "Fonts"
    assert terminal_fragment_path(tmp_path) == (
        tmp_path / "Microsoft" / "Windows Terminal" / "Fragments" / "Hund" / "hund.json"
    )
    assert ownership_manifest_path(tmp_path) == tmp_path / "Hund" / "font-setup.json"
    assert installed_icon_path(tmp_path) == tmp_path / "Hund" / "hund.ico"


def test_ensure_installed_icon_is_idempotent(tmp_path: Path) -> None:
    target = ensure_installed_icon(tmp_path)
    assert target == tmp_path / "Hund" / "hund.ico"
    assert target.is_file()
    # Second run is a no-op.
    assert ensure_installed_icon(tmp_path) == target
    # A stale file is replaced only because the manifest proves Hund owns it.
    target.write_bytes(b"stale")
    assert ensure_installed_icon(tmp_path) == target
    assert target.stat().st_size == bundled_icon_path().stat().st_size


def test_ensure_installed_icon_refuses_foreign_file(tmp_path: Path) -> None:
    target = tmp_path / "Hund" / "hund.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"foreign")
    with pytest.raises(FileExistsError):
        ensure_installed_icon(tmp_path)

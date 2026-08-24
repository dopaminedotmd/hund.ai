from __future__ import annotations

import json
from pathlib import Path

from hund.font_setup import (
    FONT_ASSET_DIR,
    FONT_FAMILY,
    FONT_FILES,
    ownership_manifest_path,
    terminal_fragment_path,
    terminal_profile_fragment,
    user_font_dir,
)


def test_bundled_terminal_fonts_and_notices_exist() -> None:
    assert all((FONT_ASSET_DIR / name).is_file() for name in FONT_FILES)
    assert (FONT_ASSET_DIR / "LICENSE.txt").is_file()
    assert (FONT_ASSET_DIR / "README.md").is_file()


def test_terminal_profile_uses_exact_font_family_and_hund_command() -> None:
    fragment = terminal_profile_fragment()
    profile = fragment["profiles"][0]
    assert profile["name"] == "Hund"
    assert profile["commandline"] == "hund"
    assert profile["font"]["face"] == FONT_FAMILY
    json.dumps(fragment)


def test_setup_paths_are_scoped_to_local_app_data(tmp_path: Path) -> None:
    assert user_font_dir(tmp_path) == tmp_path / "Microsoft" / "Windows" / "Fonts"
    assert terminal_fragment_path(tmp_path) == (
        tmp_path / "Microsoft" / "Windows Terminal" / "Fragments" / "Hund" / "hund.json"
    )
    assert ownership_manifest_path(tmp_path) == tmp_path / "Hund" / "font-setup.json"

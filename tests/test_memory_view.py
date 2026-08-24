"""Unit tests for materialized view rendering and atomic file writing."""
from pathlib import Path

from hund.memory.engine import record_memory
from hund.memory.models import CATEGORY_BIOGRAPHICAL_FACT, CATEGORY_CORE, CATEGORY_STABLE_PREFERENCE
from hund.memory.view import render_user_md, sync_user_md


def test_render_user_md_sections(tmp_path: Path) -> None:
    db_file = tmp_path / "test_view.db"

    record_memory("protect api keys", is_core=True, db_path=db_file)
    record_memory("always write concise code", category=CATEGORY_STABLE_PREFERENCE, db_path=db_file)
    record_memory("works on Windows 11", category=CATEGORY_BIOGRAPHICAL_FACT, db_path=db_file)

    md = render_user_md(db_path=db_file)
    assert "## Core (Immutable)" in md
    assert "- protect api keys" in md
    assert "## Preferences & Habits" in md
    assert "- always write concise code" in md
    assert "## Biographical Facts" in md
    assert "- works on Windows 11" in md


def test_sync_user_md_atomic_write(tmp_path: Path) -> None:
    db_file = tmp_path / "memory" / "memory.db"
    record_memory("atomic test preference", is_core=False, db_path=db_file)

    target_file = sync_user_md(home=tmp_path, db_path=db_file)
    assert target_file.exists()
    assert target_file == tmp_path / "memory" / "user.md"

    content = target_file.read_text(encoding="utf-8")
    assert "- atomic test preference" in content

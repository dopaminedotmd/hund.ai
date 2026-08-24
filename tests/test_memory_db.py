"""Unit tests for memory.db SQLite storage and audit trail."""
from pathlib import Path

from hund.memory.db import connect_memory
from hund.memory.engine import get_audit_history, get_memory, record_memory
from hund.memory.models import ACTION_CREATE, CATEGORY_STABLE_PREFERENCE, SCOPE_USER_GLOBAL


def test_memory_db_table_initialization(tmp_path: Path) -> None:
    db_file = tmp_path / "test_memory.db"
    conn = connect_memory(db_file)

    # Check tables exist
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "memory" in tables
    assert "memory_audit" in tables

    # Check indices exist
    indices = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_memory_scope" in indices
    assert "idx_memory_status" in indices
    assert "idx_memory_is_core" in indices
    assert "idx_memory_audit_memory" in indices

    conn.close()


def test_record_and_get_memory(tmp_path: Path) -> None:
    db_file = tmp_path / "test_memory.db"

    item = record_memory(
        statement="prefers dark mode",
        scope=SCOPE_USER_GLOBAL,
        category=CATEGORY_STABLE_PREFERENCE,
        source_type="user",
        db_path=db_file,
    )

    assert item.statement == "prefers dark mode"
    assert item.status == "verified"
    assert item.confidence == 1.0

    fetched = get_memory(item.memory_id, db_path=db_file)
    assert fetched is not None
    assert fetched.memory_id == item.memory_id
    assert fetched.statement == "prefers dark mode"

    # Verify audit log was created
    audits = get_audit_history(item.memory_id, db_path=db_file)
    assert len(audits) == 1
    assert audits[0].action == ACTION_CREATE
    assert audits[0].memory_id == item.memory_id

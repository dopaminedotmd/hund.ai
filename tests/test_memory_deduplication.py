"""Regression tests for bounded, idempotent memory storage."""
from datetime import datetime, timezone
import sqlite3

from hund.memory.db import MEMORY_SCHEMA, connect_memory
from hund.memory.engine import list_active_memories, record_memory


def test_legacy_duplicates_are_merged_and_audit_repointed(tmp_path):
    db = tmp_path / "memory.db"
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db) as conn:
        conn.executescript(MEMORY_SCHEMA)
        row = (
            "user_global", "stable_preference", "Prefers concise code",
            "verified", 1.0, "user", now, now, 1, 0, "[]",
            None, None, None, 0,
        )
        conn.execute(
            """INSERT INTO memory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("m1", *row),
        )
        conn.execute(
            """INSERT INTO memory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("m2", *row),
        )
        conn.execute(
            "INSERT INTO memory_audit VALUES ('a2','m2','create','','','','',?)",
            (now,),
        )
    migrated = connect_memory(db)
    assert migrated.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1
    keeper = migrated.execute("SELECT memory_id FROM memory").fetchone()[0]
    assert migrated.execute(
        "SELECT memory_id FROM memory_audit WHERE audit_id='a2'"
    ).fetchone()[0] == keeper
    migrated.close()


def test_record_memory_reinforces_instead_of_inserting_duplicate(tmp_path):
    db = tmp_path / "memory.db"
    first = record_memory("Prefers concise code", db_path=db)
    second = record_memory("  prefers concise code  ", db_path=db)
    assert second.memory_id == first.memory_id
    assert second.support_count == 2
    with connect_memory(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1


def test_active_memory_listing_is_bounded(tmp_path):
    db = tmp_path / "memory.db"
    for index in range(120):
        record_memory(f"preference {index}", db_path=db)
    assert len(list_active_memories(db_path=db)) == 100

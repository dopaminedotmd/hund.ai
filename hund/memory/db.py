"""SQLite connection and schema management for canonical memory.db."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    memory_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL DEFAULT 0.0,
    source_type TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    support_count INTEGER DEFAULT 1,
    contradiction_count INTEGER DEFAULT 0,
    evidence_ids TEXT DEFAULT '[]',
    supersedes TEXT,
    superseded_by TEXT,
    expires_at TEXT,
    is_core INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory(scope);
CREATE INDEX IF NOT EXISTS idx_memory_status ON memory(status);
CREATE INDEX IF NOT EXISTS idx_memory_is_core ON memory(is_core);

CREATE TABLE IF NOT EXISTS memory_audit (
    audit_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT DEFAULT '',
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    evidence_id TEXT DEFAULT '',
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_audit_memory ON memory_audit(memory_id);
"""


def connect_memory(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open or create connection to canonical memory.db with WAL mode and schema initialized."""
    if db_path is not None:
        p = Path(db_path)
    else:
        from ..paths import memory_db_path

        p = memory_db_path()

    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(MEMORY_SCHEMA)
    _migrate_memory(conn)
    return conn


def _migrate_memory(conn: sqlite3.Connection) -> None:
    """Deduplicate legacy active rows once, then enforce idempotent writes."""
    indexes = {
        row[1] for row in conn.execute("PRAGMA index_list(memory)").fetchall()
    }
    if "ux_memory_active_statement" in indexes:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP TABLE IF EXISTS temp._memory_ranked")
        conn.execute(
            """CREATE TEMP TABLE _memory_ranked AS
               SELECT
                   memory_id,
                   FIRST_VALUE(memory_id) OVER (
                       PARTITION BY scope, category, lower(trim(statement))
                       ORDER BY
                           CASE status WHEN 'verified' THEN 0 ELSE 1 END,
                           is_core DESC, confidence DESC, last_seen DESC, rowid ASC
                   ) AS keep_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY scope, category, lower(trim(statement))
                       ORDER BY
                           CASE status WHEN 'verified' THEN 0 ELSE 1 END,
                           is_core DESC, confidence DESC, last_seen DESC, rowid ASC
                   ) AS duplicate_rank
               FROM memory
               WHERE status IN ('verified', 'draft') AND superseded_by IS NULL"""
        )
        conn.execute(
            "CREATE INDEX temp.idx_memory_ranked_id ON _memory_ranked(memory_id)"
        )
        conn.execute(
            "CREATE INDEX temp.idx_memory_ranked_keep ON _memory_ranked(keep_id)"
        )
        conn.execute(
            """UPDATE memory
               SET first_seen = (
                       SELECT MIN(m.first_seen)
                       FROM memory m JOIN _memory_ranked r ON r.memory_id=m.memory_id
                       WHERE r.keep_id=memory.memory_id
                   ),
                   last_seen = (
                       SELECT MAX(m.last_seen)
                       FROM memory m JOIN _memory_ranked r ON r.memory_id=m.memory_id
                       WHERE r.keep_id=memory.memory_id
                   ),
                   confidence = (
                       SELECT MAX(m.confidence)
                       FROM memory m JOIN _memory_ranked r ON r.memory_id=m.memory_id
                       WHERE r.keep_id=memory.memory_id
                   ),
                   support_count = (
                       SELECT MAX(m.support_count)
                       FROM memory m JOIN _memory_ranked r ON r.memory_id=m.memory_id
                       WHERE r.keep_id=memory.memory_id
                   )
               WHERE memory_id IN (SELECT keep_id FROM _memory_ranked)"""
        )
        conn.execute(
            """UPDATE memory_audit
               SET memory_id = (
                   SELECT keep_id FROM _memory_ranked
                   WHERE _memory_ranked.memory_id=memory_audit.memory_id
               )
               WHERE memory_id IN (
                   SELECT memory_id FROM _memory_ranked WHERE duplicate_rank > 1
               )"""
        )
        conn.execute(
            """DELETE FROM memory
               WHERE memory_id IN (
                   SELECT memory_id FROM _memory_ranked WHERE duplicate_rank > 1
               )"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX ux_memory_active_statement
               ON memory(scope, category, lower(trim(statement)))
               WHERE status IN ('verified', 'draft') AND superseded_by IS NULL"""
        )
        conn.execute("DROP TABLE temp._memory_ranked")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

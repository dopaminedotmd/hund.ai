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
    return conn

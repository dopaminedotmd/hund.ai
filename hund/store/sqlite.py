"""SQLite stores — core + separerade prestanda-DBs.

Tre anslutningar (fas 9.5 Del D bröt ut requests/tool_events ur monoliten):
  - connect()              → hund.db        (core: gap_events, proposals, domains)
  - connect_requests()     → logs/requests.db
  - connect_tool_events()  → logs/tool_events.db

Schemas initieras idempotente. knowledge_units flyttades till JSON i Del C
(brain/knowledge/*.json); gamla SQLite-rader migreras via `hund migrate`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Core-DB: det som inte är rå prestandadata.
SCHEMA = """
CREATE TABLE IF NOT EXISTS gap_events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    domain TEXT,
    symptom TEXT,                 -- LOKALT ENDAST. Aldrig extern upload i v1.
    study_target TEXT,
    status TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    title TEXT,
    problem TEXT,
    proposed_change TEXT,
    change_type TEXT,            -- runtime_policy|skill|hundk|prompt|test
    risk TEXT,
    tests_needed TEXT,
    related_gaps TEXT,           -- JSON-lista av gap-id
    status TEXT DEFAULT 'proposed',  -- proposed|approved|rejected|applied
    verification_required INTEGER DEFAULT 1,  -- Fas 8: alltid 1 (True)
    rollback_note TEXT DEFAULT '',            -- Fas 8: rollback-instruktion
    raw_summary TEXT DEFAULT ''               -- Fas 9.6: LLM:ens fulla JSON (redakterad)
);

CREATE TABLE IF NOT EXISTS domains (
    domain TEXT PRIMARY KEY,
    status TEXT DEFAULT 'candidate',  -- candidate|active|primary|stale
    confidence TEXT,                   -- low|medium|high
    detected_at TEXT
);
"""

REQUESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    task_class TEXT,
    model_requested TEXT,
    model_actual TEXT,
    provider TEXT,
    finish_reason TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0
);
"""

TOOL_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    tool TEXT,
    risk TEXT,
    outcome TEXT,                -- ran|approved|declined|blocked|error
    success INTEGER DEFAULT 0    -- 1 om tool körde utan fel
);
"""


def _open(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(schema)
    return conn


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Core-DB: gap_events, proposals, domains."""
    from ..paths import db_path as default_db_path

    path = db_path or default_db_path()
    conn = _open(path, SCHEMA)
    _migrate(conn)
    return conn


def connect_requests(db_path: Path | None = None) -> sqlite3.Connection:
    """logs/requests.db — token/latency per LLM-request."""
    from ..paths import requests_db_path as default_path

    return _open(db_path or default_path(), REQUESTS_SCHEMA)


def connect_tool_events(db_path: Path | None = None) -> sqlite3.Connection:
    """logs/tool_events.db — verktygsanrop, risk, outcome."""
    from ..paths import tool_events_db_path as default_path

    return _open(db_path or default_path(), TOOL_EVENTS_SCHEMA)


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent schema migrations för befintliga core-databaser.

    Fas 8: lägg till verification_required + rollback_note till proposals
    om de saknas (äldre DB som skapades innan fas 8).
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(proposals)")
    }
    if "verification_required" not in existing:
        conn.execute(
            "ALTER TABLE proposals ADD COLUMN verification_required INTEGER DEFAULT 1"
        )
    if "rollback_note" not in existing:
        conn.execute(
            "ALTER TABLE proposals ADD COLUMN rollback_note TEXT DEFAULT ''"
        )
    # Fas 9.6: raw_summary — LLM:ens fulla JSON-svar (för apply --apply).
    if "raw_summary" not in existing:
        conn.execute(
            "ALTER TABLE proposals ADD COLUMN raw_summary TEXT DEFAULT ''"
        )
    conn.commit()

"""SQLite store — sessions, request-stats, gap events.

En databas (hund.db) istället för många .jsonl. Ger aggregering + `hund stats`
gratis. Schemas initieras idempotente. Stub i 0.1.0; fullständigt i fas 1.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
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
    status TEXT DEFAULT 'proposed'  -- proposed|approved|rejected|applied
);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    domain TEXT,
    trigger TEXT,                -- nyckelord som aktiverar unit
    rule TEXT,                   -- själva regeln/lärdomen
    frequency INTEGER DEFAULT 0, -- LFU: hur ofta använt
    last_used TEXT,              -- MRU: senast använt
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    source TEXT                  -- manual|study|gap
);

CREATE TABLE IF NOT EXISTS tool_events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    tool TEXT,
    risk TEXT,
    outcome TEXT,                -- ran|approved|declined|blocked|error
    success INTEGER DEFAULT 0    -- 1 om tool körde utan fel
);

CREATE TABLE IF NOT EXISTS domains (
    domain TEXT PRIMARY KEY,
    status TEXT DEFAULT 'candidate',  -- candidate|active|primary|stale
    confidence TEXT,                   -- low|medium|high
    detected_at TEXT
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    from ..paths import db_path as default_db_path

    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn

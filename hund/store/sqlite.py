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

CREATE TABLE IF NOT EXISTS trace_events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    org_id TEXT,
    workspace_id TEXT,
    connector_id TEXT,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    turn_id TEXT,
    parent_run_id TEXT,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    risk TEXT,
    policy_version TEXT,
    tool_name TEXT,
    approval_id TEXT,
    payload_redacted TEXT,         -- JSON string
    payload_hash TEXT NOT NULL,
    payload_hash_algorithm TEXT NOT NULL,
    redactor_version TEXT NOT NULL,
    redaction TEXT                  -- JSON string
);

CREATE INDEX IF NOT EXISTS idx_trace_events_session ON trace_events(session_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_run ON trace_events(run_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events(event_type);

CREATE TABLE IF NOT EXISTS export_log (
    export_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    export_format TEXT NOT NULL,
    pair_count INTEGER DEFAULT 0,
    output_path TEXT,
    filters_json TEXT,
    redactor_version TEXT
);

CREATE TABLE IF NOT EXISTS forge_artifacts (
    artifact_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    change_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    risk TEXT NOT NULL,
    source TEXT DEFAULT 'real',
    state TEXT NOT NULL,
    payload_redacted TEXT NOT NULL,
    apply_policy TEXT NOT NULL,
    forge_verdict TEXT,
    composite_score INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forge_artifacts_tenant ON forge_artifacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_forge_artifacts_state ON forge_artifacts(state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_forge_artifacts_proposal_tenant
    ON forge_artifacts(proposal_id, tenant_id);

CREATE TABLE IF NOT EXISTS forge_evaluations (
    idempotency_key TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    request_redacted TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_states (
    scope TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    onboarding_complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_task_events (
    scope TEXT NOT NULL,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (scope, task_id)
);

CREATE TABLE IF NOT EXISTS lifecycle_sessions (
    scope TEXT NOT NULL,
    session_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (scope, session_id)
);

CREATE TABLE IF NOT EXISTS lifecycle_audit (
    audit_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    action TEXT NOT NULL,
    old_phase TEXT,
    new_phase TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_tasks_scope
ON lifecycle_task_events(scope);
CREATE INDEX IF NOT EXISTS idx_lifecycle_sessions_scope
ON lifecycle_sessions(scope);
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
    latency_ms INTEGER DEFAULT 0,
    run_id TEXT,
    reasoning_content TEXT
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
    _migrate_trace_events(conn)
    return conn


def connect_requests(db_path: Path | None = None) -> sqlite3.Connection:
    """logs/requests.db — token/latency per LLM-request."""
    from ..paths import requests_db_path as default_path

    conn = _open(db_path or default_path(), REQUESTS_SCHEMA)
    _migrate_requests(conn)
    return conn


def _migrate_trace_events(conn: sqlite3.Connection) -> None:
    """Idempotent migrations for trace_events.

    Phase 1 is new, but local developer DBs may already contain an older draft
    table. Keep it self-healing so trace rollout does not require DB deletion.
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(trace_events)")
    }
    if not existing:
        return
    required = {
        "org_id": "TEXT",
        "connector_id": "TEXT",
        "turn_id": "TEXT",
        "parent_run_id": "TEXT",
        "approval_id": "TEXT",
        "payload_hash_algorithm": "TEXT DEFAULT 'sha256'",
        "redactor_version": "TEXT DEFAULT '1.0.0'",
        "redaction": "TEXT DEFAULT '{\"applied\":false,\"fields\":[],\"risk_level\":\"safe\"}'",
    }
    for column, ddl in required.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE trace_events ADD COLUMN {column} {ddl}")
    conn.commit()

def _migrate_requests(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(requests)")
    }
    if "run_id" not in existing:
        conn.execute("ALTER TABLE requests ADD COLUMN run_id TEXT")
        conn.commit()
    if "reasoning_content" not in existing:
        conn.execute("ALTER TABLE requests ADD COLUMN reasoning_content TEXT")
        conn.commit()


def log_request_reasoning(
    reasoning: str,
    *,
    run_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Log reasoning_content separately to logs/requests.db."""
    if not reasoning:
        return
    try:
        conn = connect_requests(db_path)
        if run_id:
            conn.execute(
                "UPDATE requests SET reasoning_content = ? WHERE run_id = ? AND (reasoning_content IS NULL OR reasoning_content = '')",
                (reasoning, run_id),
            )
        else:
            row = conn.execute("SELECT id FROM requests ORDER BY created_at DESC LIMIT 1").fetchone()
            if row:
                conn.execute(
                    "UPDATE requests SET reasoning_content = ? WHERE id = ?",
                    (reasoning, row[0]),
                )
            else:
                import uuid
                from datetime import datetime, timezone
                conn.execute(
                    "INSERT INTO requests (id, created_at, task_class, reasoning_content) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(), "reasoning", reasoning),
                )
        conn.commit()
        conn.close()
    except Exception:
        pass


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

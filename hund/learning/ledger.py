"""Append-only evidence ledger and durable learning jobs queue.

Invariants:
- `evidence_ledger` is strictly append-only. No UPDATE or DELETE operations exist.
- `learning_jobs` is a durable, idempotent queue designed to survive process restarts/Ctrl+C.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from ..store.sqlite import connect

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_ledger (
    event_id TEXT PRIMARY KEY,
    session_id TEXT,
    turn_id INTEGER,
    timestamp TEXT,
    event_type TEXT,
    source_type TEXT,
    source_ref TEXT,
    workspace_id TEXT,
    candidate_domains TEXT,
    content_hash TEXT,
    payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_evidence_ledger_session ON evidence_ledger(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_ledger_ts ON evidence_ledger(timestamp);

CREATE TABLE IF NOT EXISTS learning_jobs (
    job_id TEXT PRIMARY KEY,
    event_ids TEXT,
    status TEXT,
    attempt_count INTEGER DEFAULT 0,
    created_at TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    last_error TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_learning_jobs_status ON learning_jobs(status);
"""


def _ensure_tables(db_path: Path | str | None = None) -> None:
    """Ensure evidence_ledger and learning_jobs tables exist."""
    conn = connect(Path(db_path) if db_path else None)
    conn.executescript(LEDGER_SCHEMA)
    # Check if last_error column exists in learning_jobs (self-healing migration)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(learning_jobs)")}
    if "last_error" not in existing:
        conn.execute("ALTER TABLE learning_jobs ADD COLUMN last_error TEXT DEFAULT ''")
    conn.commit()
    conn.close()


def append_event(
    session_id: str = "",
    turn_id: int | None = None,
    event_type: str = "",
    source_type: str = "",
    source_ref: str = "",
    workspace_id: str = "",
    candidate_domains: list[str] | None = None,
    payload: str = "",
    db_path: Path | str | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Append an event to the evidence ledger.

    Returns the unique event_id.
    """
    _ensure_tables(db_path)
    ev_id = event_id or uuid.uuid4().hex
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    domains_json = json.dumps(candidate_domains or [])
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    conn = connect(Path(db_path) if db_path else None)
    conn.execute(
        """INSERT INTO evidence_ledger (
            event_id, session_id, turn_id, timestamp, event_type,
            source_type, source_ref, workspace_id, candidate_domains,
            content_hash, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ev_id,
            session_id,
            turn_id,
            ts,
            event_type,
            source_type,
            source_ref,
            workspace_id,
            domains_json,
            content_hash,
            payload,
        ),
    )
    conn.commit()
    conn.close()
    return ev_id


def get_event(event_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Retrieve an evidence ledger event by ID."""
    _ensure_tables(db_path)
    conn = connect(Path(db_path) if db_path else None)
    row = conn.execute(
        """SELECT event_id, session_id, turn_id, timestamp, event_type,
                  source_type, source_ref, workspace_id, candidate_domains,
                  content_hash, payload
           FROM evidence_ledger WHERE event_id = ?""",
        (event_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    try:
        domains = json.loads(row[8]) if row[8] else []
    except Exception:
        domains = []

    return {
        "event_id": row[0],
        "session_id": row[1],
        "turn_id": row[2],
        "timestamp": row[3],
        "event_type": row[4],
        "source_type": row[5],
        "source_ref": row[6],
        "workspace_id": row[7],
        "candidate_domains": domains,
        "content_hash": row[9],
        "payload": row[10],
    }


def list_events(
    limit: int = 50,
    before_event_id: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """List events ordered backwards in time (newest first).

    Supports pagination using before_event_id.
    """
    _ensure_tables(db_path)
    conn = connect(Path(db_path) if db_path else None)

    conditions = []
    params: list[Any] = []

    if before_event_id:
        target = conn.execute(
            "SELECT timestamp, rowid FROM evidence_ledger WHERE event_id = ?",
            (before_event_id,),
        ).fetchone()
        if target:
            target_ts, target_rowid = target
            conditions.append("(timestamp < ? OR (timestamp = ? AND rowid < ?))")
            params.extend([target_ts, target_ts, target_rowid])
        else:
            # If before_event_id is invalid, return empty list
            conn.close()
            return []

    if session_id is not None:
        conditions.append("session_id = ?")
        params.append(session_id)

    if workspace_id is not None:
        conditions.append("workspace_id = ?")
        params.append(workspace_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT event_id, session_id, turn_id, timestamp, event_type,
               source_type, source_ref, workspace_id, candidate_domains,
               content_hash, payload
        FROM evidence_ledger
        {where_clause}
        ORDER BY timestamp DESC, rowid DESC
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        try:
            domains = json.loads(row[8]) if row[8] else []
        except Exception:
            domains = []
        results.append(
            {
                "event_id": row[0],
                "session_id": row[1],
                "turn_id": row[2],
                "timestamp": row[3],
                "event_type": row[4],
                "source_type": row[5],
                "source_ref": row[6],
                "workspace_id": row[7],
                "candidate_domains": domains,
                "content_hash": row[9],
                "payload": row[10],
            }
        )
    return results


# Durable learning jobs queue operations


def enqueue_job(
    event_ids: list[str],
    db_path: Path | str | None = None,
    job_id: str | None = None,
) -> str:
    """Enqueue a new learning job with status='pending'.

    Idempotent: if job_id already exists, returns existing job_id.
    """
    _ensure_tables(db_path)
    jid = job_id or uuid.uuid4().hex
    events_json = json.dumps(event_ids)
    now = datetime.now(timezone.utc).isoformat()

    conn = connect(Path(db_path) if db_path else None)
    conn.execute(
        """INSERT OR IGNORE INTO learning_jobs (
            job_id, event_ids, status, attempt_count, created_at, claimed_at, completed_at, last_error
        ) VALUES (?, ?, 'pending', 0, ?, NULL, NULL, '')""",
        (jid, events_json, now),
    )
    conn.commit()
    conn.close()
    return jid


def claim_next_job(db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Atomically claim the next pending learning job.

    Transitions status from 'pending' to 'running'.
    Returns the job dict or None if no pending jobs are available.
    """
    _ensure_tables(db_path)
    conn = connect(Path(db_path) if db_path else None)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        """SELECT job_id, event_ids, status, attempt_count, created_at, claimed_at, completed_at, last_error
           FROM learning_jobs
           WHERE status = 'pending'
           ORDER BY created_at ASC, rowid ASC
           LIMIT 1"""
    ).fetchone()

    if row is None:
        conn.commit()
        conn.close()
        return None

    job_id = row[0]
    conn.execute(
        "UPDATE learning_jobs SET status = 'running', claimed_at = ? WHERE job_id = ? AND status = 'pending'",
        (now, job_id),
    )
    conn.commit()
    conn.close()

    try:
        ev_ids = json.loads(row[1]) if row[1] else []
    except Exception:
        ev_ids = []

    return {
        "job_id": job_id,
        "event_ids": ev_ids,
        "status": "running",
        "attempt_count": row[3],
        "created_at": row[4],
        "claimed_at": now,
        "completed_at": row[6],
        "last_error": row[7] or "",
    }


def complete_job(job_id: str, db_path: Path | str | None = None) -> bool:
    """Mark a learning job as completed.

    Idempotent: returns True if updated or already completed.
    """
    _ensure_tables(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect(Path(db_path) if db_path else None)
    cur = conn.execute(
        "UPDATE learning_jobs SET status = 'completed', completed_at = ? WHERE job_id = ?",
        (now, job_id),
    )
    conn.commit()
    rows_affected = cur.rowcount
    conn.close()
    return rows_affected > 0


def fail_job(
    job_id: str,
    error: str = "",
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Mark a learning job as failed.

    Increments attempt_count. If attempt_count < 3, resets status to 'pending'.
    If attempt_count >= 3, transitions status to 'dead'.
    Stores error reason in last_error.
    """
    _ensure_tables(db_path)
    conn = connect(Path(db_path) if db_path else None)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        """SELECT job_id, event_ids, status, attempt_count, created_at, claimed_at, completed_at, last_error
           FROM learning_jobs WHERE job_id = ?""",
        (job_id,),
    ).fetchone()

    if row is None:
        conn.commit()
        conn.close()
        return None

    new_attempt_count = (row[3] or 0) + 1
    if new_attempt_count < 3:
        new_status = "pending"
        new_claimed = None
        new_completed = None
    else:
        new_status = "dead"
        new_claimed = row[5]
        new_completed = now

    conn.execute(
        """UPDATE learning_jobs
           SET status = ?, attempt_count = ?, claimed_at = ?, completed_at = ?, last_error = ?
           WHERE job_id = ?""",
        (new_status, new_attempt_count, new_claimed, new_completed, error, job_id),
    )
    conn.commit()
    conn.close()

    try:
        ev_ids = json.loads(row[1]) if row[1] else []
    except Exception:
        ev_ids = []

    return {
        "job_id": job_id,
        "event_ids": ev_ids,
        "status": new_status,
        "attempt_count": new_attempt_count,
        "created_at": row[4],
        "claimed_at": new_claimed,
        "completed_at": new_completed,
        "last_error": error,
    }


def get_job(job_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Retrieve learning job by ID."""
    _ensure_tables(db_path)
    conn = connect(Path(db_path) if db_path else None)
    row = conn.execute(
        """SELECT job_id, event_ids, status, attempt_count, created_at, claimed_at, completed_at, last_error
           FROM learning_jobs WHERE job_id = ?""",
        (job_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    try:
        ev_ids = json.loads(row[1]) if row[1] else []
    except Exception:
        ev_ids = []

    return {
        "job_id": row[0],
        "event_ids": ev_ids,
        "status": row[2],
        "attempt_count": row[3],
        "created_at": row[4],
        "claimed_at": row[5],
        "completed_at": row[6],
        "last_error": row[7] or "",
    }

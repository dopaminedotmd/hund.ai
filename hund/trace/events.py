"""Trace event model and persistence.

Trace events are the canonical audit substrate for runs, tools, approvals,
verification, safety decisions, dashboard views, and future dataset export.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..learning.redactor import redact_text
from ..store.sqlite import connect

SCHEMA_VERSION = 1
PAYLOAD_HASH_ALGORITHM = "sha256"
REDACTOR_VERSION = "1.0.0"

EVENT_TYPES = {
    "run_started",
    "run_completed",
    "turn_started",
    "turn_completed",
    "plan_snapshot",
    "tool_call_requested",
    "tool_call_classified",
    "tool_call_approved",
    "tool_call_declined",
    "tool_call_blocked",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
    "verification_intent",
    "verification_started",
    "verification_completed",
    "final_claim",
    "redaction_applied",
    "injection_suspected",
    "injection_blocked",
    "context_compressed",
    "proposal_created",
    "proposal_approved",
    "proposal_rejected",
    "eval_started",
    "eval_completed",
    "approval_requested",
    "approval_resolved",
    "worktree_session_started",
    "worktree_session_completed",
    "worktree_proposed",
    "worktree_merged",
    "export_completed",
    "local_fallback",
    "cloud_registered",
    "cloud_heartbeat",
    "cloud_deployed",
}

ACTORS = {"user", "hund", "agent", "subagent", "connector", "system", "evaluator", "worktree_agent"}
RISKS = {"safe", "write", "confirm", "dangerous", "blocked", "none"}


class TraceEvent(BaseModel):
    schema_version: int = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    org_id: str | None = None
    workspace_id: str
    connector_id: str | None = None
    session_id: str
    run_id: str
    turn_id: str | None = None
    parent_run_id: str | None = None
    actor: str
    event_type: str
    risk: str = "none"
    policy_version: str
    tool_name: str | None = None
    approval_id: str | None = None
    payload_redacted: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    payload_hash_algorithm: str = PAYLOAD_HASH_ALGORITHM
    redactor_version: str = REDACTOR_VERSION
    redaction: dict[str, Any] = Field(
        default_factory=lambda: {"applied": False, "fields": [], "risk_level": "safe"}
    )


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def create_event(
    workspace_id: str,
    session_id: str,
    run_id: str,
    actor: str,
    event_type: str,
    policy_version: str,
    payload_unredacted: dict[str, Any] | None = None,
    org_id: str | None = None,
    connector_id: str | None = None,
    turn_id: str | None = None,
    parent_run_id: str | None = None,
    risk: str = "none",
    tool_name: str | None = None,
    approval_id: str | None = None,
) -> TraceEvent:
    """Create a trace event and redact its payload before persistence."""
    if actor not in ACTORS:
        raise ValueError(f"invalid trace actor: {actor}")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"invalid trace event_type: {event_type}")
    if risk not in RISKS:
        raise ValueError(f"invalid trace risk: {risk}")

    payload_json = _canonical_json(payload_unredacted or {})
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    redact_res = redact_text(payload_json)
    try:
        payload_redacted = json.loads(redact_res.text)
    except json.JSONDecodeError:
        payload_redacted = {"_redacted_text": redact_res.text}

    return TraceEvent(
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        actor=actor,
        event_type=event_type,
        policy_version=policy_version,
        payload_redacted=payload_redacted,
        payload_hash=payload_hash,
        org_id=org_id,
        connector_id=connector_id,
        turn_id=turn_id,
        parent_run_id=parent_run_id,
        risk=risk,
        tool_name=tool_name,
        approval_id=approval_id,
        redaction={
            "applied": bool(redact_res.blocked_fields),
            "fields": redact_res.blocked_fields,
            "risk_level": redact_res.risk_level,
        },
    )


def write_event(event: TraceEvent, db_path: Path | None = None) -> None:
    """Persist a trace event into the core trace_events table."""
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO trace_events (
            event_id, schema_version, created_at, org_id, workspace_id, connector_id,
            session_id, run_id, turn_id, parent_run_id, actor, event_type, risk,
            policy_version, tool_name, approval_id, payload_redacted, payload_hash,
            payload_hash_algorithm, redactor_version, redaction
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.schema_version,
            event.created_at,
            event.org_id,
            event.workspace_id,
            event.connector_id,
            event.session_id,
            event.run_id,
            event.turn_id,
            event.parent_run_id,
            event.actor,
            event.event_type,
            event.risk,
            event.policy_version,
            event.tool_name,
            event.approval_id,
            json.dumps(event.payload_redacted, ensure_ascii=False, sort_keys=True),
            event.payload_hash,
            event.payload_hash_algorithm,
            event.redactor_version,
            json.dumps(event.redaction, ensure_ascii=False, sort_keys=True),
        ),
    )
    conn.commit()
    conn.close()


def record_event(db_path: Path | None = None, **kwargs) -> TraceEvent:
    """Create and persist a trace event in one call."""
    event = create_event(**kwargs)
    write_event(event, db_path=db_path)
    return event


def _row_to_event(row: tuple) -> TraceEvent:
    return TraceEvent(
        event_id=row[0],
        schema_version=row[1],
        created_at=row[2],
        org_id=row[3],
        workspace_id=row[4],
        connector_id=row[5],
        session_id=row[6],
        run_id=row[7],
        turn_id=row[8],
        parent_run_id=row[9],
        actor=row[10],
        event_type=row[11],
        risk=row[12] or "none",
        policy_version=row[13],
        tool_name=row[14],
        approval_id=row[15],
        payload_redacted=json.loads(row[16]) if row[16] else {},
        payload_hash=row[17],
        payload_hash_algorithm=row[18],
        redactor_version=row[19],
        redaction=json.loads(row[20]) if row[20] else {},
    )


def list_events_by_run(run_id: str, db_path: Path | None = None) -> list[TraceEvent]:
    """Return all events for a run sorted chronologically."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT * FROM trace_events WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,),
    ).fetchall()
    conn.close()
    return [_row_to_event(row) for row in rows]


def list_events_by_session(session_id: str, db_path: Path | None = None) -> list[TraceEvent]:
    """Return all events for a session sorted chronologically."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT * FROM trace_events WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [_row_to_event(row) for row in rows]


def list_events_by_type(event_type: str, db_path: Path | None = None) -> list[TraceEvent]:
    """Return all events of a given type sorted chronologically."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT * FROM trace_events WHERE event_type = ? ORDER BY created_at ASC",
        (event_type,),
    ).fetchall()
    conn.close()
    return [_row_to_event(row) for row in rows]

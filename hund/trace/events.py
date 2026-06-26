"""Trace Event Model and Persistence — Hund.ai spårningsinfrastruktur (TCB)."""
from __future__ import annotations

import json
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..store.sqlite import connect
from ..learning.redactor import redact_text


class TraceEvent(BaseModel):
    schema_version: int = 1
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    org_id: Optional[str] = None
    workspace_id: str
    connector_id: Optional[str] = None
    session_id: str
    run_id: str
    turn_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    actor: str
    event_type: str
    risk: Optional[str] = "none"
    policy_version: str
    tool_name: Optional[str] = None
    approval_id: Optional[str] = None
    payload_redacted: Dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    payload_hash_algorithm: str = "sha256"
    redactor_version: str = "1.0.0"
    redaction: Dict[str, Any] = Field(
        default_factory=lambda: {"applied": False, "fields": [], "risk_level": "safe"}
    )


def create_event(
    workspace_id: str,
    session_id: str,
    run_id: str,
    actor: str,
    event_type: str,
    policy_version: str,
    payload_unredacted: Dict[str, Any],
    org_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    parent_run_id: Optional[str] = None,
    risk: Optional[str] = "none",
    tool_name: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> TraceEvent:
    """Skapar ett TraceEvent och tvättar dess payload med Redactor."""
    # 1. Beräkna hash för den oredakterade payloaden
    payload_json = json.dumps(payload_unredacted, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    # 2. Redaktera payload
    redact_res = redact_text(payload_json)
    try:
        payload_redacted = json.loads(redact_res.text)
    except json.JSONDecodeError:
        payload_redacted = {"_raw_corrupted": redact_res.text}

    redaction_metadata = {
        "applied": len(redact_res.blocked_fields) > 0,
        "fields": redact_res.blocked_fields,
        "risk_level": redact_res.risk_level
    }

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
        redaction=redaction_metadata
    )


def write_event(event: TraceEvent, db_path: Path | None = None) -> None:
    """Skriver ett TraceEvent till tabellen trace_events i core-DB."""
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
            json.dumps(event.payload_redacted, ensure_ascii=False),
            event.payload_hash,
            event.payload_hash_algorithm,
            event.redactor_version,
            json.dumps(event.redaction, ensure_ascii=False),
        )
    )
    conn.commit()
    conn.close()


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
        risk=row[12],
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
    """Hämtar alla händelser för en viss körning (run_id) sorterade kronologiskt."""
    conn = connect(db_path)
    cursor = conn.execute(
        "SELECT * FROM trace_events WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,)
    )
    events = [_row_to_event(row) for row in cursor.fetchall()]
    conn.close()
    return events


def list_events_by_session(session_id: str, db_path: Path | None = None) -> list[TraceEvent]:
    """Hämtar alla händelser för en viss session (session_id) sorterade kronologiskt."""
    conn = connect(db_path)
    cursor = conn.execute(
        "SELECT * FROM trace_events WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,)
    )
    events = [_row_to_event(row) for row in cursor.fetchall()]
    conn.close()
    return events

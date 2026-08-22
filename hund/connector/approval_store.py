"""ApprovalStorage — SQLite-backed CRUD for ApprovalRequest persistence.

Uses the same core database (hund.db) as trace_events but with its own
approvals table. Supports create, get_by_id, get_pending, resolve, and
timeout detection.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..store.sqlite import connect
from .approval import ApprovalRequest

APPROVAL_TABLE = "approvals"
_DEFAULT_TIMEOUT_S = 300


def _ensure_table(db_path: Path | None = None) -> None:
    """Idempotent schema creation for approvals table."""
    conn = connect(db_path)
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {APPROVAL_TABLE} (
            approval_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            intent_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            args_hash TEXT DEFAULT '',
            risk_level TEXT NOT NULL,
            workspace_id TEXT DEFAULT '',
            connector_id TEXT DEFAULT '',
            user_decision TEXT DEFAULT 'pending',
            user_signature TEXT DEFAULT '',
            nonce TEXT NOT NULL,
            created_at TEXT NOT NULL,
            approved_at TEXT DEFAULT '',
            expires_at TEXT DEFAULT '',
            intent_payload TEXT DEFAULT '{{}}'
        )"""
    )
    conn.commit()
    conn.close()


def _row_to_approval(row: tuple) -> ApprovalRequest | None:
    if not row:
        return None
    columns = [
        "approval_id", "schema_version", "intent_id", "tool_name",
        "args_hash", "risk_level", "workspace_id", "connector_id",
        "user_decision", "user_signature", "nonce", "created_at",
        "approved_at", "expires_at", "intent_payload",
    ]
    data = dict(zip(columns, row))
    if data.get("intent_payload"):
        try:
            data["intent_payload"] = json.loads(data["intent_payload"])
        except (json.JSONDecodeError, TypeError):
            data["intent_payload"] = {}
    return ApprovalRequest(**data)


def create_approval(
    intent_id: str,
    tool_name: str,
    args_hash: str,
    risk_level: str,
    workspace_id: str = "",
    connector_id: str = "",
    intent_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> ApprovalRequest:
    """Create a new pending approval request and persist it."""
    _ensure_table(db_path)

    approval = ApprovalRequest(
        intent_id=intent_id,
        tool_name=tool_name,
        args_hash=args_hash,
        risk_level=risk_level,
        workspace_id=workspace_id,
        connector_id=connector_id,
        intent_payload=intent_payload or {},
    )

    conn = connect(db_path)
    conn.execute(
        f"""INSERT INTO {APPROVAL_TABLE} (
            approval_id, schema_version, intent_id, tool_name, args_hash,
            risk_level, workspace_id, connector_id, user_decision,
            user_signature, nonce, created_at, approved_at, expires_at,
            intent_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            approval.approval_id,
            approval.schema_version,
            approval.intent_id,
            approval.tool_name,
            approval.args_hash,
            approval.risk_level,
            approval.workspace_id,
            approval.connector_id,
            approval.user_decision,
            approval.user_signature,
            approval.nonce,
            approval.created_at,
            approval.approved_at,
            approval.expires_at,
            json.dumps(approval.intent_payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    conn.commit()
    conn.close()
    return approval


def get_approval(approval_id: str, db_path: Path | None = None) -> ApprovalRequest | None:
    """Get an approval by ID."""
    _ensure_table(db_path)
    conn = connect(db_path)
    row = conn.execute(
        f"SELECT * FROM {APPROVAL_TABLE} WHERE approval_id = ?",
        (approval_id,),
    ).fetchone()
    conn.close()
    return _row_to_approval(row)


def get_pending_approvals(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Get all pending approvals that have not timed out.

    Returns API-safe dicts (no intent_payload by default).
    Expired approvals are auto-marked as 'timeout'.
    """
    _ensure_table(db_path)
    conn = connect(db_path)
    rows = conn.execute(
        f"SELECT * FROM {APPROVAL_TABLE} WHERE user_decision = 'pending' ORDER BY created_at DESC",
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        approval = _row_to_approval(row)
        if approval is None:
            continue
        # Auto-timeout check
        if approval.is_expired(timeout_s=_DEFAULT_TIMEOUT_S):
            resolve_approval(
                approval_id=approval.approval_id,
                user_decision="timeout",
                user_signature="",
                db_path=db_path,
            )
            continue
        result.append(approval.model_dump_api())
    return result


def resolve_approval(
    approval_id: str,
    user_decision: str,
    user_signature: str = "",
    db_path: Path | None = None,
) -> ApprovalRequest | None:
    """Resolve a pending approval (approved/denied/timeout).

    Returns the updated ApprovalRequest, or None if not found.
    """
    if user_decision not in {"approved", "denied", "timeout"}:
        raise ValueError(f"invalid user_decision: {user_decision}")

    _ensure_table(db_path)
    conn = connect(db_path)

    # Verify it exists and is still pending
    row = conn.execute(
        f"SELECT * FROM {APPROVAL_TABLE} WHERE approval_id = ?",
        (approval_id,),
    ).fetchone()

    if row is None:
        conn.close()
        return None

    approval = _row_to_approval(row)
    if approval is None or approval.user_decision != "pending":
        conn.close()
        return None

    approved_at = ""
    if user_decision == "approved":
        approved_at = datetime.now(timezone.utc).isoformat()

    conn.execute(
        f"""UPDATE {APPROVAL_TABLE}
            SET user_decision = ?, user_signature = ?, approved_at = ?
            WHERE approval_id = ?""",
        (user_decision, user_signature, approved_at, approval_id),
    )
    conn.commit()
    conn.close()

    approval.user_decision = user_decision
    approval.user_signature = user_signature
    approval.approved_at = approved_at
    return approval


def cancel_approval(
    approval_id: str,
    db_path: Path | None = None,
) -> ApprovalRequest | None:
    """Cancel a pending approval (user denied via dashboard)."""
    return resolve_approval(
        approval_id=approval_id,
        user_decision="denied",
        user_signature="dashboard_cancel",
        db_path=db_path,
    )

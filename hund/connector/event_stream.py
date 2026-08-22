"""Event stream — read-only access to trace events via connector endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..trace.events import (
    list_events_by_run,
    list_events_by_session,
    list_events_by_type,
)


def query_events(
    *,
    run_id: str | None = None,
    session_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Query trace events with optional filters. Returns redacted payloads.

    All filters are optional. If none provided, returns recent events.
    """
    events = []

    if run_id:
        events = list_events_by_run(run_id, db_path=db_path)
    elif session_id:
        events = list_events_by_session(session_id, db_path=db_path)
    elif event_type:
        events = list_events_by_type(event_type, db_path=db_path)
    else:
        # No filter — return last N events via list_events_by_type with
        # a known event type and post-filter. This is a fallback.
        from ..store.sqlite import connect

        conn = connect(db_path)
        rows = conn.execute(
            "SELECT * FROM trace_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        from ..trace.events import _row_to_event

        events = [_row_to_event(row) for row in rows]

    # Convert to dicts with redacted payload
    result = []
    for ev in events:
        result.append(
            {
                "event_id": ev.event_id,
                "event_type": ev.event_type,
                "created_at": ev.created_at,
                "actor": ev.actor,
                "risk": ev.risk,
                "tool_name": ev.tool_name,
                "payload_redacted": ev.payload_redacted,
                "payload_hash": ev.payload_hash,
                "redaction": ev.redaction,
                "connector_id": ev.connector_id,
                "run_id": ev.run_id,
                "session_id": ev.session_id,
                "turn_id": ev.turn_id,
            }
        )

    # Apply since filter if given
    if since and not run_id and not session_id:
        result = [r for r in result if r["created_at"] >= since]

    return result[:limit]

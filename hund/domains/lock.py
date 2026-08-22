"""Domain Lock — lock a domain after sufficient confidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..store.sqlite import connect
from ..trace.events import record_event
from .confidence import get_confidence, list_confidence


def lock_domain(domain: str, user_confirmed: bool = False) -> bool:
    """Lock a domain. Requires user_confirmed=True (human gate)."""
    if not user_confirmed:
        return False

    confidence = get_confidence(domain)
    if not confidence or not confidence.is_lockable:
        return False

    conn = connect()
    conn.execute(
        "INSERT INTO domains (domain, status, confidence, detected_at) VALUES (?, 'locked', 'high', ?) "
        "ON CONFLICT(domain) DO UPDATE SET status='locked', confidence='high'",
        (domain, datetime.now(timezone.utc).isoformat()),
    )
    conn.execute("UPDATE domains SET status='active' WHERE status='primary'")
    conn.execute("UPDATE domains SET status='primary' WHERE domain=?", (domain,))
    conn.commit()
    conn.close()

    record_event(
        workspace_id="core", session_id="system", run_id="domain_lock",
        actor="system", event_type="domain_locked",
        policy_version="1.0.0",
        payload_unredacted={"domain": domain, "confidence": confidence.percentage},
    )
    return True


def list_lockable(db_path=None) -> list[dict[str, Any]]:
    """List domains ready for locking."""
    return [c for c in list_confidence(db_path) if c.get("is_lockable")]


def set_domain_status(domain: str, status: str) -> bool:
    conn = connect()
    conn.execute("UPDATE domains SET status=? WHERE domain=?", (status, domain))
    conn.commit()
    conn.close()
    return True

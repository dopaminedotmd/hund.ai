"""Observer — lokala gap-events (prestation om HUND, ALDRIG användardata).

PRIVACY-INVARIANT (review, hårt):
  - Lokalt: symptom-fritext får finnas LOKALT (hjälper Hund studera gap).
  - Extern upload: AV i v1. När på: structured-only, inga fritextfält lämnar
    maskinen förrän adversariell redactor-svit är grön.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..store.sqlite import connect
from .gap_detector import detect_evidence_gaps


@dataclass
class Observation:
    task_class: str
    performance_event: str  # success|failure|near_miss|user_correction|...
    privacy_level: str = "local_only"  # default: lämnar aldrig maskinen


def add_gap_event(
    symptom: str,
    domain: str = "unknown",
    study_target: str = "",
    db_path=None,
) -> str:
    """Logga ett gap (kunskapslucka Hund ska studera). Returnerar gap-id."""
    conn = connect(db_path)
    gid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO gap_events(id, created_at, domain, symptom, study_target, status)
           VALUES (?,?,?,?,?,?)""",
        (
            gid,
            datetime.now(timezone.utc).isoformat(),
            domain,
            symptom,
            study_target,
            "open",
        ),
    )
    conn.commit()
    conn.close()
    # Gap observations are telemetry only. Durable knowledge XP is awarded
    # exclusively by CommitController lifecycle events.
    return gid


def observe_epistemic_gaps(user_message: str, *, domain: str = "unknown", db_path=None) -> list[str]:
    """Persist only structured, redacted gap labels—not the user's raw prompt."""
    ids: list[str] = []
    for gap in detect_evidence_gaps(user_message):
        ids.append(add_gap_event(
            symptom=f"epistemic:{gap.kind}",
            domain=domain,
            study_target=gap.study_target,
            db_path=db_path,
        ))
    return ids


def list_gap_events(status: str | None = None) -> list[tuple]:
    conn = connect()
    if status:
        rows = conn.execute(
            """SELECT substr(id,1,8), substr(created_at,1,10), domain, symptom, status
               FROM gap_events WHERE status=? ORDER BY created_at DESC""",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT substr(id,1,8), substr(created_at,1,10), domain, symptom, status
               FROM gap_events ORDER BY created_at DESC"""
        ).fetchall()
    conn.close()
    return rows


def set_gap_status(gid_prefix: str, status: str) -> int:
    """Stäng/öppna gap via id-prefix. Returnerar antal ändrade."""
    conn = connect()
    cur = conn.execute(
        "UPDATE gap_events SET status=? WHERE id LIKE ?",
        (status, gid_prefix + "%"),
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n

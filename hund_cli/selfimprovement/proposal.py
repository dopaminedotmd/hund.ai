"""Proposal — deklarativt förbättringsförslag från gaps. Ej exekverbar kod."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..learning.redactor import redact_text
from ..store.sqlite import connect

# TCB-skydd: change_type tvingas deklarativ. Core-kod får aldrig föreslås.
ALLOWED_CHANGE_TYPES = {"runtime_policy", "skill", "hundk", "prompt", "test"}

# Change-types som kräver rollback_note (alla write-nära typer).
WRITE_CHANGE_TYPES = {"runtime_policy", "skill", "hundk"}

# Mönster för råa filinnehåll — blockeras ur förslag.
_RAW_CONTENT_PATTERNS = [
    re.compile(r"^(?:content|file_content|raw_content)$", re.IGNORECASE),
]
_RAW_CONTENT_MAX_CHARS = 500  # Fält som är längre än så misstänks vara rådata

_COLS = [
    "id", "created_at", "title", "problem", "proposed_change",
    "change_type", "risk", "tests_needed", "related_gaps", "status",
    "verification_required", "rollback_note",
]


@dataclass
class Proposal:
    id: str
    created_at: str
    title: str
    problem: str
    proposed_change: str
    change_type: str
    risk: str
    tests_needed: str
    related_gaps: list
    status: str = "proposed"
    # Fas 8 — v1.5 fält
    verification_required: bool = True  # alltid True, kan inte sättas False
    rollback_note: str = ""             # obligatoriskt för write-nära change_types

    def as_markdown(self) -> str:
        rollback_section = (
            f"\n## Rollback\n{self.rollback_note}\n"
            if self.rollback_note
            else "\n## Rollback\n*(ej angiven)*\n"
        )
        verification = "✅ krävs" if self.verification_required else "⚠️ ej satt"
        return (
            f"# Proposal {self.id[:8]} — {self.title}\n\n"
            f"status: **{self.status}** · type: `{self.change_type}` · risk: {self.risk}"
            f" · verifiering: {verification}\n\n"
            f"## Problem\n{self.problem}\n\n"
            f"## Föreslagen ändring ({self.change_type})\n{self.proposed_change}\n\n"
            f"## Tester som krävs\n{self.tests_needed or '(ingen)'}\n\n"
            f"## Relaterade gaps\n{', '.join(self.related_gaps) or '(ingen)'}\n"
            + rollback_section
        )


def create(p: Proposal) -> None:
    conn = connect()
    conn.execute(
        f"INSERT INTO proposals ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
        (
            p.id, p.created_at, p.title, p.problem, p.proposed_change,
            p.change_type, p.risk, p.tests_needed, json.dumps(p.related_gaps), p.status,
            int(p.verification_required), p.rollback_note,
        ),
    )
    conn.commit()
    conn.close()


def list_proposals(status: str | None = None) -> list[Proposal]:
    conn = connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
    conn.close()
    return [_row(r) for r in rows]


def get(pid_prefix: str) -> Proposal | None:
    conn = connect()
    rows = conn.execute("SELECT * FROM proposals WHERE id LIKE ?", (pid_prefix + "%",)).fetchall()
    conn.close()
    return _row(rows[0]) if rows else None


def set_status(pid_prefix: str, status: str) -> int:
    """Markerar status i DB. Applicerar ALDRIG ändringen på systemet."""
    conn = connect()
    cur = conn.execute("UPDATE proposals SET status=? WHERE id LIKE ?", (status, pid_prefix + "%"))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def _is_raw_file_content(name: str, value: str) -> bool:
    """Returnerar True om ett fält misstänks innehålla rå fildata."""
    for pat in _RAW_CONTENT_PATTERNS:
        if pat.match(name):
            return True
    # Heuristik: mycket långa fält med radbrytningar är sannolikt råinnehåll
    if len(value) > _RAW_CONTENT_MAX_CHARS and "\n" in value:
        return True
    return False


def build_from_gaps(gaps: list, llm_summary: dict) -> "Proposal":
    """gaps: list of gap-rows; llm_summary: dikterade fält från LLM."""
    ct = llm_summary.get("change_type", "runtime_policy")
    if ct not in ALLOWED_CHANGE_TYPES:  # TCB-skydd: tvinga deklarativ
        ct = "runtime_policy"

    def safe_field(name: str, default: str = "") -> str:
        raw = str(llm_summary.get(name, default))
        # Fas 8: blockera råa filinnehåll — ersätt med placeholder
        if _is_raw_file_content(name, raw):
            return "[REDACTED: raw file content not allowed in proposals]"
        return redact_text(raw).text

    # rollback_note är obligatoriskt för write-nära typer
    rollback_raw = str(llm_summary.get("rollback_note", ""))
    rollback = redact_text(rollback_raw).text if rollback_raw else ""

    return Proposal(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=safe_field("title", "(ingen titel)"),
        problem=safe_field("problem"),
        proposed_change=safe_field("proposed_change"),
        change_type=ct,
        risk=safe_field("risk", "unknown"),
        tests_needed=safe_field("tests_needed"),
        related_gaps=[g[0] for g in gaps],
        verification_required=True,  # alltid obligatorisk
        rollback_note=rollback,
    )


def _row(r) -> Proposal:
    # Hantera både gamla rader (utan de nya kolumnerna) och nya
    if len(r) >= len(_COLS):
        d = dict(zip(_COLS, r))
    else:
        # Bakåtkompatibilitet: gamla rader saknar verification_required + rollback_note
        old_cols = _COLS[:len(r)]
        d = dict(zip(old_cols, r))
    try:
        d["related_gaps"] = json.loads(d.get("related_gaps") or "[]")
    except json.JSONDecodeError:
        d["related_gaps"] = []
    d.setdefault("verification_required", True)
    d.setdefault("rollback_note", "")
    # Konvertera int → bool för verification_required
    d["verification_required"] = bool(d["verification_required"])
    return Proposal(**d)


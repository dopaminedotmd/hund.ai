"""Proposal — deklarativt förbättringsförslag från gaps. Ej exekverbar kod."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..store.sqlite import connect

# TCB-skydd: change_type tvingas deklarativ. Core-kod får aldrig föreslås.
ALLOWED_CHANGE_TYPES = {"runtime_policy", "skill", "hundk", "prompt", "test"}

_COLS = [
    "id", "created_at", "title", "problem", "proposed_change",
    "change_type", "risk", "tests_needed", "related_gaps", "status",
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

    def as_markdown(self) -> str:
        return (
            f"# Proposal {self.id[:8]} — {self.title}\n\n"
            f"status: **{self.status}** · type: `{self.change_type}` · risk: {self.risk}\n\n"
            f"## Problem\n{self.problem}\n\n"
            f"## Föreslagen ändring ({self.change_type})\n{self.proposed_change}\n\n"
            f"## Tester som krävs\n{self.tests_needed or '(ingen)'}\n\n"
            f"## Relaterade gaps\n{', '.join(self.related_gaps) or '(ingen)'}\n"
        )


def create(p: Proposal) -> None:
    conn = connect()
    conn.execute(
        f"INSERT INTO proposals ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
        (
            p.id, p.created_at, p.title, p.problem, p.proposed_change,
            p.change_type, p.risk, p.tests_needed, json.dumps(p.related_gaps), p.status,
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
    conn = connect()
    cur = conn.execute("UPDATE proposals SET status=? WHERE id LIKE ?", (status, pid_prefix + "%"))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def build_from_gaps(gaps: list, llm_summary: dict) -> Proposal:
    """gaps: list of gap-rows; llm_summary: dikterade fält från LLM."""
    ct = llm_summary.get("change_type", "runtime_policy")
    if ct not in ALLOWED_CHANGE_TYPES:  # TCB-skydd: tvinga deklarativ
        ct = "runtime_policy"
    return Proposal(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=llm_summary.get("title", "(ingen titel)"),
        problem=llm_summary.get("problem", ""),
        proposed_change=llm_summary.get("proposed_change", ""),
        change_type=ct,
        risk=llm_summary.get("risk", "unknown"),
        tests_needed=llm_summary.get("tests_needed", ""),
        related_gaps=[g[0] for g in gaps],
    )


def _row(r) -> Proposal:
    d = dict(zip(_COLS, r))
    try:
        d["related_gaps"] = json.loads(d["related_gaps"] or "[]")
    except json.JSONDecodeError:
        d["related_gaps"] = []
    return Proposal(**d)

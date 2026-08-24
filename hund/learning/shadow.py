"""Shadow mode execution and metric tracking for candidate evaluator.

Runs candidate evaluator without write-access to live knowledge stores,
logging all proposals for precision/noise analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from ..paths import hund_home
from ..store.sqlite import connect
from .evaluator import CandidateProposal

SHADOW_TABLE = "shadow_proposals"


def _shadow_db_path(custom_path: Path | str | None = None) -> Path:
    if custom_path:
        return Path(custom_path)
    return hund_home() / "learning" / "shadow.db"


def _ensure_shadow_table(db_path: Path | str | None = None) -> None:
    p = _shadow_db_path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(p)
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {SHADOW_TABLE} (
            proposal_id TEXT PRIMARY KEY,
            session_id TEXT,
            turn_id INTEGER,
            timestamp TEXT NOT NULL,
            proposition TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            relation_to_existing TEXT NOT NULL,
            reusability REAL NOT NULL,
            confidence REAL NOT NULL,
            suggested_action TEXT NOT NULL,
            evidence_ids TEXT DEFAULT '[]',
            deps TEXT DEFAULT '{{}}'
        )"""
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_shadow_scope ON {SHADOW_TABLE}(scope_type, scope_id)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_shadow_relation ON {SHADOW_TABLE}(relation_to_existing)")
    conn.commit()
    conn.close()


def log_shadow_proposal(
    proposal: CandidateProposal,
    session_id: str = "",
    turn_id: int = 0,
    db_path: Path | str | None = None,
) -> str:
    """Record a candidate proposal into the shadow evaluation log."""
    _ensure_shadow_table(db_path)
    proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    conn = connect(_shadow_db_path(db_path))
    conn.execute(
        f"""INSERT INTO {SHADOW_TABLE} (
            proposal_id, session_id, turn_id, timestamp, proposition,
            scope_type, scope_id, kind, relation_to_existing,
            reusability, confidence, suggested_action, evidence_ids, deps
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            proposal_id,
            session_id,
            turn_id,
            now,
            proposal.proposition,
            proposal.scope.get("type", "domain"),
            proposal.scope.get("id", "general"),
            proposal.kind,
            proposal.relation_to_existing,
            proposal.reusability,
            proposal.confidence,
            proposal.suggested_action,
            json.dumps(proposal.evidence_ids),
            json.dumps(proposal.deps),
        ),
    )
    conn.commit()
    conn.close()
    return proposal_id


def list_shadow_proposals(
    limit: int = 50,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve logged shadow proposals."""
    _ensure_shadow_table(db_path)
    conn = connect(_shadow_db_path(db_path))
    rows = conn.execute(
        f"""SELECT proposal_id, session_id, turn_id, timestamp, proposition,
                   scope_type, scope_id, kind, relation_to_existing,
                   reusability, confidence, suggested_action, evidence_ids, deps
            FROM {SHADOW_TABLE} ORDER BY timestamp DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append({
            "proposal_id": r[0],
            "session_id": r[1],
            "turn_id": r[2],
            "timestamp": r[3],
            "proposition": r[4],
            "scope": {"type": r[5], "id": r[6]},
            "kind": r[7],
            "relation_to_existing": r[8],
            "reusability": r[9],
            "confidence": r[10],
            "suggested_action": r[11],
            "evidence_ids": json.loads(r[12] or "[]"),
            "deps": json.loads(r[13] or "{}"),
        })
    return results


def get_shadow_stats(db_path: Path | str | None = None) -> dict[str, Any]:
    """Calculate shadow evaluation distribution and statistics."""
    _ensure_shadow_table(db_path)
    conn = connect(_shadow_db_path(db_path))

    total = conn.execute(f"SELECT COUNT(*) FROM {SHADOW_TABLE}").fetchone()[0]
    if total == 0:
        conn.close()
        return {
            "total_proposals": 0,
            "actions": {},
            "relations": {},
            "scopes": {},
            "avg_confidence": 0.0,
            "avg_reusability": 0.0,
        }

    # Action breakdown
    action_rows = conn.execute(
        f"SELECT suggested_action, COUNT(*) FROM {SHADOW_TABLE} GROUP BY suggested_action"
    ).fetchall()
    actions = {r[0]: r[1] for r in action_rows}

    # Relation breakdown
    relation_rows = conn.execute(
        f"SELECT relation_to_existing, COUNT(*) FROM {SHADOW_TABLE} GROUP BY relation_to_existing"
    ).fetchall()
    relations = {r[0]: r[1] for r in relation_rows}

    # Scope breakdown
    scope_rows = conn.execute(
        f"SELECT scope_type, COUNT(*) FROM {SHADOW_TABLE} GROUP BY scope_type"
    ).fetchall()
    scopes = {r[0]: r[1] for r in scope_rows}

    # Averages
    avg_row = conn.execute(
        f"SELECT AVG(confidence), AVG(reusability) FROM {SHADOW_TABLE}"
    ).fetchone()
    conn.close()

    return {
        "total_proposals": total,
        "actions": actions,
        "relations": relations,
        "scopes": scopes,
        "avg_confidence": round(avg_row[0] or 0.0, 3),
        "avg_reusability": round(avg_row[1] or 0.0, 3),
    }

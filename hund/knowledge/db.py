"""SQLite storage and schema for knowledge units and lifecycle auditing."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from ..paths import hund_home
from ..store.sqlite import connect
from .models import (
    ACTION_CREATE,
    KnowledgeAuditEntry,
    KnowledgeUnit,
    STATUS_CANDIDATE,
    STATUS_VALIDATED,
)

KNOWLEDGE_TABLE = "knowledge_units"
AUDIT_TABLE = "knowledge_audit"


def get_knowledge_db_path(custom_path: Path | str | None = None) -> Path:
    """Return path to canonical knowledge.db."""
    if custom_path:
        return Path(custom_path)
    return hund_home() / "knowledge" / "knowledge.db"


def ensure_knowledge_tables(db_path: Path | str | None = None) -> None:
    """Create knowledge_units and knowledge_audit tables if they do not exist."""
    p = get_knowledge_db_path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(p)

    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {KNOWLEDGE_TABLE} (
            id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            statement TEXT NOT NULL,
            trigger TEXT DEFAULT '',
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence_ids TEXT DEFAULT '[]',
            deps TEXT DEFAULT '{{}}',
            supersedes TEXT,
            support_count INTEGER DEFAULT 0,
            contradiction_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_used TEXT,
            last_validated_at TEXT
        )"""
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON {KNOWLEDGE_TABLE}(domain)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_knowledge_status ON {KNOWLEDGE_TABLE}(status)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_knowledge_kind ON {KNOWLEDGE_TABLE}(kind)")

    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
            audit_id TEXT PRIMARY KEY,
            unit_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            reason TEXT DEFAULT '',
            evidence_id TEXT,
            timestamp TEXT NOT NULL
        )"""
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_knowledge_audit_unit ON {AUDIT_TABLE}(unit_id)")

    conn.commit()
    conn.close()


def insert_unit(
    unit: KnowledgeUnit,
    action: str = ACTION_CREATE,
    reason: str = "initial candidate ingestion",
    evidence_id: Optional[str] = None,
    db_path: Path | str | None = None,
) -> str:
    """Insert a new knowledge unit and record its audit creation entry."""
    ensure_knowledge_tables(db_path)
    now = datetime.now(timezone.utc).isoformat()
    if not unit.created_at:
        unit.created_at = now

    audit_id = f"kaudit_{uuid.uuid4().hex[:12]}"
    conn = connect(get_knowledge_db_path(db_path))

    conn.execute(
        f"""INSERT INTO {KNOWLEDGE_TABLE} (
            id, domain, statement, trigger, kind, status, confidence,
            evidence_ids, deps, supersedes, support_count, contradiction_count,
            created_at, last_used, last_validated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            unit.id,
            unit.domain,
            unit.statement,
            unit.trigger,
            unit.kind,
            unit.status,
            unit.confidence,
            json.dumps(unit.evidence_ids),
            json.dumps(unit.deps),
            unit.supersedes,
            unit.support_count,
            unit.contradiction_count,
            unit.created_at,
            unit.last_used,
            unit.last_validated_at,
        ),
    )

    conn.execute(
        f"""INSERT INTO {AUDIT_TABLE} (
            audit_id, unit_id, action, old_status, new_status, reason, evidence_id, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (audit_id, unit.id, action, None, unit.status, reason, evidence_id, now),
    )

    conn.commit()
    conn.close()
    return unit.id


def get_unit(unit_id: str, db_path: Path | str | None = None) -> Optional[KnowledgeUnit]:
    """Fetch single knowledge unit by ID."""
    ensure_knowledge_tables(db_path)
    conn = connect(get_knowledge_db_path(db_path))
    row = conn.execute(
        f"""SELECT id, domain, statement, trigger, kind, status, confidence,
                   evidence_ids, deps, supersedes, support_count, contradiction_count,
                   created_at, last_used, last_validated_at
            FROM {KNOWLEDGE_TABLE} WHERE id = ?""",
        (unit_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None
    return KnowledgeUnit.from_row(row)


def list_units(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Path | str | None = None,
) -> list[KnowledgeUnit]:
    """List knowledge units with optional domain and status filter."""
    ensure_knowledge_tables(db_path)
    conn = connect(get_knowledge_db_path(db_path))

    query = f"""SELECT id, domain, statement, trigger, kind, status, confidence,
                       evidence_ids, deps, supersedes, support_count, contradiction_count,
                       created_at, last_used, last_validated_at
                FROM {KNOWLEDGE_TABLE} WHERE 1=1"""
    params: list[Any] = []

    if domain:
        query += " AND domain = ?"
        params.append(domain)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY confidence DESC, support_count DESC, created_at ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [KnowledgeUnit.from_row(r) for r in rows]


def update_unit_status(
    unit_id: str,
    new_status: str,
    action: str,
    reason: str,
    evidence_id: Optional[str] = None,
    confidence_delta: float = 0.0,
    support_delta: int = 0,
    contradiction_delta: int = 0,
    last_used: Optional[str] = None,
    db_path: Path | str | None = None,
) -> bool:
    """Transition unit status and log audit trail."""
    ensure_knowledge_tables(db_path)
    conn = connect(get_knowledge_db_path(db_path))

    row = conn.execute(
        f"SELECT status, confidence, support_count, contradiction_count FROM {KNOWLEDGE_TABLE} WHERE id = ?",
        (unit_id,),
    ).fetchone()
    if row is None:
        conn.close()
        return False

    old_status = row[0]
    current_conf = float(row[1])
    current_support = int(row[2] or 0)
    current_contradiction = int(row[3] or 0)

    new_conf = max(0.0, min(1.0, current_conf + confidence_delta))
    new_support = max(0, current_support + support_delta)
    new_contradiction = max(0, current_contradiction + contradiction_delta)
    now = datetime.now(timezone.utc).isoformat()
    audit_id = f"kaudit_{uuid.uuid4().hex[:12]}"

    last_val = now if new_status == STATUS_VALIDATED else None

    conn.execute(
        f"""UPDATE {KNOWLEDGE_TABLE}
            SET status = ?, confidence = ?, support_count = ?, contradiction_count = ?,
                last_used = COALESCE(?, last_used),
                last_validated_at = COALESCE(?, last_validated_at)
            WHERE id = ?""",
        (new_status, new_conf, new_support, new_contradiction, last_used, last_val, unit_id),
    )

    conn.execute(
        f"""INSERT INTO {AUDIT_TABLE} (
            audit_id, unit_id, action, old_status, new_status, reason, evidence_id, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (audit_id, unit_id, action, old_status, new_status, reason, evidence_id, now),
    )

    conn.commit()
    conn.close()
    return True



def list_audit_trail(unit_id: str, db_path: Path | str | None = None) -> list[KnowledgeAuditEntry]:
    """List audit entries for a knowledge unit."""
    ensure_knowledge_tables(db_path)
    conn = connect(get_knowledge_db_path(db_path))
    rows = conn.execute(
        f"""SELECT audit_id, unit_id, action, old_status, new_status, reason, evidence_id, timestamp
            FROM {AUDIT_TABLE} WHERE unit_id = ? ORDER BY timestamp ASC""",
        (unit_id,),
    ).fetchall()
    conn.close()
    return [KnowledgeAuditEntry.from_row(r) for r in rows]

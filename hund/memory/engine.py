"""Evidence weighting engine, trust enforcement, and state transitions for memory."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional
import uuid

from ..learning.trust import (
    SOURCE_CONFIRMED_ACTION,
    SOURCE_INFERENCE,
    SOURCE_USER,
    source_allowed,
)
from .db import connect_memory
from .models import (
    ACTION_CREATE,
    ACTION_FLAG_CONFLICT,
    ACTION_FORGET,
    ACTION_PROMOTE,
    ACTION_SUPERSEDE,
    CATEGORY_CORE,
    CATEGORY_STABLE_PREFERENCE,
    MemoryAuditEntry,
    MemoryItem,
    SCOPE_USER_GLOBAL,
    STATUS_DRAFT,
    STATUS_FLAGGED,
    STATUS_FORGOTTEN,
    STATUS_SUPERSEDED,
    STATUS_VERIFIED,
)

# Evidence weights
WEIGHT_EXPLICIT_PREFERENCE = 1.0
WEIGHT_EXPLICIT_CORRECTION = 1.2
WEIGHT_EXPLICIT_CHOICE = 0.7
WEIGHT_REPEATED_BEHAVIOR = 0.35
WEIGHT_ASSISTANT_INFERENCE = 0.15
WEIGHT_CONTRADICTION = -0.8
PROMOTION_THRESHOLD = 1.0


def _log_audit(
    conn: Any,
    memory_id: str,
    action: str,
    reason: str = "",
    old_value: str = "",
    new_value: str = "",
    evidence_id: str = "",
    timestamp: str | None = None,
) -> None:
    audit_id = f"aud_{uuid.uuid4().hex[:12]}"
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO memory_audit (
            audit_id, memory_id, action, reason, old_value, new_value, evidence_id, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (audit_id, memory_id, action, reason, old_value, new_value, evidence_id, ts),
    )


def record_memory(
    statement: str,
    scope: str = SCOPE_USER_GLOBAL,
    category: str = CATEGORY_STABLE_PREFERENCE,
    source_type: str = SOURCE_USER,
    evidence_ids: list[str] | None = None,
    is_core: bool = False,
    initial_confidence: float | None = None,
    expires_at: str | None = None,
    db_path: Path | str | None = None,
    memory_id: str | None = None,
) -> MemoryItem:
    """Record a new memory observation with strict trust boundary check.

    Raises PermissionError if source_type is forbidden from writing to the memory scope.
    """
    # Trust boundary check: only allowed sources can write to user memory
    dest = "user" if scope == SCOPE_USER_GLOBAL or "user" in scope else "project"
    if not source_allowed(source_type, dest):
        raise PermissionError(
            f"Source '{source_type}' is not permitted to write to destination '{dest}'."
        )

    clean_statement = statement.strip()
    if not clean_statement:
        raise ValueError("Memory statement cannot be empty.")

    existing_conn = connect_memory(db_path)
    existing = existing_conn.execute(
        """SELECT memory_id FROM memory
           WHERE scope=? AND category=? AND lower(trim(statement))=lower(trim(?))
             AND status IN ('verified', 'draft') AND superseded_by IS NULL
           ORDER BY confidence DESC, last_seen DESC LIMIT 1""",
        (scope, category, clean_statement),
    ).fetchone()
    existing_conn.close()
    if existing is not None:
        reinforced = reinforce_memory(
            existing[0],
            evidence_id=(evidence_ids or [None])[0],
            db_path=db_path,
        )
        if reinforced is not None:
            return reinforced

    # Calculate initial confidence
    if initial_confidence is not None:
        confidence = float(initial_confidence)
    elif is_core or category == CATEGORY_CORE:
        confidence = 1.5
    elif source_type == SOURCE_USER:
        confidence = WEIGHT_EXPLICIT_PREFERENCE
    elif source_type == SOURCE_CONFIRMED_ACTION:
        confidence = WEIGHT_EXPLICIT_PREFERENCE
    elif source_type == SOURCE_INFERENCE:
        confidence = WEIGHT_ASSISTANT_INFERENCE
    else:
        confidence = 0.5

    status = STATUS_VERIFIED if (confidence >= PROMOTION_THRESHOLD or is_core) else STATUS_DRAFT
    mem_id = memory_id or f"mem_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    ev_ids = evidence_ids or []

    item = MemoryItem(
        memory_id=mem_id,
        scope=scope,
        category=category,
        statement=clean_statement,
        status=status,
        confidence=confidence,
        source_type=source_type,
        first_seen=now,
        last_seen=now,
        support_count=1,
        contradiction_count=0,
        evidence_ids=ev_ids,
        supersedes=None,
        superseded_by=None,
        expires_at=expires_at,
        is_core=is_core or (category == CATEGORY_CORE),
    )

    conn = connect_memory(db_path)
    conn.execute(
        """INSERT INTO memory (
            memory_id, scope, category, statement, status, confidence, source_type,
            first_seen, last_seen, support_count, contradiction_count, evidence_ids,
            supersedes, superseded_by, expires_at, is_core
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        item.to_row(),
    )
    _log_audit(
        conn,
        mem_id,
        ACTION_CREATE,
        reason=f"initial_record_via_{source_type}",
        new_value=clean_statement,
        evidence_id=ev_ids[0] if ev_ids else "",
        timestamp=now,
    )
    conn.commit()
    conn.close()
    return item


def reinforce_memory(
    memory_id: str,
    signal_weight: float = WEIGHT_REPEATED_BEHAVIOR,
    evidence_id: str | None = None,
    db_path: Path | str | None = None,
) -> MemoryItem | None:
    """Reinforce an existing memory with repeated evidence. Promotes draft -> verified when score >= 1.0."""
    conn = connect_memory(db_path)
    row = conn.execute("SELECT * FROM memory WHERE memory_id = ?", (memory_id,)).fetchone()
    if row is None:
        conn.close()
        return None

    item = MemoryItem.from_row(row)
    now = datetime.now(timezone.utc).isoformat()

    new_conf = min(2.0, item.confidence + signal_weight)
    new_support = item.support_count + 1
    new_ev_ids = list(item.evidence_ids)
    if evidence_id and evidence_id not in new_ev_ids:
        new_ev_ids.append(evidence_id)

    old_status = item.status
    new_status = item.status
    if item.status == STATUS_DRAFT and new_conf >= PROMOTION_THRESHOLD:
        new_status = STATUS_VERIFIED
        _log_audit(
            conn,
            memory_id,
            ACTION_PROMOTE,
            reason=f"score_reached_{new_conf:.2f}",
            old_value=old_status,
            new_value=new_status,
            evidence_id=evidence_id or "",
            timestamp=now,
        )

    conn.execute(
        """UPDATE memory
           SET confidence = ?, support_count = ?, last_seen = ?, evidence_ids = ?, status = ?
           WHERE memory_id = ?""",
        (new_conf, new_support, now, json.dumps(new_ev_ids), new_status, memory_id),
    )
    conn.commit()
    conn.close()

    item.confidence = new_conf
    item.support_count = new_support
    item.last_seen = now
    item.evidence_ids = new_ev_ids
    item.status = new_status
    return item


def apply_correction(
    new_statement: str,
    old_memory_id: str | None = None,
    scope: str = SCOPE_USER_GLOBAL,
    category: str = CATEGORY_STABLE_PREFERENCE,
    source_type: str = SOURCE_USER,
    evidence_id: str | None = None,
    is_core: bool = False,
    db_path: Path | str | None = None,
) -> tuple[MemoryItem, Optional[MemoryItem]]:
    """Apply an explicit user correction.

    Immediately supersedes old_memory_id (if provided) and creates the new verified memory.
    """
    dest = "user" if scope == SCOPE_USER_GLOBAL or "user" in scope else "project"
    if not source_allowed(source_type, dest):
        raise PermissionError(
            f"Source '{source_type}' is not permitted to write to destination '{dest}'."
        )

    now = datetime.now(timezone.utc).isoformat()
    new_id = f"mem_{uuid.uuid4().hex[:12]}"
    ev_ids = [evidence_id] if evidence_id else []

    conn = connect_memory(db_path)
    old_item: Optional[MemoryItem] = None

    if old_memory_id:
        row = conn.execute("SELECT * FROM memory WHERE memory_id = ?", (old_memory_id,)).fetchone()
        if row:
            old_item = MemoryItem.from_row(row)
            conn.execute(
                "UPDATE memory SET status = ?, superseded_by = ?, last_seen = ? WHERE memory_id = ?",
                (STATUS_SUPERSEDED, new_id, now, old_memory_id),
            )
            _log_audit(
                conn,
                old_memory_id,
                ACTION_SUPERSEDE,
                reason=f"superseded_by_{new_id}",
                old_value=old_item.statement,
                new_value=new_statement,
                evidence_id=evidence_id or "",
                timestamp=now,
            )
            old_item.status = STATUS_SUPERSEDED
            old_item.superseded_by = new_id

    new_item = MemoryItem(
        memory_id=new_id,
        scope=scope,
        category=category,
        statement=new_statement.strip(),
        status=STATUS_VERIFIED,
        confidence=WEIGHT_EXPLICIT_CORRECTION,
        source_type=source_type,
        first_seen=now,
        last_seen=now,
        support_count=1,
        contradiction_count=0,
        evidence_ids=ev_ids,
        supersedes=old_memory_id,
        superseded_by=None,
        expires_at=None,
        is_core=is_core or (category == CATEGORY_CORE),
    )

    conn.execute(
        """INSERT INTO memory (
            memory_id, scope, category, statement, status, confidence, source_type,
            first_seen, last_seen, support_count, contradiction_count, evidence_ids,
            supersedes, superseded_by, expires_at, is_core
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        new_item.to_row(),
    )
    _log_audit(
        conn,
        new_id,
        ACTION_CREATE,
        reason="explicit_correction",
        new_value=new_statement.strip(),
        evidence_id=evidence_id or "",
        timestamp=now,
    )
    conn.commit()
    conn.close()
    return new_item, old_item


def record_contradiction(
    memory_id: str,
    evidence_id: str | None = None,
    reason: str = "",
    db_path: Path | str | None = None,
) -> MemoryItem | None:
    """Record a contradiction against an existing memory.

    Decrements confidence. If contradictions accumulate or confidence drops below 0.5, flags conflict.
    #core items are protected from automatic degradation.
    """
    conn = connect_memory(db_path)
    row = conn.execute("SELECT * FROM memory WHERE memory_id = ?", (memory_id,)).fetchone()
    if row is None:
        conn.close()
        return None

    item = MemoryItem.from_row(row)
    now = datetime.now(timezone.utc).isoformat()

    if item.is_core:
        # Core items cannot be weakened by automated contradictions
        conn.close()
        return item

    new_conf = max(0.0, item.confidence + WEIGHT_CONTRADICTION)
    new_contradictions = item.contradiction_count + 1
    new_status = item.status

    if new_contradictions >= 2 or new_conf < 0.5:
        new_status = STATUS_FLAGGED
        _log_audit(
            conn,
            memory_id,
            ACTION_FLAG_CONFLICT,
            reason=f"contradiction_penalty_conf_{new_conf:.2f}_{reason}".strip("_"),
            old_value=item.status,
            new_value=new_status,
            evidence_id=evidence_id or "",
            timestamp=now,
        )

    conn.execute(
        """UPDATE memory
           SET confidence = ?, contradiction_count = ?, last_seen = ?, status = ?
           WHERE memory_id = ?""",
        (new_conf, new_contradictions, now, new_status, memory_id),
    )
    conn.commit()
    conn.close()

    item.confidence = new_conf
    item.contradiction_count = new_contradictions
    item.last_seen = now
    item.status = new_status
    return item


def forget_memory(
    memory_id: str,
    reason: str = "user_requested",
    db_path: Path | str | None = None,
) -> bool:
    """Mark a memory as forgotten."""
    conn = connect_memory(db_path)
    row = conn.execute("SELECT * FROM memory WHERE memory_id = ?", (memory_id,)).fetchone()
    if row is None:
        conn.close()
        return False

    item = MemoryItem.from_row(row)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "UPDATE memory SET status = ?, last_seen = ? WHERE memory_id = ?",
        (STATUS_FORGOTTEN, now, memory_id),
    )
    _log_audit(
        conn,
        memory_id,
        ACTION_FORGET,
        reason=reason,
        old_value=item.statement,
        new_value="",
        timestamp=now,
    )
    conn.commit()
    conn.close()
    return True


def get_memory(memory_id: str, db_path: Path | str | None = None) -> MemoryItem | None:
    """Fetch single memory item by ID."""
    conn = connect_memory(db_path)
    row = conn.execute("SELECT * FROM memory WHERE memory_id = ?", (memory_id,)).fetchone()
    conn.close()
    return MemoryItem.from_row(row) if row else None


def list_active_memories(
    scope: str | None = None,
    category: str | None = None,
    include_drafts: bool = False,
    db_path: Path | str | None = None,
    limit: int = 100,
) -> list[MemoryItem]:
    """List active memories (verified, or drafts if requested) ordered by is_core DESC, confidence DESC."""
    conn = connect_memory(db_path)
    conditions = []
    params: list[Any] = []

    if include_drafts:
        conditions.append("status IN ('verified', 'draft')")
    else:
        conditions.append("status = 'verified'")

    if scope is not None:
        conditions.append("scope = ?")
        params.append(scope)

    if category is not None:
        conditions.append("category = ?")
        params.append(category)

    where_clause = f"WHERE {' AND '.join(conditions)}"
    query = f"""
        SELECT * FROM memory
        {where_clause}
        ORDER BY is_core DESC, confidence DESC, last_seen DESC
        LIMIT ?
    """
    params.append(max(1, min(int(limit), 500)))
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [MemoryItem.from_row(r) for r in rows]


def list_conflicts(db_path: Path | str | None = None) -> list[MemoryItem]:
    """List all flagged or contradicted memories."""
    conn = connect_memory(db_path)
    rows = conn.execute(
        """SELECT * FROM memory
           WHERE status = 'flagged' OR (contradiction_count > 0 AND status = 'verified')
           ORDER BY contradiction_count DESC, last_seen DESC"""
    ).fetchall()
    conn.close()
    return [MemoryItem.from_row(r) for r in rows]


def get_audit_history(memory_id: str, db_path: Path | str | None = None) -> list[MemoryAuditEntry]:
    """Retrieve complete audit history for a memory item."""
    conn = connect_memory(db_path)
    rows = conn.execute(
        """SELECT * FROM memory_audit
           WHERE memory_id = ?
           ORDER BY timestamp ASC""",
        (memory_id,),
    ).fetchall()
    conn.close()
    return [MemoryAuditEntry.from_row(r) for r in rows]

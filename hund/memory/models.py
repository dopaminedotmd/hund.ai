"""Data models and constants for user and project memory."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Optional

# Scopes
SCOPE_USER_GLOBAL = "user_global"
SCOPE_PROJECT_PREFIX = "project:"
SCOPE_DOMAIN_PREFIX = "domain:"

# Categories
CATEGORY_STABLE_PREFERENCE = "stable_preference"
CATEGORY_WORKING_PREFERENCE = "working_preference"
CATEGORY_BIOGRAPHICAL_FACT = "biographical_fact"
CATEGORY_WORKFLOW_HABIT = "workflow_habit"
CATEGORY_PROJECT_STATE = "current_project_state"
CATEGORY_TEMPORARY_CONTEXT = "temporary_context"
CATEGORY_CORE = "core"

# Statuses
STATUS_DRAFT = "draft"
STATUS_VERIFIED = "verified"
STATUS_SUPERSEDED = "superseded"
STATUS_DEPRECATED = "deprecated"
STATUS_FLAGGED = "flagged"
STATUS_FORGOTTEN = "forgotten"

# Audit actions
ACTION_CREATE = "create"
ACTION_PROMOTE = "promote"
ACTION_SUPERSEDE = "supersede"
ACTION_FLAG_CONFLICT = "flag_conflict"
ACTION_DECAY = "decay"
ACTION_FORGET = "forget"
ACTION_EVICT = "evict"


@dataclass
class MemoryItem:
    memory_id: str
    scope: str
    category: str
    statement: str
    status: str
    confidence: float
    source_type: str
    first_seen: str
    last_seen: str
    support_count: int = 1
    contradiction_count: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    expires_at: Optional[str] = None
    is_core: bool = False

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> MemoryItem:
        try:
            ev_ids = json.loads(row[11]) if row[11] else []
        except Exception:
            ev_ids = []

        return cls(
            memory_id=row[0],
            scope=row[1],
            category=row[2],
            statement=row[3],
            status=row[4],
            confidence=float(row[5] or 0.0),
            source_type=row[6],
            first_seen=row[7],
            last_seen=row[8],
            support_count=int(row[9] or 1),
            contradiction_count=int(row[10] or 0),
            evidence_ids=ev_ids,
            supersedes=row[12],
            superseded_by=row[13],
            expires_at=row[14],
            is_core=bool(row[15]),
        )

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.memory_id,
            self.scope,
            self.category,
            self.statement,
            self.status,
            self.confidence,
            self.source_type,
            self.first_seen,
            self.last_seen,
            self.support_count,
            self.contradiction_count,
            json.dumps(self.evidence_ids),
            self.supersedes,
            self.superseded_by,
            self.expires_at,
            1 if self.is_core else 0,
        )


@dataclass
class MemoryAuditEntry:
    audit_id: str
    memory_id: str
    action: str
    reason: str
    old_value: str
    new_value: str
    evidence_id: str
    timestamp: str

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> MemoryAuditEntry:
        return cls(
            audit_id=row[0],
            memory_id=row[1],
            action=row[2],
            reason=row[3] or "",
            old_value=row[4] or "",
            new_value=row[5] or "",
            evidence_id=row[6] or "",
            timestamp=row[7],
        )

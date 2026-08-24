"""Data models and constants for knowledge units and lifecycle auditing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Optional

STATUS_CANDIDATE = "candidate"
STATUS_SUPPORTED = "supported"
STATUS_VALIDATED = "validated"
STATUS_DEPRECATED = "deprecated"
STATUS_RETRACTED = "retracted"
VALID_STATUSES = {
    STATUS_CANDIDATE,
    STATUS_SUPPORTED,
    STATUS_VALIDATED,
    STATUS_DEPRECATED,
    STATUS_RETRACTED,
}

KIND_RULE = "rule"
KIND_NEGATIVE_RULE = "negative_rule"
KIND_CONSTRAINT = "constraint"
KIND_EXCEPTION = "exception"
VALID_KINDS = {KIND_RULE, KIND_NEGATIVE_RULE, KIND_CONSTRAINT, KIND_EXCEPTION}

ACTION_CREATE = "create"
ACTION_PROMOTE = "promote"
ACTION_DEGRADE = "degrade"
ACTION_DEPRECATE = "deprecate"
ACTION_RETRACT = "retract"
ACTION_REVISE = "revise"
VALID_ACTIONS = {
    ACTION_CREATE,
    ACTION_PROMOTE,
    ACTION_DEGRADE,
    ACTION_DEPRECATE,
    ACTION_RETRACT,
    ACTION_REVISE,
}


@dataclass
class KnowledgeUnit:
    id: str
    domain: str
    statement: str
    trigger: str = ""
    kind: str = KIND_RULE
    status: str = STATUS_CANDIDATE
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    deps: dict[str, str] = field(default_factory=dict)
    supersedes: Optional[str] = None
    support_count: int = 0
    contradiction_count: int = 0
    created_at: str = ""
    last_used: Optional[str] = None
    last_validated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> KnowledgeUnit:
        """Map SQLite row to KnowledgeUnit."""
        # row: (id, domain, statement, trigger, kind, status, confidence, evidence_ids, deps, supersedes, support_count, contradiction_count, created_at, last_used, last_validated_at)
        ev_ids = json.loads(row[7] or "[]") if isinstance(row[7], str) else (row[7] or [])
        deps_dict = json.loads(row[8] or "{}") if isinstance(row[8], str) else (row[8] or {})
        return cls(
            id=row[0],
            domain=row[1],
            statement=row[2],
            trigger=row[3] or "",
            kind=row[4],
            status=row[5],
            confidence=float(row[6]),
            evidence_ids=ev_ids,
            deps=deps_dict,
            supersedes=row[9],
            support_count=int(row[10] or 0),
            contradiction_count=int(row[11] or 0),
            created_at=row[12],
            last_used=row[13],
            last_validated_at=row[14],
        )


@dataclass
class KnowledgeAuditEntry:
    audit_id: str
    unit_id: str
    action: str
    old_status: Optional[str]
    new_status: str
    reason: str
    evidence_id: Optional[str]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> KnowledgeAuditEntry:
        # row: (audit_id, unit_id, action, old_status, new_status, reason, evidence_id, timestamp)
        return cls(
            audit_id=row[0],
            unit_id=row[1],
            action=row[2],
            old_status=row[3],
            new_status=row[4],
            reason=row[5] or "",
            evidence_id=row[6],
            timestamp=row[7],
        )

"""Immutable, provider-neutral specialization contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

CONTRACT_VERSION = 1


class LifecycleState(StrEnum):
    ACTIVE = "active"
    PARKED = "parked"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"
    DEPRECATED = "deprecated"


class ConflictState(StrEnum):
    CLEAR = "clear"
    WEAK_FIT = "weak_fit"
    SCOPE_CONFLICT = "scope_conflict"
    INSTRUCTION_CONFLICT = "instruction_conflict"
    SAFETY_CONFLICT = "safety_conflict"
    INVALID_MANIFEST = "invalid_manifest"
    QUARANTINED = "quarantined"


class ProposalReviewState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DEFERRED = "deferred"
    DECLINED = "declined"
    NEVER_SUGGEST = "never_suggest"


class ProposalDecision(StrEnum):
    APPROVE = "approve"
    DEFER = "defer"
    DECLINE = "decline"
    NEVER_SUGGEST = "never_suggest"


class ValidationIssue(ValueError):
    """Safe, stable validation failure exposed at a contract boundary."""

    def __init__(self, code: str, message: str = "Invalid specialization contract") -> None:
        super().__init__(message)
        self.code = code


def _enum_value(value: StrEnum) -> str:
    return value.value


@dataclass(frozen=True)
class SpecializationMembership:
    capability_id: str
    kind: str
    condition: str | None
    order: int
    scope: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "condition": self.condition,
            "order": self.order,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class SpecializationManifest:
    specialization_id: str
    profile_id: str
    manifest_version: int
    display_name: str
    purpose: str
    outcomes: tuple[str, ...]
    membership: tuple[SpecializationMembership, ...]
    lifecycle: LifecycleState
    conflict: ConflictState
    provenance_refs: tuple[str, ...]
    previous_version: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": "SpecializationManifest",
            "contract_version": CONTRACT_VERSION,
            "specialization_id": self.specialization_id,
            "profile_id": self.profile_id,
            "manifest_version": self.manifest_version,
            "display_name": self.display_name,
            "purpose": self.purpose,
            "outcomes": list(self.outcomes),
            "membership": [item.to_dict() for item in self.membership],
            "lifecycle": _enum_value(self.lifecycle),
            "conflict": _enum_value(self.conflict),
            "provenance_refs": list(self.provenance_refs),
            "previous_version": self.previous_version,
        }


@dataclass(frozen=True)
class SpecializationProposal:
    proposal_id: str
    manifest: SpecializationManifest
    reason: str
    evidence_summary: str
    review_state: ProposalReviewState
    decision: ProposalDecision | None
    expires_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": "SpecializationProposal",
            "contract_version": CONTRACT_VERSION,
            "proposal_id": self.proposal_id,
            "manifest": self.manifest.to_dict(),
            "reason": self.reason,
            "evidence_summary": self.evidence_summary,
            "review_state": self.review_state.value,
            "decision": self.decision.value if self.decision else None,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class Profile:
    profile_id: str
    display_name: str
    scope: str
    active_specialization_ids: tuple[str, ...]
    snapshot_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": "Profile",
            "contract_version": CONTRACT_VERSION,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "scope": self.scope,
            "active_specialization_ids": list(self.active_specialization_ids),
            "snapshot_version": self.snapshot_version,
        }


@dataclass(frozen=True)
class SpecializationSnapshot:
    profile: Profile
    active: tuple[SpecializationManifest, ...]
    parked: tuple[SpecializationManifest, ...]
    degraded: tuple[SpecializationManifest, ...]
    member_references: tuple[SpecializationMembership, ...]
    progression_available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": "SpecializationSnapshot",
            "contract_version": CONTRACT_VERSION,
            "profile": self.profile.to_dict(),
            "active": [item.to_dict() for item in self.active],
            "parked": [item.to_dict() for item in self.parked],
            "degraded": [item.to_dict() for item in self.degraded],
            "member_references": [item.to_dict() for item in self.member_references],
            "progression_available": self.progression_available,
        }


def _require_version(data: Mapping[str, Any]) -> None:
    if data.get("contract_version") != CONTRACT_VERSION:
        raise ValidationIssue("unsupported_contract_version")


def _membership(data: Mapping[str, Any]) -> SpecializationMembership:
    return SpecializationMembership(
        capability_id=str(data["capability_id"]),
        kind=str(data["kind"]),
        condition=data.get("condition"),
        order=int(data["order"]),
        scope=str(data["scope"]),
    )


def _manifest(data: Mapping[str, Any]) -> SpecializationManifest:
    return SpecializationManifest(
        specialization_id=str(data["specialization_id"]),
        profile_id=str(data["profile_id"]),
        manifest_version=int(data["manifest_version"]),
        display_name=str(data["display_name"]),
        purpose=str(data["purpose"]),
        outcomes=tuple(str(item) for item in data["outcomes"]),
        membership=tuple(_membership(item) for item in data["membership"]),
        lifecycle=LifecycleState(data["lifecycle"]),
        conflict=ConflictState(data["conflict"]),
        provenance_refs=tuple(str(item) for item in data["provenance_refs"]),
        previous_version=data.get("previous_version"),
    )


def _profile(data: Mapping[str, Any]) -> Profile:
    return Profile(
        profile_id=str(data["profile_id"]),
        display_name=str(data["display_name"]),
        scope=str(data["scope"]),
        active_specialization_ids=tuple(str(item) for item in data["active_specialization_ids"]),
        snapshot_version=int(data["snapshot_version"]),
    )


def parse_contract(data: Mapping[str, Any]) -> SpecializationSnapshot:
    """Parse a snapshot while keeping version errors stable and safe."""
    _require_version(data)
    if data.get("contract_type") != "SpecializationSnapshot":
        raise ValidationIssue("invalid_contract_type")
    try:
        return SpecializationSnapshot(
            profile=_profile(data["profile"]),
            active=tuple(_manifest(item) for item in data["active"]),
            parked=tuple(_manifest(item) for item in data["parked"]),
            degraded=tuple(_manifest(item) for item in data["degraded"]),
            member_references=tuple(_membership(item) for item in data["member_references"]),
            progression_available=bool(data["progression_available"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationIssue("invalid_contract") from error

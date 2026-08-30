"""Explicit proposal decisions, reassignment and rollback operations."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .contracts import (
    ConflictState,
    ProposalDecision,
    ProposalReviewState,
    SpecializationMembership,
    SpecializationProposal,
    SpecializationSnapshot,
)


class ProposalConflict(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def apply_proposal_decision(
    proposals: Iterable[SpecializationProposal],
    proposal_id: str,
    decision: ProposalDecision,
) -> tuple[SpecializationProposal, ...]:
    """Apply one explicit decision and leave every other proposal untouched."""
    items = tuple(proposals)
    if not any(item.proposal_id == proposal_id for item in items):
        raise ProposalConflict("proposal_not_found")
    if decision is ProposalDecision.APPROVE:
        selected = next(item for item in items if item.proposal_id == proposal_id)
        if selected.manifest.conflict not in {ConflictState.CLEAR, ConflictState.WEAK_FIT}:
            raise ProposalConflict("proposal_activation_blocked")
    state = {
        ProposalDecision.APPROVE: ProposalReviewState.APPROVED,
        ProposalDecision.DEFER: ProposalReviewState.DEFERRED,
        ProposalDecision.DECLINE: ProposalReviewState.DECLINED,
        ProposalDecision.NEVER_SUGGEST: ProposalReviewState.NEVER_SUGGEST,
    }[decision]
    return tuple(
        replace(item, review_state=state, decision=decision) if item.proposal_id == proposal_id else item
        for item in items
    )


def reassign_membership(
    snapshot: SpecializationSnapshot,
    specialization_id: str,
    membership: tuple[SpecializationMembership, ...],
    *,
    expected_snapshot_version: int,
) -> SpecializationSnapshot:
    if snapshot.profile.snapshot_version != expected_snapshot_version:
        raise ProposalConflict("snapshot_version_conflict")
    selected = next((item for item in snapshot.active if item.specialization_id == specialization_id), None)
    if selected is None:
        raise ProposalConflict("specialization_not_found")
    updated = replace(
        selected,
        membership=membership,
        manifest_version=selected.manifest_version + 1,
        previous_version=selected.manifest_version,
    )
    active = tuple(updated if item.specialization_id == specialization_id else item for item in snapshot.active)
    profile = replace(snapshot.profile, snapshot_version=expected_snapshot_version + 1)
    references = tuple(member for item in active for member in item.membership)
    return replace(snapshot, profile=profile, active=active, member_references=references)


def rollback_snapshot(
    current: SpecializationSnapshot,
    previous: SpecializationSnapshot,
    *,
    expected_snapshot_version: int,
) -> SpecializationSnapshot:
    if current.profile.snapshot_version != expected_snapshot_version:
        raise ProposalConflict("snapshot_version_conflict")
    return previous

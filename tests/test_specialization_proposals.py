import pytest

from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    ProposalDecision,
    ProposalReviewState,
    SpecializationManifest,
    SpecializationMembership,
    SpecializationProposal,
    SpecializationSnapshot,
)
from hund.specializations.proposals import (
    ProposalConflict,
    apply_proposal_decision,
    reassign_membership,
    rollback_snapshot,
)


def manifest(identifier: str = "spec.backend", conflict: ConflictState = ConflictState.CLEAR) -> SpecializationManifest:
    return SpecializationManifest(
        identifier, "profile.default", 1, "Backend", "Purpose", (),
        (SpecializationMembership("cap.python", "core", None, 0, "project:hund"),),
        LifecycleState.ACTIVE, conflict, (), None,
    )


def proposal(identifier: str, conflict: ConflictState = ConflictState.CLEAR) -> SpecializationProposal:
    return SpecializationProposal(
        identifier, manifest(f"spec.{identifier}", conflict), "user requested", "safe summary",
        ProposalReviewState.PENDING, None, "2099-01-01T00:00:00Z",
    )


def snapshot(item: SpecializationManifest = None) -> SpecializationSnapshot:
    item = item or manifest()
    profile = Profile("profile.default", "Default", "project:hund", (item.specialization_id,), 2)
    return SpecializationSnapshot(profile, (item,), (), (), item.membership, False)


def test_approval_changes_only_the_selected_proposal() -> None:
    proposals = (proposal("one"), proposal("two"))

    updated = apply_proposal_decision(proposals, "one", ProposalDecision.APPROVE)

    assert updated[0].review_state is ProposalReviewState.APPROVED
    assert updated[0].decision is ProposalDecision.APPROVE
    assert updated[1] == proposals[1]


def test_hard_conflict_cannot_be_approved() -> None:
    with pytest.raises(ProposalConflict) as error:
        apply_proposal_decision((proposal("blocked", ConflictState.SAFETY_CONFLICT),), "blocked", ProposalDecision.APPROVE)

    assert error.value.code == "proposal_activation_blocked"


def test_reassignment_requires_version_and_preserves_manifest_metadata() -> None:
    original = snapshot()
    replacement = (SpecializationMembership("cap.other", "conditional", "when safe", 1, "project:hund"),)

    updated = reassign_membership(original, "spec.backend", replacement, expected_snapshot_version=2)

    assert updated.active[0].membership == replacement
    assert updated.active[0].purpose == original.active[0].purpose
    assert updated.profile.snapshot_version == 3
    with pytest.raises(ProposalConflict):
        reassign_membership(original, "spec.backend", replacement, expected_snapshot_version=1)


def test_rollback_restores_previous_snapshot_without_touching_atomic_state() -> None:
    previous = snapshot()
    current = reassign_membership(previous, "spec.backend", (), expected_snapshot_version=2)

    restored = rollback_snapshot(current, previous, expected_snapshot_version=3)

    assert restored == previous

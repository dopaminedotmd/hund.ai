"""Typed contracts for the additive specialization runtime."""

from .contracts import (
    CONTRACT_VERSION,
    ConflictState,
    LifecycleState,
    Profile,
    ProposalDecision,
    ProposalReviewState,
    SpecializationManifest,
    SpecializationMembership,
    SpecializationProposal,
    SpecializationSnapshot,
    ValidationIssue,
    parse_contract,
)
from .validation import MAX_ACTIVE_SPECIALIZATIONS, ValidationResult, validate_manifest
from .migrations import MigrationResult, migrate_state
from .routing import MAX_ROUTING_MATCHES, RouteMatch, route
from .proposals import ProposalConflict, apply_proposal_decision, reassign_membership, rollback_snapshot
from .progression import ProgressionAvailability, SpecializationProgression, project_progression
from .snapshots import (
    CanonicalSpecializationSnapshot,
    build_canonical_snapshot,
    snapshot_for_detail,
    snapshot_for_progress,
    snapshot_for_skills,
    snapshot_for_startup,
)
from .flags import SpecializationFeatureFlags, feature_flags_from_mapping
from .ui import SpecializationDisplay, to_public_display

__all__ = [
    "CONTRACT_VERSION",
    "ConflictState",
    "LifecycleState",
    "Profile",
    "ProposalDecision",
    "ProposalReviewState",
    "SpecializationManifest",
    "SpecializationMembership",
    "SpecializationProposal",
    "SpecializationSnapshot",
    "ValidationIssue",
    "parse_contract",
    "MAX_ACTIVE_SPECIALIZATIONS",
    "ValidationResult",
    "validate_manifest",
    "MigrationResult",
    "migrate_state",
    "MAX_ROUTING_MATCHES",
    "RouteMatch",
    "route",
    "ProposalConflict",
    "apply_proposal_decision",
    "reassign_membership",
    "rollback_snapshot",
    "ProgressionAvailability",
    "SpecializationProgression",
    "project_progression",
    "CanonicalSpecializationSnapshot",
    "build_canonical_snapshot",
    "snapshot_for_detail",
    "snapshot_for_progress",
    "snapshot_for_skills",
    "snapshot_for_startup",
    "SpecializationFeatureFlags",
    "feature_flags_from_mapping",
    "SpecializationDisplay",
    "to_public_display",
]

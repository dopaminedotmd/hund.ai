"""Pure validation for specialization manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Iterable

from .contracts import ConflictState, LifecycleState, Profile, SpecializationManifest, ValidationIssue

MAX_ACTIVE_SPECIALIZATIONS = 6
HARD_CONFLICTS = frozenset({
    ConflictState.SCOPE_CONFLICT,
    ConflictState.INSTRUCTION_CONFLICT,
    ConflictState.SAFETY_CONFLICT,
    ConflictState.INVALID_MANIFEST,
    ConflictState.QUARANTINED,
})


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    conflict: ConflictState
    issues: tuple[ValidationIssue, ...] = ()


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _issue(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, message)


def _first_conflict(issues: Iterable[ValidationIssue]) -> ConflictState:
    codes = {issue.code for issue in issues}
    if "scope_conflict" in codes:
        return ConflictState.SCOPE_CONFLICT
    if "instruction_conflict" in codes:
        return ConflictState.INSTRUCTION_CONFLICT
    if "safety_conflict" in codes:
        return ConflictState.SAFETY_CONFLICT
    if "quarantined" in codes:
        return ConflictState.QUARANTINED
    if "weak_fit" in codes:
        return ConflictState.WEAK_FIT
    if codes:
        return ConflictState.INVALID_MANIFEST
    return ConflictState.CLEAR


def validate_manifest(
    manifest: SpecializationManifest,
    profile_scope: str | Profile,
    canonical_skills: Mapping[str, Any],
    *,
    builtin_capability_ids: Iterable[str] = (),
    active_specialization_count: int = 0,
) -> ValidationResult:
    """Validate activation eligibility without mutating any runtime state."""
    scope = profile_scope.scope if isinstance(profile_scope, Profile) else profile_scope
    issues: list[ValidationIssue] = []

    if manifest.profile_id and isinstance(profile_scope, Profile) and manifest.profile_id != profile_scope.profile_id:
        issues.append(_issue("profile_identity_conflict", "Manifest belongs to another profile"))

    if manifest.lifecycle is not LifecycleState.ACTIVE:
        issues.append(_issue("invalid_lifecycle", "Only active manifests may be reviewed for activation"))
    if manifest.conflict in HARD_CONFLICTS:
        issues.append(_issue(manifest.conflict.value, "Manifest conflict blocks activation"))
    elif manifest.conflict is ConflictState.WEAK_FIT:
        issues.append(_issue("weak_fit", "Manifest requires a visible manual-organization warning"))

    capability_ids = [item.capability_id for item in manifest.membership]
    if len(capability_ids) != len(set(capability_ids)):
        issues.append(_issue("duplicate_member_identity", "A capability may appear only once in a manifest"))

    builtin_ids = set(builtin_capability_ids)
    for item in manifest.membership:
        if item.capability_id in builtin_ids:
            issues.append(_issue("builtin_collision", "Builtin capabilities cannot be shadowed"))
            continue
        if item.scope != scope:
            issues.append(_issue("scope_conflict", "Membership scope must match the active profile scope"))
            continue
        record = canonical_skills.get(item.capability_id)
        if record is None:
            issues.append(_issue("missing_canonical_member", "Referenced canonical capability does not exist"))
            continue
        if _value(record, "scope") != scope:
            issues.append(_issue("scope_conflict", "Canonical capability scope does not match the profile"))
        if _value(record, "lifecycle_state") not in {"active", "proven"} or _value(record, "vault_state") != "equipped":
            issues.append(_issue("ineligible_member", "Only equipped active capabilities are routable"))

    if active_specialization_count >= MAX_ACTIVE_SPECIALIZATIONS:
        issues.append(_issue("specialization_capacity_exceeded", "A profile may activate at most six specializations"))

    conflict = _first_conflict(issues)
    hard_failure = any(issue.code not in {"weak_fit"} for issue in issues)
    return ValidationResult(valid=not hard_failure, conflict=conflict, issues=tuple(issues))

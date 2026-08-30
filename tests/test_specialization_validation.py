from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
)
from hund.specializations.validation import validate_manifest


def manifest(*members: SpecializationMembership, conflict: ConflictState = ConflictState.CLEAR):
    return SpecializationManifest(
        specialization_id="spec.backend",
        profile_id="profile.default",
        manifest_version=1,
        display_name="Backend",
        purpose="Build backend systems",
        outcomes=("ship reliable code",),
        membership=members,
        lifecycle=LifecycleState.ACTIVE,
        conflict=conflict,
        provenance_refs=("user",),
        previous_version=None,
    )


def member(capability_id: str = "cap.python", scope: str = "project:hund"):
    return SpecializationMembership(capability_id, "core", None, 0, scope)


def profile(active_count: int = 0, scope: str = "project:hund") -> Profile:
    return Profile("profile.default", "Default", scope, tuple(f"spec.{i}" for i in range(active_count)), 1)


def test_validates_canonical_members_and_preserves_many_to_many_identity() -> None:
    result = validate_manifest(
        manifest(member()),
        profile_scope="project:hund",
        canonical_skills={"cap.python": {"scope": "project:hund", "lifecycle_state": "active", "vault_state": "equipped"}},
    )

    assert result.valid is True
    assert result.conflict is ConflictState.CLEAR


def test_rejects_missing_member() -> None:
    result = validate_manifest(manifest(member("cap.missing")), "project:hund", {})

    assert result.valid is False
    assert result.issues[0].code == "missing_canonical_member"


def test_rejects_scope_leakage() -> None:
    result = validate_manifest(
        manifest(member(scope="global")),
        "project:hund",
        {"cap.python": {"scope": "global", "lifecycle_state": "active", "vault_state": "equipped"}},
    )

    assert result.conflict is ConflictState.SCOPE_CONFLICT
    assert result.valid is False


def test_rejects_parked_members_and_builtin_collisions() -> None:
    parked = validate_manifest(
        manifest(member()), "project:hund",
        {"cap.python": {"scope": "project:hund", "lifecycle_state": "active", "vault_state": "parked"}},
    )
    builtin = validate_manifest(
        manifest(member("builtin.shell")), "project:hund",
        {"builtin.shell": {"scope": "global", "lifecycle_state": "active", "vault_state": "equipped"}},
        builtin_capability_ids={"builtin.shell"},
    )

    assert parked.issues[0].code == "ineligible_member"
    assert builtin.issues[0].code == "builtin_collision"


def test_rejects_hard_conflict_and_seventh_active_specialization() -> None:
    conflict = validate_manifest(manifest(member(), conflict=ConflictState.SAFETY_CONFLICT), "project:hund", {
        "cap.python": {"scope": "project:hund", "lifecycle_state": "active", "vault_state": "equipped"}
    })
    capacity = validate_manifest(manifest(member()), "project:hund", {
        "cap.python": {"scope": "project:hund", "lifecycle_state": "active", "vault_state": "equipped"}
    }, active_specialization_count=6)

    assert conflict.issues[0].code == "safety_conflict"
    assert capacity.issues[0].code == "specialization_capacity_exceeded"

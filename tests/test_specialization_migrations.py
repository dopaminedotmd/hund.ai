from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
)
from hund.specializations.migrations import migrate_state


def profile() -> Profile:
    return Profile("profile.default", "Default", "project:hund", (), 0)


def manifest(scope: str = "project:hund") -> SpecializationManifest:
    return SpecializationManifest(
        "spec.backend", "profile.default", 1, "Backend", "Build backend systems",
        ("ship reliable code",),
        (SpecializationMembership("cap.python", "core", None, 0, scope),),
        LifecycleState.ACTIVE, ConflictState.CLEAR, ("user",), None,
    )


def skills() -> dict:
    return {"cap.python": {"scope": "project:hund", "lifecycle_state": "active", "vault_state": "equipped"}}


def test_absent_or_legacy_state_does_not_cluster_atomic_skills() -> None:
    atomic_state = b'{"entries":[{"capability_id":"cap.python"}]}'
    result = migrate_state(
        {"schema_version": 2, "atomic_skill_state": {"entries": ["cap.python"]}},
        declared_profiles=(profile(),),
        declared_manifests=(),
        canonical_skills=skills(),
        atomic_state_bytes=atomic_state,
    )

    assert result.snapshot.active == ()
    assert result.imported_ids == ()
    assert result.atomic_state_before == atomic_state
    assert result.atomic_state_after == atomic_state


def test_only_explicit_valid_manifests_are_imported() -> None:
    result = migrate_state(
        None,
        declared_profiles=(profile(),),
        declared_manifests=(manifest(),),
        canonical_skills=skills(),
        atomic_state_bytes=b"before",
    )

    assert result.snapshot.active[0].specialization_id == "spec.backend"
    assert result.imported_ids == ("spec.backend",)
    assert result.changed is True


def test_invalid_manifest_is_quarantined_without_partial_activation() -> None:
    result = migrate_state(
        None,
        declared_profiles=(profile(),),
        declared_manifests=(manifest(scope="global"),),
        canonical_skills=skills(),
        atomic_state_bytes=b"before",
    )

    assert result.snapshot.active == ()
    assert result.quarantined == ("scope_conflict",)
    assert result.atomic_state_after == b"before"


def test_unsupported_state_preserves_previous_snapshot() -> None:
    previous = migrate_state(
        None,
        declared_profiles=(profile(),),
        declared_manifests=(manifest(),),
        canonical_skills=skills(),
        atomic_state_bytes=b"before",
    ).snapshot
    result = migrate_state(
        {"schema_version": 999},
        declared_profiles=(profile(),),
        declared_manifests=(manifest(scope="global"),),
        canonical_skills=skills(),
        atomic_state_bytes=b"before",
        previous_snapshot=previous,
    )

    assert result.snapshot == previous
    assert result.quarantined == ("unsupported_schema_version",)
    assert result.changed is False

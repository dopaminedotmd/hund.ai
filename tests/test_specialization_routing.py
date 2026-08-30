from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
    SpecializationSnapshot,
)
from hund.specializations.routing import route


def manifest(identifier: str, capability_id: str = "cap.shared", scope: str = "project:hund", *, lifecycle=LifecycleState.ACTIVE, conflict=ConflictState.CLEAR):
    return SpecializationManifest(
        identifier, "profile.default", 1, identifier, "Purpose", (),
        (SpecializationMembership(capability_id, "core", None, 0, scope),),
        lifecycle, conflict, (), None,
    )


def snapshot(manifests: tuple[SpecializationManifest, ...]) -> SpecializationSnapshot:
    profile = Profile("profile.default", "Default", "project:hund", tuple(item.specialization_id for item in manifests), 1)
    return SpecializationSnapshot(profile, manifests, (), (), tuple(member for item in manifests for member in item.membership), False)


def skills(scope: str = "project:hund") -> dict:
    return {"cap.shared": {"scope": scope, "lifecycle_state": "active", "vault_state": "equipped"}}


def test_routes_shared_canonical_skill_to_multiple_specializations() -> None:
    result = route(snapshot((manifest("spec.alpha"), manifest("spec.beta"))), ("cap.shared",), "project:hund", skills())

    assert [item.specialization_id for item in result] == ["spec.alpha", "spec.beta"]
    assert result[0].capability_ids == ("cap.shared",)


def test_scope_and_lifecycle_gates_skip_ineligible_specializations() -> None:
    current = manifest("spec.current")
    wrong_scope = manifest("spec.wrong", scope="global")
    parked = manifest("spec.parked", lifecycle=LifecycleState.PARKED)
    conflicted = manifest("spec.conflicted", conflict=ConflictState.SAFETY_CONFLICT)

    result = route(snapshot((current, wrong_scope, parked, conflicted)), ("cap.shared",), "project:hund", skills())

    assert [item.specialization_id for item in result] == ["spec.current"]


def test_routing_is_deterministic_and_bounded() -> None:
    manifests = tuple(manifest(f"spec.{index:02d}") for index in range(8))

    result = route(snapshot(manifests), ("cap.shared",), "project:hund", skills(), max_matches=5)

    assert len(result) == 5
    assert [item.specialization_id for item in result] == [f"spec.{index:02d}" for index in range(5)]

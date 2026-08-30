from dataclasses import FrozenInstanceError

import pytest

from hund.specializations.contracts import (
    CONTRACT_VERSION,
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
    SpecializationSnapshot,
    ValidationIssue,
    parse_contract,
)


def test_profile_and_manifest_round_trip_with_many_to_many_membership() -> None:
    membership = SpecializationMembership(
        capability_id="capability.python",
        kind="core",
        condition=None,
        order=0,
        scope="project:hund",
    )
    manifest = SpecializationManifest(
        specialization_id="spec.backend",
        profile_id="profile.default",
        manifest_version=1,
        display_name="Backend",
        purpose="Build backend systems",
        outcomes=("ship reliable code",),
        membership=(membership,),
        lifecycle=LifecycleState.ACTIVE,
        conflict=ConflictState.CLEAR,
        provenance_refs=("user",),
        previous_version=None,
    )
    profile = Profile(
        profile_id="profile.default",
        display_name="Default",
        scope="project:hund",
        active_specialization_ids=(manifest.specialization_id,),
        snapshot_version=3,
    )
    snapshot = SpecializationSnapshot(
        profile=profile,
        active=(manifest,),
        parked=(),
        degraded=(),
        member_references=(membership,),
        progression_available=False,
    )

    restored = parse_contract(snapshot.to_dict())

    assert restored == snapshot
    assert restored.active[0].membership[0].capability_id == "capability.python"


def test_contracts_are_immutable() -> None:
    profile = Profile("p", "Default", "global", (), 0)

    with pytest.raises(FrozenInstanceError):
        profile.display_name = "changed"


def test_unsupported_contract_version_has_stable_issue() -> None:
    with pytest.raises(ValidationIssue) as error:
        parse_contract({"contract_type": "Profile", "contract_version": 999})

    assert error.value.code == "unsupported_contract_version"


def test_contract_version_is_explicit() -> None:
    assert CONTRACT_VERSION == 1

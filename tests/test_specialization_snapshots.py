from dataclasses import FrozenInstanceError

import pytest

from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
)
from hund.specializations.progression import ProgressionAvailability, SpecializationProgression
from hund.specializations.snapshots import (
    build_canonical_snapshot,
    snapshot_for_detail,
    snapshot_for_progress,
    snapshot_for_skills,
    snapshot_for_startup,
)


def manifest(identifier: str) -> SpecializationManifest:
    return SpecializationManifest(
        identifier, "profile.default", 1, identifier, "Purpose", (),
        (SpecializationMembership("cap.python", "core", None, 0, "global"),),
        LifecycleState.ACTIVE, ConflictState.CLEAR, (), None,
    )


def test_all_surfaces_share_one_canonical_snapshot() -> None:
    profile = Profile("profile.default", "Default", "global", ("spec.backend",), 7)
    progression = SpecializationProgression("spec.backend", ProgressionAvailability.UNAVAILABLE, 0, 0.0, None)
    canonical = build_canonical_snapshot(profile, (manifest("spec.backend"),), (progression,))

    surfaces = (
        snapshot_for_startup(canonical), snapshot_for_skills(canonical),
        snapshot_for_progress(canonical), snapshot_for_detail(canonical),
    )

    assert all(surface is canonical for surface in surfaces)
    assert all(surface.snapshot_version == 7 for surface in surfaces)


def test_snapshot_order_is_deterministic_and_immutable() -> None:
    profile = Profile("profile.default", "Default", "global", ("spec.z", "spec.a"), 1)
    canonical = build_canonical_snapshot(profile, (manifest("spec.z"), manifest("spec.a")), ())

    assert [item.specialization_id for item in canonical.active] == ["spec.a", "spec.z"]
    with pytest.raises(FrozenInstanceError):
        canonical.active = ()

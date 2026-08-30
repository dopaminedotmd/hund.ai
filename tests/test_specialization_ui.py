from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
)
from hund.specializations.progression import ProgressionAvailability, SpecializationProgression
from hund.specializations.snapshots import build_canonical_snapshot
from hund.specializations.ui import SpecializationDisplay, to_public_display


def test_public_projection_excludes_internal_ids_and_raw_evidence() -> None:
    manifest = SpecializationManifest(
        "internal-spec-123", "profile.default", 1, "Backend", "Build systems", (),
        (SpecializationMembership("internal-cap-456", "core", None, 0, "global"),),
        LifecycleState.ACTIVE, ConflictState.CLEAR, ("internal-event-789",), None,
    )
    snapshot = build_canonical_snapshot(
        Profile("profile.default", "Default", "global", ("internal-spec-123",), 3),
        (manifest,),
        (SpecializationProgression("internal-spec-123", ProgressionAvailability.UNAVAILABLE, 0, 0.0, None),),
    )

    display = to_public_display(snapshot)

    assert display == (SpecializationDisplay("Backend", "Build systems", "active", 1, "unavailable"),)
    assert "internal-spec-123" not in repr(display)
    assert "internal-cap-456" not in repr(display)
    assert "internal-event-789" not in repr(display)

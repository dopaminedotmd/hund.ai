from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
)
from hund.specializations.progression import ProgressionAvailability, project_progression


def manifest() -> SpecializationManifest:
    return SpecializationManifest(
        "spec.backend", "profile.default", 1, "Backend", "Purpose", ("ship", "maintain"),
        (SpecializationMembership("cap.python", "core", None, 0, "global"),),
        LifecycleState.ACTIVE, ConflictState.CLEAR, (), None,
    )


def test_progression_is_unavailable_without_verified_evidence() -> None:
    result = project_progression(manifest(), evidence=(), expected_workflow_ids=("ship", "maintain"))

    assert result.availability is ProgressionAvailability.UNAVAILABLE
    assert result.verified_outcomes == 0
    assert result.workflow_coverage == 0.0
    assert result.health is None


def test_progression_uses_verified_outcomes_workflow_coverage_and_health() -> None:
    evidence = (
        {"verified": True, "outcome_id": "ship", "workflow_id": "release", "health": 0.8},
        {"verified": True, "outcome_id": "maintain", "workflow_id": "operate", "health": 1.0},
        {"verified": False, "outcome_id": "ignored", "workflow_id": "release", "health": 0.0},
    )

    result = project_progression(manifest(), evidence=evidence, expected_workflow_ids=("release", "operate", "observe"))

    assert result.availability is ProgressionAvailability.AVAILABLE
    assert result.verified_outcomes == 2
    assert result.workflow_coverage == 2 / 3
    assert result.health == 0.9


def test_progression_does_not_sum_atomic_skill_xp() -> None:
    evidence = ({"verified": True, "outcome_id": "ship", "workflow_id": "release", "health": 0.5, "personal_skill_xp": 999999},)

    result = project_progression(manifest(), evidence=evidence, expected_workflow_ids=("release", "operate"))

    assert result.verified_outcomes == 1
    assert result.health == 0.5

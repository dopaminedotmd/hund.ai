"""Evidence-gated specialization progression, independent from atomic XP."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from .contracts import SpecializationManifest


class ProgressionAvailability(StrEnum):
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"


@dataclass(frozen=True)
class SpecializationProgression:
    specialization_id: str
    availability: ProgressionAvailability
    verified_outcomes: int
    workflow_coverage: float
    health: float | None


def project_progression(
    manifest: SpecializationManifest,
    *,
    evidence: Iterable[Mapping[str, Any]],
    expected_workflow_ids: Iterable[str],
) -> SpecializationProgression:
    """Project verified outcomes without reading atomic skill XP or artifacts."""
    expected = set(expected_workflow_ids)
    outcome_ids: set[str] = set()
    workflow_ids: set[str] = set()
    health_values: list[float] = []
    for record in evidence:
        if record.get("specialization_id", manifest.specialization_id) != manifest.specialization_id:
            continue
        if record.get("verified") is not True:
            continue
        outcome_id = record.get("outcome_id")
        workflow_id = record.get("workflow_id")
        if isinstance(outcome_id, str) and outcome_id:
            outcome_ids.add(outcome_id)
        if isinstance(workflow_id, str) and workflow_id in expected:
            workflow_ids.add(workflow_id)
        health = record.get("health")
        if isinstance(health, (int, float)) and not isinstance(health, bool):
            health_values.append(max(0.0, min(1.0, float(health))))

    if not outcome_ids and not health_values:
        return SpecializationProgression(manifest.specialization_id, ProgressionAvailability.UNAVAILABLE, 0, 0.0, None)
    coverage = len(workflow_ids) / len(expected) if expected else 0.0
    health = sum(health_values) / len(health_values) if health_values else None
    return SpecializationProgression(
        manifest.specialization_id,
        ProgressionAvailability.AVAILABLE,
        len(outcome_ids),
        coverage,
        health,
    )

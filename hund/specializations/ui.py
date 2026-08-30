"""Safe public projections for specialization UI consumers."""

from __future__ import annotations

from dataclasses import dataclass

from .progression import ProgressionAvailability
from .snapshots import CanonicalSpecializationSnapshot


@dataclass(frozen=True)
class SpecializationDisplay:
    display_name: str
    purpose: str
    state: str
    member_count: int
    progression_status: str


def to_public_display(snapshot: CanonicalSpecializationSnapshot) -> tuple[SpecializationDisplay, ...]:
    progression = {item.specialization_id: item for item in snapshot.progression}
    manifests = snapshot.active + snapshot.parked + snapshot.degraded
    displays: list[SpecializationDisplay] = []
    for item in manifests:
        projected = progression.get(item.specialization_id)
        status = projected.availability.value if projected else ProgressionAvailability.UNAVAILABLE.value
        displays.append(SpecializationDisplay(item.display_name, item.purpose, item.lifecycle.value, len(item.membership), status))
    return tuple(displays)

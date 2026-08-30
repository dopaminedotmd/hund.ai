"""Canonical read-only specialization snapshot shared by UI surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import Profile, SpecializationManifest, SpecializationMembership
from .progression import SpecializationProgression


@dataclass(frozen=True)
class CanonicalSpecializationSnapshot:
    profile: Profile
    active: tuple[SpecializationManifest, ...]
    parked: tuple[SpecializationManifest, ...]
    degraded: tuple[SpecializationManifest, ...]
    member_references: tuple[SpecializationMembership, ...]
    progression: tuple[SpecializationProgression, ...]

    @property
    def snapshot_version(self) -> int:
        return self.profile.snapshot_version


def build_canonical_snapshot(
    profile: Profile,
    active: tuple[SpecializationManifest, ...],
    progression: tuple[SpecializationProgression, ...],
    *,
    parked: tuple[SpecializationManifest, ...] = (),
    degraded: tuple[SpecializationManifest, ...] = (),
) -> CanonicalSpecializationSnapshot:
    active_sorted = tuple(sorted(active, key=lambda item: item.specialization_id))
    parked_sorted = tuple(sorted(parked, key=lambda item: item.specialization_id))
    degraded_sorted = tuple(sorted(degraded, key=lambda item: item.specialization_id))
    all_manifests = active_sorted + parked_sorted + degraded_sorted
    references = tuple(
        member
        for item in all_manifests
        for member in sorted(item.membership, key=lambda value: (value.capability_id, value.order))
    )
    return CanonicalSpecializationSnapshot(
        profile=profile,
        active=active_sorted,
        parked=parked_sorted,
        degraded=degraded_sorted,
        member_references=references,
        progression=tuple(sorted(progression, key=lambda item: item.specialization_id)),
    )


def snapshot_for_startup(snapshot: CanonicalSpecializationSnapshot) -> CanonicalSpecializationSnapshot:
    return snapshot


def snapshot_for_skills(snapshot: CanonicalSpecializationSnapshot) -> CanonicalSpecializationSnapshot:
    return snapshot


def snapshot_for_progress(snapshot: CanonicalSpecializationSnapshot) -> CanonicalSpecializationSnapshot:
    return snapshot


def snapshot_for_detail(snapshot: CanonicalSpecializationSnapshot) -> CanonicalSpecializationSnapshot:
    return snapshot

"""Deterministic, opt-in migration into specialization state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from .contracts import Profile, SpecializationManifest, SpecializationSnapshot
from .validation import validate_manifest

CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MigrationResult:
    snapshot: SpecializationSnapshot
    imported_ids: tuple[str, ...]
    quarantined: tuple[str, ...]
    atomic_state_before: bytes
    atomic_state_after: bytes
    changed: bool


def migrate_state(
    raw_state: Mapping[str, Any] | None,
    *,
    declared_profiles: Iterable[Profile],
    declared_manifests: Iterable[SpecializationManifest],
    canonical_skills: Mapping[str, Any],
    atomic_state_bytes: bytes,
    previous_snapshot: SpecializationSnapshot | None = None,
) -> MigrationResult:
    """Build a candidate snapshot without writing or inferring any state."""
    profiles = tuple(sorted(declared_profiles, key=lambda item: item.profile_id))
    base = previous_snapshot or _empty_snapshot(profiles[0] if profiles else None)
    quarantined: list[str] = []

    if raw_state is not None:
        schema_version = raw_state.get("schema_version")
        if schema_version not in (None, 2, CURRENT_SCHEMA_VERSION):
            return MigrationResult(base, (), ("unsupported_schema_version",), atomic_state_bytes, atomic_state_bytes, False)
        if schema_version == CURRENT_SCHEMA_VERSION:
            return MigrationResult(base, (), (), atomic_state_bytes, atomic_state_bytes, False)

    profile_by_id = {item.profile_id: item for item in profiles}
    imported: list[SpecializationManifest] = []
    seen_ids: set[str] = set()
    for item in sorted(declared_manifests, key=lambda value: value.specialization_id):
        if item.specialization_id in seen_ids:
            quarantined.append("duplicate_specialization_identity")
            continue
        seen_ids.add(item.specialization_id)
        profile = profile_by_id.get(item.profile_id)
        if profile is None:
            quarantined.append("profile_identity_conflict")
            continue
        result = validate_manifest(item, profile, canonical_skills)
        if not result.valid:
            quarantined.append(result.issues[0].code if result.issues else "invalid_manifest")
            continue
        imported.append(item)

    if not imported:
        return MigrationResult(base, (), tuple(quarantined), atomic_state_bytes, atomic_state_bytes, False)

    chosen_profile = profile_by_id[imported[0].profile_id]
    active_ids = tuple(item.specialization_id for item in imported)
    next_profile = replace(chosen_profile, active_specialization_ids=active_ids)
    snapshot = SpecializationSnapshot(
        profile=next_profile,
        active=tuple(imported),
        parked=(),
        degraded=(),
        member_references=tuple(member for item in imported for member in item.membership),
        progression_available=False,
    )
    return MigrationResult(
        snapshot,
        active_ids,
        tuple(quarantined),
        atomic_state_bytes,
        atomic_state_bytes,
        True,
    )


def _empty_snapshot(profile: Profile | None) -> SpecializationSnapshot:
    profile = profile or Profile("default", "Default", "global", (), 0)
    return SpecializationSnapshot(profile, (), (), (), (), False)

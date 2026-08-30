"""Read-only, bounded specialization routing over a canonical snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Iterable

from .contracts import ConflictState, SpecializationSnapshot

MAX_ROUTING_MATCHES = 5


@dataclass(frozen=True)
class RouteMatch:
    specialization_id: str
    capability_ids: tuple[str, ...]


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def route(
    snapshot: SpecializationSnapshot,
    requested_capability_ids: Iterable[str],
    workspace_scope: str,
    canonical_skills: Mapping[str, Any],
    *,
    max_matches: int = MAX_ROUTING_MATCHES,
) -> tuple[RouteMatch, ...]:
    """Select eligible specializations without activating or mutating state."""
    if max_matches <= 0 or snapshot.profile.scope != workspace_scope:
        return ()
    requested = set(requested_capability_ids)
    matches: list[RouteMatch] = []
    for specialization in sorted(snapshot.active, key=lambda item: item.specialization_id):
        if specialization.lifecycle.value != "active" or specialization.conflict is not ConflictState.CLEAR:
            continue
        eligible: list[str] = []
        for member in sorted(specialization.membership, key=lambda item: (item.order, item.capability_id)):
            if member.capability_id not in requested or member.scope != workspace_scope:
                continue
            skill = canonical_skills.get(member.capability_id)
            if skill is None:
                continue
            if _value(skill, "scope") != workspace_scope:
                continue
            if _value(skill, "lifecycle_state") not in {"active", "proven"}:
                continue
            if _value(skill, "vault_state") != "equipped":
                continue
            eligible.append(member.capability_id)
        if eligible:
            matches.append(RouteMatch(specialization.specialization_id, tuple(eligible)))
        if len(matches) >= max_matches:
            break
    return tuple(matches)

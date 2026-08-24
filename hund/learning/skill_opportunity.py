"""Deterministic detection of reusable procedural knowledge."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domains.xp import (
    EVENT_CROSS_SESSION_REUSE,
    EVENT_SAME_TASK_REUSE,
    list_xp_events,
)
from ..knowledge import db as knowledge_db
from ..knowledge.models import STATUS_VALIDATED


@dataclass(frozen=True)
class SkillOpportunity:
    domain: str
    intent: str
    knowledge_ids: tuple[str, ...]
    observed_reuse: int
    cross_session_reuse: int
    procedurality: float


def _matches_intent(unit, intent: str) -> bool:
    declared = str(unit.deps.get("intent", "")).casefold()
    trigger = unit.trigger.casefold()
    wanted = intent.casefold()
    return declared == wanted or trigger == wanted or (not declared and not trigger)


def detect_skill_opportunities(
    domain: str,
    intent: str,
    db_path: Path | str | None = None,
) -> SkillOpportunity | None:
    """Return an opportunity only after two validated units and unique reuses."""
    units = [
        unit for unit in knowledge_db.list_units(
            domain=domain, status=STATUS_VALIDATED, db_path=db_path
        )
        if _matches_intent(unit, intent)
    ]
    if len(units) < 2:
        return None
    unit_ids = {unit.id for unit in units}
    reuse_types = {EVENT_SAME_TASK_REUSE, EVENT_CROSS_SESSION_REUSE}
    events = [
        event for event in list_xp_events(domain=domain, db_path=db_path)
        if event["unit_id"] in unit_ids and event["event_type"] in reuse_types
    ]
    unique_events = {event["event_id"]: event for event in events}
    if len(unique_events) < 2:
        return None
    sessions = {
        event["session_id"] for event in unique_events.values()
        if event["session_id"]
    }
    procedural_terms = ("first", "then", "run", "check", "verify", "before", "after")
    procedural = sum(
        any(term in unit.statement.casefold() for term in procedural_terms)
        for unit in units
    ) / len(units)
    return SkillOpportunity(
        domain=domain,
        intent=intent,
        knowledge_ids=tuple(sorted(unit_ids)),
        observed_reuse=len(unique_events),
        cross_session_reuse=len(sessions),
        procedurality=round(procedural, 3),
    )


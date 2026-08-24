"""Pure SkillFactory: knowledge in, declarative draft out, never writes."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from ..knowledge.models import KnowledgeUnit
from ..learning.skill_opportunity import SkillOpportunity
from .model import BANNED_ACTIONS, KnowledgeRef, Skill


@dataclass(frozen=True)
class SkillDraft:
    action: str
    skill: Skill


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-")
    return (value or "learned-skill")[:64]


def _minor_bump(version: str) -> str:
    try:
        major, minor, _patch = (int(part) for part in version.split(".", 2))
        return f"{major}.{minor + 1}.0"
    except (TypeError, ValueError):
        return "1.1.0"


class SkillFactory:
    """Generate CREATE/UPDATE drafts without storage authority."""

    def build(
        self,
        opportunity: SkillOpportunity,
        knowledge_units: Iterable[KnowledgeUnit],
        existing_skills: Iterable[Skill] = (),
    ) -> SkillDraft:
        units_by_id = {unit.id: unit for unit in knowledge_units}
        units = [
            units_by_id[unit_id] for unit_id in opportunity.knowledge_ids
            if unit_id in units_by_id
        ]
        if len(units) != len(opportunity.knowledge_ids):
            raise ValueError("opportunity references unavailable knowledge")
        capability = f"{opportunity.domain}/{_slug(opportunity.intent)}"
        existing = next(
            (skill for skill in existing_skills if skill.capability_id == capability),
            None,
        )
        action = "UPDATE" if existing else "CREATE"
        version = _minor_bump(existing.version) if existing else "1.0.0"
        name = existing.name if existing else _slug(capability.replace("/", "-"))
        tools = tuple(sorted({
            tool for unit in units
            for tool in str(unit.deps.get("required_tools", "")).split(",")
            if tool.strip()
        }))
        skill = Skill(
            schema_version=1,
            name=name,
            domain=opportunity.domain,
            status="draft",
            triggers=(opportunity.intent,),
            when_to_use=f"When the task intent is {opportunity.intent}.",
            steps=tuple(unit.statement for unit in units),
            required_tools=tools,
            forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
            safety_level="confirm" if tools else "read_only",
            verification=("Verify every produced result against current workspace state.",),
            lifecycle_state="draft",
            vault_state="vaulted",
            version=version,
            capability_id=capability,
            source_knowledge_refs=tuple(
                KnowledgeRef(
                    unit.id,
                    unit.last_validated_at or unit.created_at or "unknown",
                )
                for unit in units
            ),
            created_from_event_ids=tuple(
                sorted({event_id for unit in units for event_id in unit.evidence_ids})
            ),
        )
        return SkillDraft(action, skill)


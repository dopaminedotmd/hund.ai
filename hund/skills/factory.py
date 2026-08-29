"""Pure SkillFactory: knowledge in, declarative draft out, never writes."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from ..knowledge.models import KnowledgeUnit
from ..learning.skill_opportunity import SkillOpportunity
from .authoring import LocalSkillProposal, ResearchSkillProposal, SkillDraft
from .model import BANNED_ACTIONS, KnowledgeRef, Skill
from .scope import ScopeResolution


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-")
    return (value or "learned-skill")[:64]


def _minor_bump(version: str) -> str:
    try:
        major, minor, _patch = (int(part) for part in version.split(".", 2))
        return f"{major}.{minor + 1}.0"
    except (TypeError, ValueError):
        return "1.1.0"


def _sanitize_triggers(triggers: Iterable[str]) -> tuple[str, ...]:
    sanitized: list[str] = []
    for t in triggers:
        cleaned = re.sub(r"[!?:;,.\"]+", "", str(t)).strip().casefold()
        if cleaned and cleaned not in sanitized:
            sanitized.append(cleaned)
    return tuple(sanitized)


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
            triggers=_sanitize_triggers((opportunity.intent,)),
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
            personal_skill_xp=0,
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
        return SkillDraft(action=action, skill=skill, metadata={"source": "knowledge_opportunity"})

    def build_from_proposal(
        self,
        proposal: LocalSkillProposal | ResearchSkillProposal,
        resolution: ScopeResolution,
        existing_skills: Iterable[Skill] = (),
    ) -> SkillDraft:
        """Pure factory construction of SkillDraft from authoring proposal and scope resolution."""
        action = resolution.action or "CREATE"
        target_name = _slug(resolution.target_name or proposal.name)
        target_scope = resolution.target_scope or proposal.scope or "global"
        capability_id = resolution.capability_id or f"{proposal.domain}/{target_name}"

        existing = resolution.existing_skill
        if existing is None:
            existing = next(
                (s for s in existing_skills if s.name == target_name and s.scope == target_scope),
                None,
            )

        if existing is not None:
            action = "UPDATE"
            version = _minor_bump(existing.version)
        else:
            action = "CREATE"
            version = "1.0.0"

        tools = tuple(sorted(set(proposal.required_tools)))
        raw_triggers = proposal.triggers if proposal.triggers else (proposal.intent,)
        triggers = _sanitize_triggers(raw_triggers)
        steps = tuple(proposal.steps)
        verification = tuple(proposal.verification) if proposal.verification else (
            "Verify produced output against requirements.",
        )
        examples = tuple(proposal.examples) if proposal.examples else ()

        source_refs = getattr(proposal, "source_refs", ())
        source_knowledge_refs = tuple(
            KnowledgeRef(
                knowledge_id=ref.url_or_origin,
                version=ref.retrieved_at,
            )
            for ref in source_refs
        )

        skill = Skill(
            schema_version=1,
            name=target_name,
            domain=proposal.domain or "general",
            status="draft",
            triggers=triggers,
            when_to_use=proposal.when_to_use,
            steps=steps,
            required_tools=tools,
            forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
            safety_level="confirm" if tools else "read_only",
            verification=verification,
            examples=examples,
            lifecycle_state="draft",
            vault_state="vaulted",
            version=version,
            capability_id=capability_id,
            scope=target_scope,
            personal_skill_xp=0,
            source_knowledge_refs=source_knowledge_refs,
        )

        metadata = {
            "action": action,
            "scope": target_scope,
            "workspace_key": resolution.workspace_key or "global",
            "is_shadowing": resolution.is_shadowing,
            "source_count": len(source_refs),
            "reason": resolution.reason,
        }
        return SkillDraft(action=action, skill=skill, metadata=metadata)

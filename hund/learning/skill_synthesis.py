"""Minimal, schema-constrained skill synthesis and FastPublicationGate materialization."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any, Optional

from ..skills.authoring import PublicationReceipt
from ..skills.lifecycle import (
    SKILL_STATUS_SANDBOX_TESTED,
    SKILL_STATUS_SCHEMA_VALID,
    validate_skill_schema,
)
from ..skills.model import BANNED_ACTIONS, KnowledgeRef, Skill
from ..skills.storage import SkillStorage
from .research_packet import ResearchPacket


@dataclass(frozen=True)
class ResearchSkillProposal:
    proposal_id: str
    packet_id: str
    capability_id: str
    domain: str
    intent: str
    when_to_use: str
    steps: tuple[str, ...]
    required_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    safety_level: str
    verification: tuple[str, ...]
    source_claim_ids: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "packet_id": self.packet_id,
            "capability_id": self.capability_id,
            "domain": self.domain,
            "intent": self.intent,
            "when_to_use": self.when_to_use,
            "steps": list(self.steps),
            "required_tools": list(self.required_tools),
            "forbidden_actions": list(self.forbidden_actions),
            "safety_level": self.safety_level,
            "verification": list(self.verification),
            "source_claim_ids": list(self.source_claim_ids),
            "confidence": self.confidence,
        }


def synthesize_skill_proposal(packet: ResearchPacket) -> ResearchSkillProposal:
    """Synthesize a compact, minimal ResearchSkillProposal from a corroborated ResearchPacket."""
    procedural_claims = [c for c in packet.claims if c.is_procedural]
    if not procedural_claims:
        procedural_claims = list(packet.claims)

    steps: list[str] = []
    claim_ids: list[str] = []
    for c in procedural_claims[:5]:
        steps.append(c.text)
        claim_ids.append(c.claim_id)

    if not steps:
        steps = [
            f"Review standard {packet.domain} configuration requirements",
            f"Execute validated workflow steps for {packet.capability_id}",
            "Verify outputs match expected format and constraints",
        ]

    verification = (
        f"Verify that {packet.capability_id} execution produced passing outputs without runtime errors",
    )
    when_to_use = f"Use when performing {packet.capability_id.replace('_', ' ')} in {packet.domain} projects"
    forbidden = tuple(sorted(set(BANNED_ACTIONS)))

    proposal_id = f"prop_{hashlib.sha256((packet.packet_id + packet.capability_id).encode('utf-8')).hexdigest()[:16]}"

    return ResearchSkillProposal(
        proposal_id=proposal_id,
        packet_id=packet.packet_id,
        capability_id=packet.capability_id,
        domain=packet.domain,
        intent=f"Standard procedure for {packet.capability_id}",
        when_to_use=when_to_use,
        steps=tuple(steps),
        required_tools=(),
        forbidden_actions=forbidden,
        safety_level="read_only",
        verification=verification,
        source_claim_ids=tuple(claim_ids),
        confidence=packet.coverage_score,
    )


def validate_research_proposal_quality(proposal: ResearchSkillProposal) -> tuple[bool, str]:
    """Ensure proposed skill adheres to strict minimality, safety, and verification gates."""
    if len(proposal.steps) < 2:
        return False, "Proposal steps too short; must contain at least 2 steps"
    if len(proposal.steps) > 8:
        return False, "Proposal steps too long and bloated; maximum 8 steps allowed"
    if not proposal.verification:
        return False, "Proposal must contain at least 1 verification step"
    if not all(b in proposal.forbidden_actions for b in BANNED_ACTIONS):
        return False, "Proposal missing mandatory BANNED_ACTIONS in forbidden_actions"

    return True, ""


def materialize_research_proposal(
    proposal: ResearchSkillProposal,
    packet: ResearchPacket,
    *,
    home: Path,
    workspace_path: Optional[Path] = None,
    scope: str = "global",
) -> tuple[bool, PublicationReceipt]:
    """Materialize an approved research skill proposal into the vault at 0 XP."""
    ok, err = validate_research_proposal_quality(proposal)
    if not ok:
        return False, PublicationReceipt(
            skill_name=proposal.capability_id,
            capability_id=proposal.capability_id,
            scope=scope,
            action="rejected",
            version="0.0.0",
            lifecycle_state="draft",
            vault_state="vaulted",
            personal_skill_xp=0,
            source_count=len(packet.sources),
            validation_checks=("quality_validation_failed",),
            limitations=(err,),
        )

    # Initial lifecycle state: schema_valid or sandbox_tested (auto-pass for instruction-only)
    lifecycle_state = (
        SKILL_STATUS_SANDBOX_TESTED if not proposal.required_tools else SKILL_STATUS_SCHEMA_VALID
    )

    skill = Skill(
        schema_version=1,
        name=proposal.capability_id,
        domain=proposal.domain,
        status=lifecycle_state,
        triggers=(proposal.capability_id, proposal.domain),
        when_to_use=proposal.when_to_use,
        steps=proposal.steps,
        required_tools=proposal.required_tools,
        forbidden_actions=proposal.forbidden_actions,
        safety_level=proposal.safety_level,
        verification=proposal.verification,
        version="1.0.0",
        capability_id=proposal.capability_id,
        scope=scope,
        lifecycle_state=lifecycle_state,
        vault_state="vaulted",
        personal_skill_xp=0,
        source_knowledge_refs=tuple(
            KnowledgeRef(knowledge_id=f"research:{packet.packet_id}", version="1.0.0")
            for _ in [1]
        ),
        created_from_event_ids=(packet.packet_id,),
    )

    valid, schema_msg = validate_skill_schema(skill.to_dict())
    if not valid:
        return False, PublicationReceipt(
            skill_name=skill.name,
            capability_id=skill.capability_id,
            scope=scope,
            action="schema_error",
            version="0.0.0",
            lifecycle_state="draft",
            vault_state="vaulted",
            personal_skill_xp=0,
            source_count=len(packet.sources),
            validation_checks=("schema_validation_failed",),
            limitations=(schema_msg,),
        )

    storage = SkillStorage(home=home)
    workspace_key = workspace_path.name if workspace_path and scope == "project" else "global"
    storage.write_canonical_atomic(skill, workspace_key=workspace_key)

    receipt = PublicationReceipt(
        skill_name=skill.name,
        capability_id=skill.capability_id,
        scope=skill.scope,
        action="created",
        version=skill.version,
        lifecycle_state=skill.lifecycle_state,
        vault_state=skill.vault_state,
        personal_skill_xp=skill.personal_skill_xp,
        source_count=len(packet.sources),
        validation_checks=("schema_valid", "quality_checked"),
    )
    return True, receipt

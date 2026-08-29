from datetime import datetime, timezone
from pathlib import Path
import pytest

from hund.learning.research_packet import (
    ResearchClaim,
    ResearchPacket,
    ResearchSourceRecord,
    SourceTier,
)
from hund.learning.skill_synthesis import (
    ResearchSkillProposal,
    materialize_research_proposal,
    synthesize_skill_proposal,
    validate_research_proposal_quality,
)
from hund.skills.loader import load_domain_skills
from hund.skills.model import BANNED_ACTIONS, Skill


def _sample_packet() -> ResearchPacket:
    return ResearchPacket(
        packet_id="packet_log_01",
        need_id="need_log_01",
        capability_id="python_logging",
        domain="python",
        canonical_queries=("python logging best practices",),
        sources=(
            ResearchSourceRecord(
                url="https://docs.python.org/3/howto/logging.html",
                domain="docs.python.org",
                title="Logging HOWTO",
                retrieved_at="2026-08-26T12:00:00Z",
                source_tier=SourceTier.TIER_1_OFFICIAL.value,
                content_hash="abc1",
            ),
            ResearchSourceRecord(
                url="https://realpython.com/python-logging/",
                domain="realpython.com",
                title="Python Logging Guide",
                retrieved_at="2026-08-26T12:00:00Z",
                source_tier=SourceTier.TIER_2_REPUTABLE.value,
                content_hash="abc2",
            ),
        ),
        claims=(
            ResearchClaim(
                claim_id="claim_01",
                text="Use logging.getLogger(__name__) for modular hierarchy",
                source_urls=("https://docs.python.org/3/howto/logging.html",),
                corroboration_count=2,
                confidence=0.9,
                freshness_timestamp="2026-08-26T12:00:00Z",
                is_procedural=True,
            ),
            ResearchClaim(
                claim_id="claim_02",
                text="Configure rotating file handlers with appropriate maxBytes and backupCount",
                source_urls=("https://realpython.com/python-logging/",),
                corroboration_count=2,
                confidence=0.9,
                freshness_timestamp="2026-08-26T12:00:00Z",
                is_procedural=True,
            ),
            ResearchClaim(
                claim_id="claim_03",
                text="Verify log output format and handler registration before starting workers",
                source_urls=("https://docs.python.org/3/howto/logging.html",),
                corroboration_count=2,
                confidence=0.9,
                freshness_timestamp="2026-08-26T12:00:00Z",
                is_procedural=True,
            ),
        ),
        conflicts=(),
        freshness_window_days=90,
        coverage_score=0.95,
        safety_scan_passed=True,
        status="corroborated",
    )


def test_synthesize_skill_proposal_from_research_packet():
    packet = _sample_packet()
    proposal = synthesize_skill_proposal(packet)

    assert isinstance(proposal, ResearchSkillProposal)
    assert proposal.capability_id == "python_logging"
    assert proposal.domain == "python"
    assert len(proposal.steps) >= 2
    assert len(proposal.steps) <= 6
    assert len(proposal.verification) >= 1
    assert all(b in proposal.forbidden_actions for b in BANNED_ACTIONS)


def test_validate_research_proposal_quality():
    valid = ResearchSkillProposal(
        proposal_id="prop_01",
        packet_id="packet_01",
        capability_id="python_logging",
        domain="python",
        intent="Configure rotating file logging for workers",
        when_to_use="When configuring structured logging for background jobs",
        steps=(
            "Create logger using logging.getLogger(__name__)",
            "Attach RotatingFileHandler with size limit and backupCount",
            "Set formatter with timestamp, level, and message",
        ),
        required_tools=("read_file",),
        forbidden_actions=tuple(BANNED_ACTIONS),
        safety_level="read_only",
        verification=("Check log file is created and contains structured entries",),
        source_claim_ids=("claim_01", "claim_02"),
        confidence=0.9,
    )
    ok, err = validate_research_proposal_quality(valid)
    assert ok is True
    assert err == ""

    # Quality check: reject if steps are empty or too long (> 8)
    bloated = ResearchSkillProposal(
        proposal_id="prop_bloated",
        packet_id="packet_01",
        capability_id="python_logging",
        domain="python",
        intent="Logging",
        when_to_use="When logging",
        steps=tuple(f"Step {i}" for i in range(12)),
        required_tools=(),
        forbidden_actions=tuple(BANNED_ACTIONS),
        safety_level="read_only",
        verification=("verify",),
        source_claim_ids=(),
        confidence=0.9,
    )
    ok, err = validate_research_proposal_quality(bloated)
    assert ok is False
    assert "steps" in err.lower()


def test_materialize_research_proposal_to_vault_at_zero_xp(tmp_path):
    home = tmp_path / "home"
    packet = _sample_packet()
    proposal = synthesize_skill_proposal(packet)

    ok, receipt = materialize_research_proposal(
        proposal,
        packet,
        home=home,
        scope="global",
    )

    assert ok is True
    assert receipt.personal_skill_xp == 0
    assert receipt.version == "1.0.0"
    assert receipt.vault_state == "vaulted"

    # Verify loaded skill
    loaded = load_domain_skills(home)
    matched = next((s for s in loaded if s.capability_id == "python_logging"), None)
    assert matched is not None
    assert matched.personal_skill_xp == 0
    assert matched.vault_state == "vaulted"
    assert matched.lifecycle_state in {"schema_valid", "sandbox_tested"}

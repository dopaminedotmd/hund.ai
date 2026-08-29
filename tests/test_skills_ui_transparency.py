from hund.skills.model import KnowledgeRef, Skill
from hund.skills.proficiency import SkillXPRecord
from hund.ui.skills_view import render_skill_transparency_summary


def test_render_skill_transparency_summary_displays_all_three_axes():
    skill = Skill(
        schema_version=1,
        name="python_logging",
        domain="python",
        status="active",
        triggers=("log",),
        when_to_use="When configuring python logging",
        steps=("Step 1", "Step 2"),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("verify",),
        version="1.0.0",
        lifecycle_state="active",
        vault_state="equipped",
        personal_skill_xp=0,
        source_knowledge_refs=(
            KnowledgeRef(knowledge_id="research:packet_123", version="1.0.0"),
        ),
    )
    rec = SkillXPRecord(
        capability_id="python_logging",
        domain="python",
        version_lineage="1.0.0",
        xp=0,
        level=1,
        tier="Novice",
        use_count=0,
        successful_use_count=0,
        failure_count=0,
        cross_session_success=0,
        last_used_at=None,
        health=1.0,
        updated_at="2026-08-26T12:00:00Z",
    )

    summary = render_skill_transparency_summary(skill, rec, source_count=2, research_status="corroborated")
    assert "python_logging" in summary
    # Axis 1: Research maturity
    assert "Research foundation" in summary or "corroborated" in summary.lower()
    assert "2 source" in summary
    # Axis 2: Lifecycle
    assert "Active" in summary
    # Axis 3: Personal proficiency
    assert "0 skill XP" in summary or "0 XP" in summary
    assert "Novice" in summary

    # Verify no UUID or hash leakage
    assert "packet_123" not in summary
    assert "uuid" not in summary.lower()

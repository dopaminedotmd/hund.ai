from datetime import datetime, timezone
from pathlib import Path
import pytest

from hund.learning.injection_guard import scan_untrusted_content
from hund.learning.receipts import format_public_receipt
from hund.learning.research_packet import ResearchPacketStore
from hund.learning.skill_research import perform_skill_research
from hund.learning.skill_synthesis import (
    materialize_research_proposal,
    synthesize_skill_proposal,
)
from hund.skills.drift import evaluate_skill_health_and_drift, quarantine_skill, rollback_skill_version
from hund.skills.lifecycle import (
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_PROVEN,
    evaluate_proven_promotion,
)
from hund.skills.loader import load_domain_skills
from hund.skills.proficiency import (
    EVENT_VERIFIED_CROSS_SESSION_REUSE,
    EVENT_VERIFIED_FIRST_USE,
    EVENT_VERIFIED_SAME_PROJECT_REUSE,
    SkillProficiencyStore,
    award_skill_xp,
    record_skill_run_outcome,
)
from hund.ui.skills_view import render_skill_transparency_summary


def test_phase6_complete_lifecycle_end_to_end(tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    db_path = home / "hund.db"

    # Step 1: Bounded privacy-safe research
    def mock_web_search(query_dict: dict) -> str:
        return (
            "https://docs.python.org/3/library/logging.html - Python Logging Library\n"
            "Use getLogger(__name__) and StreamHandler.\n"
            "https://realpython.com/python-logging/ - Python Logging Tutorial\n"
            "Configure logging with RotatingFileHandler and formatter.\n"
        )

    packet = perform_skill_research(
        need_id="need_log_e2e",
        capability_id="python_logging_e2e",
        domain="python",
        intent="Configure rotating file logging for background workers in C:\\Secret\\Path",
        search_fn=mock_web_search,
        db_path=db_path,
    )

    assert packet.status == "corroborated"
    assert packet.safety_scan_passed is True
    assert len(packet.sources) >= 2
    # Verify private path was not in canonical queries
    assert all("Secret" not in q and "C:\\" not in q for q in packet.canonical_queries)

    # Step 2: Minimal synthesis
    proposal = synthesize_skill_proposal(packet)
    assert proposal.capability_id == "python_logging_e2e"
    assert len(proposal.steps) >= 2
    assert len(proposal.steps) <= 6

    # Step 3: FastPublicationGate Materialization into Vault at 0 XP
    ok, receipt = materialize_research_proposal(
        proposal,
        packet,
        home=home,
        scope="global",
    )
    assert ok is True
    assert receipt.personal_skill_xp == 0
    assert receipt.vault_state == "vaulted"

    # Verify canonical skill file exists and loaded
    loaded = load_domain_skills(home)
    skill = next((s for s in loaded if s.name == "python_logging_e2e"), None)
    assert skill is not None
    assert skill.personal_skill_xp == 0
    assert skill.vault_state == "vaulted"

    # Step 4: First verified execution -> awards +2 XP
    delta, pub_receipt = award_skill_xp(
        capability_id="python_logging_e2e",
        domain="python",
        version="1.0.0",
        event_type=EVENT_VERIFIED_FIRST_USE,
        task_id="task_1",
        session_id="session_1",
        db_path=db_path,
    )
    assert delta == 2
    assert pub_receipt is not None
    formatted = format_public_receipt(pub_receipt)
    assert "python_logging_e2e +2 skill XP · verified first use" in formatted
    assert "uuid" not in formatted.lower()

    # Step 5: Accumulate verified runs and cross-session evidence
    record_skill_run_outcome("python_logging_e2e", success=True, db_path=db_path)
    for i in range(2, 7):
        award_skill_xp(
            capability_id="python_logging_e2e",
            domain="python",
            version="1.0.0",
            event_type=EVENT_VERIFIED_CROSS_SESSION_REUSE if i <= 3 else EVENT_VERIFIED_SAME_PROJECT_REUSE,
            task_id=f"task_{i}",
            session_id=f"session_{i}",
            db_path=db_path,
        )
        record_skill_run_outcome("python_logging_e2e", success=True, db_path=db_path)

    # Step 6: Verify Proven promotion
    prof_store = SkillProficiencyStore(db_path=db_path)
    # Manually record cross_session count for test
    conn = prof_store.db_path
    import sqlite3
    c = sqlite3.connect(conn)
    c.execute("UPDATE skill_xp SET cross_session_success = 3 WHERE capability_id = 'python_logging_e2e'")
    c.commit()
    c.close()

    prof_rec = prof_store.get_record("python_logging_e2e")
    assert prof_rec is not None
    assert prof_rec.use_count >= 5
    assert prof_rec.health == 1.0

    can_promote, reason = evaluate_proven_promotion(skill, prof_rec)
    assert can_promote is True

    # Step 7: 3-Axis UI Transparency
    ui_summary = render_skill_transparency_summary(
        skill,
        prof_rec,
        source_count=len(packet.sources),
        research_status=packet.status,
    )
    assert "Research foundation" in ui_summary
    assert "2 sources" in ui_summary
    assert "Proficiency:" in ui_summary
    assert "skill XP" in ui_summary

"""Tests for Domain XP v2 knowledge-driven progression and audit trail."""
from pathlib import Path
import pytest

from hund.domains import xp as domain_xp
from hund.knowledge import db as kdb
from hund.learning.commit_controller import CommitController
from hund.learning.evaluator import CandidateProposal


@pytest.fixture
def xp_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_xp.db"
    domain_xp._ensure_table(db_file)
    return db_file


def test_award_xp_deterministic_values(xp_db: Path) -> None:
    # 1. Discovery: +1 XP
    level, tier, leveled_up, amount = domain_xp.award_xp(
        domain="python",
        event_type=domain_xp.EVENT_DISCOVERY,
        unit_id="know_1",
        db_path=xp_db,
    )
    assert amount == 1
    assert level == 1
    assert tier == "Novice"
    assert not leveled_up

    # 2. Same-task reuse: +3 XP
    _, _, _, amount = domain_xp.award_xp(
        domain="python",
        event_type=domain_xp.EVENT_SAME_TASK_REUSE,
        unit_id="know_1",
        db_path=xp_db,
    )
    assert amount == 3

    # 3. Cross-session reuse: +5 XP
    _, _, _, amount = domain_xp.award_xp(
        domain="python",
        event_type=domain_xp.EVENT_CROSS_SESSION_REUSE,
        unit_id="know_1",
        db_path=xp_db,
    )
    assert amount == 5

    # 4. Validation promotion: +8 XP
    _, _, _, amount = domain_xp.award_xp(
        domain="python",
        event_type=domain_xp.EVENT_VALIDATION_PROMOTION,
        unit_id="know_1",
        db_path=xp_db,
    )
    assert amount == 8

    # Total XP should be 1 + 3 + 5 + 8 = 17
    data = domain_xp.get_xp("python", db_path=xp_db)
    assert data["xp"] == 17


def test_xp_events_audit_trail_and_recalculation(xp_db: Path) -> None:
    domain_xp.award_xp(
        domain="git",
        event_type=domain_xp.EVENT_DISCOVERY,
        unit_id="know_git1",
        session_id="sess_100",
        task_id="task_200",
        db_path=xp_db,
    )
    domain_xp.award_xp(
        domain="git",
        event_type=domain_xp.EVENT_CROSS_SESSION_REUSE,
        unit_id="know_git1",
        session_id="sess_101",
        db_path=xp_db,
    )

    # Check audit events
    events = domain_xp.list_xp_events(domain="git", db_path=xp_db)
    assert len(events) == 2
    assert events[0]["event_type"] == domain_xp.EVENT_DISCOVERY
    assert events[0]["xp_amount"] == 1
    assert events[0]["unit_id"] == "know_git1"
    assert events[0]["session_id"] == "sess_100"
    assert events[0]["xp_algorithm"] == "v2.0"
    assert events[1]["event_type"] == domain_xp.EVENT_CROSS_SESSION_REUSE
    assert events[1]["xp_amount"] == 5

    # Recalculate domain XP from raw event logs
    total = domain_xp.recalculate_domain_xp("git", db_path=xp_db)
    assert total == 6
    current = domain_xp.get_xp("git", db_path=xp_db)
    assert current["xp"] == 6


def test_commit_controller_xp_integration(tmp_path: Path) -> None:
    db_file = tmp_path / "knowledge_and_xp.db"
    kdb.ensure_knowledge_tables(db_file)
    domain_xp._ensure_table(db_file)

    controller = CommitController(db_path=db_file, home=tmp_path)

    # 1. Commit candidate -> triggers discovery (+1 XP)
    proposal = CandidateProposal(
        proposition="Always use pathlib.Path instead of os.path",
        scope={"type": "domain", "id": "python"},
        kind="rule",
        relation_to_existing="NEW",
        confidence=0.6,
        suggested_action="store_candidate",
    )
    unit_id, _ = controller.commit_candidate(proposal)
    assert unit_id != ""

    xp_data = domain_xp.get_xp("python", db_path=db_file)
    assert xp_data["xp"] == 1  # discovery award

    # 2. Reuse in same session (+3 XP)
    controller.record_usage_and_validate(unit_id, success=True, is_cross_session=False)
    xp_data = domain_xp.get_xp("python", db_path=db_file)
    assert xp_data["xp"] == 4  # 1 + 3

    # 3. Cross session reuse (+5 XP)
    controller.record_usage_and_validate(unit_id, success=True, is_cross_session=True)
    xp_data = domain_xp.get_xp("python", db_path=db_file)
    assert xp_data["xp"] == 9  # 4 + 5

    # 4. Success 3 & 4 -> triggers validation (+5 + 5 + 8 for promotion)
    controller.record_usage_and_validate(unit_id, success=True, is_cross_session=True)
    controller.record_usage_and_validate(unit_id, success=True, is_cross_session=True)

    xp_data = domain_xp.get_xp("python", db_path=db_file)
    # 1 (disc) + 3 (same) + 5 (cross) + 5 (cross) + 5 (cross) + 8 (promo) = 27 XP
    assert xp_data["xp"] == 27

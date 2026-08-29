from datetime import datetime, timezone
from pathlib import Path
import pytest

from hund.skills.proficiency import (
    EVENT_ACCEPTED_PERSONAL_REFINEMENT,
    EVENT_CROSS_PROJECT_GENERALIZATION,
    EVENT_VERIFIED_CROSS_SESSION_REUSE,
    EVENT_VERIFIED_FIRST_USE,
    EVENT_VERIFIED_SAME_PROJECT_REUSE,
    SkillProficiencyStore,
    award_skill_xp,
    record_skill_run_outcome,
)


def test_initial_skill_starts_at_zero_xp(tmp_path):
    db_path = tmp_path / "hund.db"
    store = SkillProficiencyStore(db_path)

    rec = store.get_or_create_record("python_logging", domain="python")
    assert rec.xp == 0
    assert rec.level == 1
    assert rec.tier == "Novice"
    assert rec.health == 1.0
    assert rec.use_count == 0


def test_award_skill_xp_idempotent(tmp_path):
    db_path = tmp_path / "hund.db"

    # First award: verified first use (+2 XP)
    delta, receipt = award_skill_xp(
        capability_id="python_logging",
        domain="python",
        version="1.0.0",
        event_type=EVENT_VERIFIED_FIRST_USE,
        task_id="task_001",
        session_id="session_001",
        db_path=db_path,
    )
    assert delta == 2
    assert receipt is not None
    assert receipt.delta_xp == 2
    assert receipt.new_total == 2
    assert "verified first use" in receipt.reason

    # Replaying same task_id + event_type must award 0 XP (idempotency)
    delta2, receipt2 = award_skill_xp(
        capability_id="python_logging",
        domain="python",
        version="1.0.0",
        event_type=EVENT_VERIFIED_FIRST_USE,
        task_id="task_001",
        session_id="session_001",
        db_path=db_path,
    )
    assert delta2 == 0
    assert receipt2 is None


def test_different_award_events_and_xp_weights(tmp_path):
    db_path = tmp_path / "hund.db"

    # 1. First use (+2)
    d1, _ = award_skill_xp("git_flow", "git", "1.0.0", EVENT_VERIFIED_FIRST_USE, "t1", "s1", db_path=db_path)
    assert d1 == 2

    # 2. Same project reuse (+2)
    d2, _ = award_skill_xp("git_flow", "git", "1.0.0", EVENT_VERIFIED_SAME_PROJECT_REUSE, "t2", "s1", db_path=db_path)
    assert d2 == 2

    # 3. Cross session reuse (+4)
    d3, _ = award_skill_xp("git_flow", "git", "1.0.0", EVENT_VERIFIED_CROSS_SESSION_REUSE, "t3", "s2", db_path=db_path)
    assert d3 == 4

    # 4. Accepted personal refinement (+3)
    d4, _ = award_skill_xp("git_flow", "git", "1.0.1", EVENT_ACCEPTED_PERSONAL_REFINEMENT, "t4", "s2", db_path=db_path)
    assert d4 == 3

    # 5. Cross project generalization (+6)
    d5, r5 = award_skill_xp("git_flow", "git", "1.0.1", EVENT_CROSS_PROJECT_GENERALIZATION, "t5", "s3", db_path=db_path)
    assert d5 == 6
    assert r5.new_total == (2 + 2 + 4 + 3 + 6)


def test_failure_outcome_degrades_health_without_subtracting_xp(tmp_path):
    db_path = tmp_path / "hund.db"
    store = SkillProficiencyStore(db_path)

    # Award 10 XP
    award_skill_xp("docker_deploy", "devops", "1.0.0", EVENT_VERIFIED_CROSS_SESSION_REUSE, "t1", "s1", db_path=db_path)
    award_skill_xp("docker_deploy", "devops", "1.0.0", EVENT_CROSS_PROJECT_GENERALIZATION, "t2", "s2", db_path=db_path)

    # Record 1 success
    record_skill_run_outcome("docker_deploy", success=True, db_path=db_path)
    # Record 1 failure
    record_skill_run_outcome("docker_deploy", success=False, error_msg="container crashed", db_path=db_path)

    rec = store.get_record("docker_deploy")
    assert rec is not None
    assert rec.xp == 10  # XP never subtracted
    assert rec.use_count == 2
    assert rec.successful_use_count == 1
    assert rec.failure_count == 1
    assert rec.health == 0.5

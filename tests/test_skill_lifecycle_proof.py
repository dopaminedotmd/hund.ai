from pathlib import Path
import pytest

from hund.skills.lifecycle import (
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_PROVEN,
    evaluate_proven_promotion,
)
from hund.skills.model import Skill
from hund.skills.proficiency import SkillXPRecord


def _sample_skill(lifecycle: str = SKILL_STATUS_ACTIVE, health: float = 1.0) -> Skill:
    return Skill(
        schema_version=1,
        name="docker_deploy",
        domain="devops",
        status=lifecycle,
        triggers=("docker",),
        when_to_use="When deploying docker containers",
        steps=("Step 1", "Step 2"),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("verify",),
        lifecycle_state=lifecycle,
        vault_state="equipped",
        health=health,
    )


def test_proven_promotion_requires_success_count_cross_session_and_health():
    skill = _sample_skill()

    # Case 1: Insufficient runs (e.g. 2 runs) -> cannot promote
    rec_insufficient = SkillXPRecord(
        capability_id="docker_deploy",
        domain="devops",
        version_lineage="1.0.0",
        xp=10,
        level=1,
        tier="Novice",
        use_count=2,
        successful_use_count=2,
        failure_count=0,
        cross_session_success=1,
        last_used_at="2026-08-26T12:00:00Z",
        health=1.0,
        updated_at="2026-08-26T12:00:00Z",
    )
    can_promote, reason = evaluate_proven_promotion(skill, rec_insufficient)
    assert can_promote is False
    assert "insufficient" in reason.lower() or "5" in reason

    # Case 2: 6 runs, 0 cross-session success -> cannot promote
    rec_no_cross = SkillXPRecord(
        capability_id="docker_deploy",
        domain="devops",
        version_lineage="1.0.0",
        xp=20,
        level=1,
        tier="Novice",
        use_count=6,
        successful_use_count=6,
        failure_count=0,
        cross_session_success=0,
        last_used_at="2026-08-26T12:00:00Z",
        health=1.0,
        updated_at="2026-08-26T12:00:00Z",
    )
    can_promote, reason = evaluate_proven_promotion(skill, rec_no_cross)
    assert can_promote is False
    assert "cross-session" in reason.lower()

    # Case 3: 10 runs, 7 successes, 3 failures, 3 cross-session, health = 0.70 (below 0.85) -> cannot promote
    rec_low_health = SkillXPRecord(
        capability_id="docker_deploy",
        domain="devops",
        version_lineage="1.0.0",
        xp=20,
        level=1,
        tier="Novice",
        use_count=10,
        successful_use_count=7,
        failure_count=3,
        cross_session_success=3,
        last_used_at="2026-08-26T12:00:00Z",
        health=0.70,
        updated_at="2026-08-26T12:00:00Z",
    )
    can_promote, reason = evaluate_proven_promotion(skill, rec_low_health)
    assert can_promote is False
    assert "health" in reason.lower()


    # Case 4: 6 runs, 3 cross-session, health = 1.0 -> PROMOTED to proven
    rec_qualifying = SkillXPRecord(
        capability_id="docker_deploy",
        domain="devops",
        version_lineage="1.0.0",
        xp=25,
        level=1,
        tier="Novice",
        use_count=6,
        successful_use_count=6,
        failure_count=0,
        cross_session_success=3,
        last_used_at="2026-08-26T12:00:00Z",
        health=1.0,
        updated_at="2026-08-26T12:00:00Z",
    )
    can_promote, reason = evaluate_proven_promotion(skill, rec_qualifying)
    assert can_promote is True
    assert reason == "qualifies for proven lifecycle promotion"

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from hund.skills.drift import (
    DriftReport,
    evaluate_skill_health_and_drift,
    quarantine_skill,
    rollback_skill_version,
)
from hund.skills.loader import load_domain_skills
from hund.skills.model import KnowledgeRef, Skill
from hund.skills.proficiency import SkillXPRecord
from hund.skills.storage import SkillStorage


def test_evaluate_skill_health_and_drift():
    now = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)

    # 1. Fresh healthy skill
    skill_healthy = Skill(
        schema_version=1,
        name="test_skill",
        domain="python",
        status="active",
        triggers=("test",),
        when_to_use="test",
        steps=("step",),
        required_tools=("read_file",),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("verify",),
        health=1.0,
        source_knowledge_refs=(
            KnowledgeRef(knowledge_id="research:packet_01", version="1.0.0"),
        ),
    )
    rec_healthy = SkillXPRecord(
        capability_id="test_skill",
        domain="python",
        version_lineage="1.0.0",
        xp=10,
        level=1,
        tier="Novice",
        use_count=5,
        successful_use_count=5,
        failure_count=0,
        cross_session_success=2,
        last_used_at="2026-08-26T12:00:00Z",
        health=1.0,
        updated_at="2026-08-26T12:00:00Z",
    )
    report_healthy = evaluate_skill_health_and_drift(
        skill_healthy,
        rec_healthy,
        registered_tools={"read_file", "write_file"},
        now=now,
    )
    assert report_healthy.is_stale is False
    assert report_healthy.revalidation_required is False
    assert report_healthy.quarantine_recommended is False

    # 2. Missing tool dependency drift
    report_tool_drift = evaluate_skill_health_and_drift(
        skill_healthy,
        rec_healthy,
        registered_tools={"write_file"},  # missing read_file
        now=now,
    )
    assert report_tool_drift.revalidation_required is True
    assert "missing tool" in report_tool_drift.reason.lower()

    # 3. Severe health collapse -> quarantine recommended
    rec_broken = SkillXPRecord(
        capability_id="test_skill",
        domain="python",
        version_lineage="1.0.0",
        xp=10,
        level=1,
        tier="Novice",
        use_count=6,
        successful_use_count=1,
        failure_count=5,
        cross_session_success=0,
        last_used_at="2026-08-26T12:00:00Z",
        health=0.17,
        updated_at="2026-08-26T12:00:00Z",
    )
    report_broken = evaluate_skill_health_and_drift(
        skill_healthy,
        rec_broken,
        registered_tools={"read_file"},
        now=now,
    )
    assert report_broken.quarantine_recommended is True


def test_quarantine_and_rollback_actions(tmp_path):
    home = tmp_path / "home"
    storage = SkillStorage(home=home)

    # Save v1.0.0
    s1 = Skill(
        schema_version=1,
        name="quarantine_target",
        domain="python",
        status="active",
        triggers=("q",),
        when_to_use="q",
        steps=("old step",),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("v",),
        version="1.0.0",
        lifecycle_state="active",
        vault_state="equipped",
    )
    storage.write_canonical_atomic(s1)
    storage.snapshot_prior_version(s1)

    # Save v1.0.1
    s2 = Skill(
        schema_version=1,
        name="quarantine_target",
        domain="python",
        status="active",
        triggers=("q",),
        when_to_use="q",
        steps=("broken step",),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("v",),
        version="1.0.1",
        lifecycle_state="active",
        vault_state="equipped",
    )
    storage.write_canonical_atomic(s2)

    # 1. Test quarantine
    quarantined = quarantine_skill("quarantine_target", home=home, reason="critical failure")
    assert quarantined is not None
    assert quarantined.lifecycle_state == "quarantined"
    assert quarantined.vault_state == "vaulted"

    # 2. Test rollback
    rolled_back = rollback_skill_version("quarantine_target", home=home)
    assert rolled_back is not None
    assert rolled_back.version == "1.0.0"
    assert rolled_back.steps == ("old step",)

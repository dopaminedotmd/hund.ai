"""Contract tests for the canonical read-only atomic Skill-XP projection."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.proficiency import (
    EVENT_VERIFIED_CROSS_SESSION_REUSE,
    SkillProficiencyStore,
    award_skill_xp,
    record_skill_run_outcome,
)
from hund.skills.projection import project_active_skill_xp
from hund.ui.snapshots import collect_skills


def _skill(
    name: str,
    capability_id: str,
    *,
    lifecycle_state: str = "active",
    vault_state: str = "equipped",
) -> Skill:
    return Skill(
        schema_version=1,
        name=name,
        domain="unrelated-domain-xp",
        status="active",
        triggers=("test",),
        when_to_use="When testing the canonical projection.",
        steps=("Verify the projection.",),
        required_tools=(),
        forbidden_actions=tuple(BANNED_ACTIONS),
        safety_level="read_only",
        verification=("Verify the result.",),
        capability_id=capability_id,
        lifecycle_state=lifecycle_state,
        vault_state=vault_state,
    )


def test_projection_joins_canonical_ids_sorts_deterministically_and_uses_skill_xp(tmp_path) -> None:
    db_path = tmp_path / "hund.db"
    skills = (
        _skill("Zeta", "cap-zeta"),
        _skill("Alpha", "cap-alpha"),
        _skill("Parked", "cap-parked", vault_state="parked"),
        _skill("Deprecated", "cap-deprecated", lifecycle_state="deprecated"),
    )
    timestamp = datetime(2026, 8, 30, tzinfo=timezone.utc)
    for capability_id in ("cap-zeta", "cap-alpha", "cap-parked", "cap-deprecated"):
        award_skill_xp(
            capability_id,
            "unrelated-domain-xp",
            "1.0.0",
            EVENT_VERIFIED_CROSS_SESSION_REUSE,
            f"task-{capability_id}",
            "session-1",
            db_path=db_path,
            now=timestamp,
        )
        record_skill_run_outcome(
            capability_id,
            success=True,
            db_path=db_path,
            now=timestamp,
        )

    rows = project_active_skill_xp(skills, db_path=db_path)

    assert [row.capability_id for row in rows] == ["cap-alpha", "cap-zeta"]
    assert [row.display_name for row in rows] == ["Alpha", "Zeta"]
    assert all(row.total_xp == 4 for row in rows)
    assert all(row.level == 1 and row.progress_percent == 8 for row in rows)


def test_projection_is_read_only_for_missing_records_and_limits_startup_to_five(tmp_path) -> None:
    db_path = tmp_path / "hund.db"
    skills = tuple(_skill(f"Skill {index}", f"cap-{index}") for index in range(6))

    rows = project_active_skill_xp(skills, db_path=db_path, limit=5)

    assert len(rows) == 5
    assert [row.capability_id for row in rows] == ["cap-0", "cap-1", "cap-2", "cap-3", "cap-4"]
    assert all(row.total_xp == 0 and row.level == 1 and row.progress_percent == 0 for row in rows)
    assert not db_path.exists()


def test_fullscreen_skills_snapshot_uses_the_same_canonical_skill_xp_projection(tmp_path) -> None:
    skill = _skill("snapshot-skill", "canonical-snapshot-capability")
    skills_dir = tmp_path / "brain" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "snapshot-skill.json").write_text(
        json.dumps(skill.to_dict()),
        encoding="utf-8",
    )
    award_skill_xp(
        "canonical-snapshot-capability",
        "unrelated-domain-xp",
        "1.0.0",
        EVENT_VERIFIED_CROSS_SESSION_REUSE,
        "snapshot-task",
        "session-1",
        db_path=tmp_path / "hund.db",
    )

    snapshot = collect_skills(home=tmp_path)

    assert len(snapshot.equipped) == 1
    assert snapshot.equipped[0].capability_id == "canonical-snapshot-capability"
    assert snapshot.equipped[0].xp == 4
    assert snapshot.equipped[0].percent == 8

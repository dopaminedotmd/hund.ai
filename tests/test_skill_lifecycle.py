"""Tests for Skill Lifecycle transitions, schema validation, and sandbox gates."""
import pytest

from hund.skills.lifecycle import (
    can_transition_skill,
    run_skill_sandbox_test,
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_DRAFT,
    SKILL_STATUS_PROVEN,
    SKILL_STATUS_QUARANTINED,
    SKILL_STATUS_SANDBOX_TESTED,
    SKILL_STATUS_SCHEMA_VALID,
    validate_skill_schema,
)


def test_validate_skill_schema() -> None:
    valid_skill = {
        "name": "git_workflow",
        "version": "1.0.0",
        "tools": ["git_status", "git_commit"],
    }
    ok, msg = validate_skill_schema(valid_skill)
    assert ok is True

    invalid_skill = {"name": ""}
    ok, msg = validate_skill_schema(invalid_skill)
    assert ok is False
    assert "name" in msg


def test_sandbox_testing() -> None:
    tool_skill = {
        "name": "file_cleaner",
        "version": "1.0.0",
        "tools": ["rm_rf"],
    }
    # Success dry-run
    ok, _ = run_skill_sandbox_test(tool_skill, dry_run_executor=lambda s: True)
    assert ok is True

    # Failed dry-run
    ok, msg = run_skill_sandbox_test(tool_skill, dry_run_executor=lambda s: False)
    assert ok is False
    assert "reported failure" in msg


def test_tool_access_skill_transition_gate() -> None:
    # 1. Non-tool skill can transition from schema_valid to active
    ok, _ = can_transition_skill(
        current_status=SKILL_STATUS_SCHEMA_VALID,
        target_status=SKILL_STATUS_ACTIVE,
        has_tools=False,
    )
    assert ok is True

    # 2. Tool-access skill CANNOT skip sandbox_tested
    ok, msg = can_transition_skill(
        current_status=SKILL_STATUS_SCHEMA_VALID,
        target_status=SKILL_STATUS_ACTIVE,
        has_tools=True,
    )
    assert ok is False
    assert "cannot transition from schema_valid to active without sandbox_tested" in msg

    # 3. Tool-access skill CAN transition to sandbox_tested, then active
    ok, _ = can_transition_skill(
        current_status=SKILL_STATUS_SCHEMA_VALID,
        target_status=SKILL_STATUS_SANDBOX_TESTED,
        has_tools=True,
    )
    assert ok is True

    ok, _ = can_transition_skill(
        current_status=SKILL_STATUS_SANDBOX_TESTED,
        target_status=SKILL_STATUS_ACTIVE,
        has_tools=True,
    )
    assert ok is True

    # 4. Active -> Proven
    ok, _ = can_transition_skill(
        current_status=SKILL_STATUS_ACTIVE,
        target_status=SKILL_STATUS_PROVEN,
        has_tools=True,
    )
    assert ok is True

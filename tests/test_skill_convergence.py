"""Converged lifecycle/vault schema compatibility tests."""
from dataclasses import replace

from hund.skills.lifecycle import run_skill_sandbox_test
from hund.skills.model import Skill


def _legacy(status: str = "active") -> dict:
    return {
        "schema_version": 1,
        "name": "safe-skill",
        "domain": "test",
        "status": status,
        "triggers": ["test"],
        "when_to_use": "during tests",
        "steps": ["inspect"],
        "tools": ["read_file"],
        "forbidden_actions": ["self_update"],
        "safety_level": "read_only",
        "verification": ["pytest"],
    }


def test_legacy_active_migrates_to_separate_states():
    skill = Skill.from_dict(_legacy("active"))
    assert skill.lifecycle_state == "active"
    assert skill.vault_state == "equipped"
    assert skill.status == "active"
    assert skill.required_tools == ("read_file",)


def test_legacy_vaulted_preserves_active_lifecycle():
    skill = Skill.from_dict(_legacy("vaulted"))
    assert skill.lifecycle_state == "active"
    assert skill.vault_state == "vaulted"
    assert skill.status == "active"


def test_nonactive_skill_cannot_be_equipped():
    data = _legacy("draft")
    data["lifecycle_state"] = "draft"
    data["vault_state"] = "equipped"
    skill = Skill.from_dict(data)
    assert skill.vault_state == "vaulted"
    assert replace(skill, vault_state="equipped").vault_state == "vaulted"


def test_tool_skill_sandbox_fails_closed_without_executor():
    ok, message = run_skill_sandbox_test(
        {"name": "tool-skill", "version": "1.0.0", "tools": ["read_file"]}
    )
    assert not ok
    assert "requires an executing" in message


def test_instruction_skill_can_take_no_tool_path():
    ok, _ = run_skill_sandbox_test(
        {"name": "instruction-skill", "version": "1.0.0", "tools": []}
    )
    assert ok

"""Integration tests for chat-driven skill creation and vault read-back (Del 1 & Del 2)."""
import pytest
from pathlib import Path

from hund.tools.skill_tool import make_handler
from hund.skills.vault import SkillVault, skill_exists
from hund.tools.types import ToolStatus


def test_create_skill_from_chat_request_end_to_end(tmp_path: Path):
    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    handler = make_handler(home=home, workspace_path=ws)

    # 1. LLM sends a request string from chat
    res = handler({"request": "project planning", "target_scope": "project", "desired_disposition": "vault"})
    assert res.status == ToolStatus.SUCCESS, f"create_skill failed: {res.public_error}"
    assert "Saved skill 'planning'" in res.to_llm_text() or "Saved skill 'project-planning'" in res.to_llm_text()

    # 2. Verify existence using canonical vault lookup (Del 2)
    vault = SkillVault(home=home)
    assert vault.has_skill("project-planning", workspace=ws) or vault.has_skill("planning", workspace=ws)
    assert skill_exists("project-planning", home=home, workspace=ws) or skill_exists("planning", home=home, workspace=ws)


def test_create_skill_from_chat_legacy_skill_dict_end_to_end(tmp_path: Path):
    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    handler = make_handler(home=home, workspace_path=ws)

    skill_dict = {
        "schema_version": 1,
        "name": "git-rebase-workflow",
        "domain": "general",
        "status": "draft",
        "triggers": ["clean interactive rebases", "squash commits before merge"],
        "when_to_use": "Use when performing clean interactive rebases or squashing commits before opening PRs.",
        "steps": [
            "1. Inspect commit log and status before rebasing.",
            "2. Execute interactive rebase against target branch.",
            "3. Verify history and working tree cleanly.",
        ],
        "required_tools": [],
        "forbidden_actions": [],
        "safety_level": "read_only",
        "verification": ["Verify git log shows desired commits in sequence."],
        "lifecycle_state": "active",
        "vault_state": "vaulted",
        "version": "1.0.0",
        "capability_id": "general/git-rebase-workflow",
        "scope": "project",
        "personal_skill_xp": 0,
    }

    # 3. Direct chat tool call without pre-minted stepper keys
    res = handler({"skill": skill_dict, "desired_disposition": "vault"})
    assert res.status == ToolStatus.SUCCESS, f"create_skill failed: {res.public_error}"
    assert "Saved skill 'git-rebase-workflow'" in res.to_llm_text()

    # 4. Canonical existence verification
    assert skill_exists("git-rebase-workflow", home=home, workspace=ws)

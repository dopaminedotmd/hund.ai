"""Tests for TCB turn boundary dynamic skill reload and system prompt immutability."""
from pathlib import Path
import pytest

from hund.agent.loop import _dynamic_context_message, _safe_skills, assemble_system_prompt
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.storage import SkillStorage


def _create_skill(home: Path, name: str, scope: str = "global", ws_key: str = "global") -> Skill:
    storage = SkillStorage(home=home)
    skill = Skill(
        schema_version=1,
        name=name,
        domain="general",
        status="active",
        lifecycle_state="active",
        vault_state="equipped",
        triggers=(name, f"run {name}"),
        when_to_use=f"When doing {name}.",
        steps=("Step 1",),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify",),
        scope=scope,
    )
    storage.write_canonical_atomic(skill, workspace_key=ws_key)
    return skill


def test_turn_boundary_reloads_newly_published_skill(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("hund.paths.hund_home", lambda: tmp_path)

    # Turn 1: No domain skills yet
    skills_t1 = _safe_skills(workspace=tmp_path)
    msg_t1 = _dynamic_context_message(skills=skills_t1, user_text="do turn 1", workspace_id=str(tmp_path))

    # In turn 1, a new skill is published
    _create_skill(tmp_path, "newly-published-skill")

    # Turn 2: Turn boundary reloads skills
    skills_t2 = _safe_skills(workspace=tmp_path)
    assert any(s.name == "newly-published-skill" for s in skills_t2)

    msg_t2 = _dynamic_context_message(
        skills=skills_t2,
        user_text="run newly-published-skill",
        workspace_id=str(tmp_path),
    )
    assert msg_t2 is not None
    assert "newly-published-skill" in msg_t2.content


def test_system_prompt_remains_byte_stable_across_turns(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("hund.paths.hund_home", lambda: tmp_path)
    from hund.doctor import EnvironmentProfile

    profile = EnvironmentProfile(
        os="Windows",
        os_version="11",
        os_caption="Microsoft Windows 11 Pro",
        processor="Intel i7",
        total_ram_gb=16.0,
        shell="powershell",
    )

    system_prompt_turn1 = assemble_system_prompt("Hund is an AI.", profile, knowledge=[])

    # Publish skills
    _create_skill(tmp_path, "extra-skill-1")
    _create_skill(tmp_path, "extra-skill-2")

    # System prompt in messages[0] should remain strictly identical
    system_prompt_turn2 = assemble_system_prompt("Hund is an AI.", profile, knowledge=[])
    assert system_prompt_turn1 == system_prompt_turn2
    assert system_prompt_turn1.encode("utf-8") == system_prompt_turn2.encode("utf-8")


def test_turn_boundary_isolates_different_workspaces(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("hund.paths.hund_home", lambda: tmp_path)
    from hund.skills.scope import compute_workspace_key

    ws_a = tmp_path / "ws_alpha"
    ws_b = tmp_path / "ws_beta"
    ws_a.mkdir()
    ws_b.mkdir()

    key_a = compute_workspace_key(ws_a)
    key_b = compute_workspace_key(ws_b)

    _create_skill(tmp_path, "skill-in-a", scope="project", ws_key=key_a)
    _create_skill(tmp_path, "skill-in-b", scope="project", ws_key=key_b)

    skills_a = _safe_skills(workspace=ws_a)
    skills_b = _safe_skills(workspace=ws_b)

    assert any(s.name == "skill-in-a" for s in skills_a)
    assert not any(s.name == "skill-in-b" for s in skills_a)

    assert any(s.name == "skill-in-b" for s in skills_b)
    assert not any(s.name == "skill-in-a" for s in skills_b)

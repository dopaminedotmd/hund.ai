import json
from pathlib import Path
import pytest

from hund.skills.model import Skill
from hund.skills.vault import SkillVault


def _make_domain_skill(name: str, domain: str = "custom") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "domain": domain,
        "status": "active",
        "triggers": ["custom_trigger"],
        "when_to_use": "when custom action is needed",
        "steps": ["step 1"],
        "required_tools": ["read_file"],
        "forbidden_actions": ["self_update", "apply_update", "modify_tcb", "elevate_permissions"],
        "safety_level": "read_only",
        "verification": ["uv run pytest"],
    }


def test_vault_initialization_defaults_fresh(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    active = vault.get_active_skills()
    vaulted = vault.list_vaulted()
    core = vault.get_core_skills()

    # Fresh install has 0 domain skills and 12 core instincts
    assert len(active) == 0
    assert len(vaulted) == 0
    assert len(core) == 12
    assert any(s.name == "shell-command-safety" for s in core)
    assert any(s.name == "skill-authoring" for s in core)


def test_vault_domain_skills_management(tmp_path: Path):
    # Add 7 custom domain skills to brain/skills/
    skills_dir = tmp_path / "brain" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 8):
        name = f"custom-skill-{i}"
        (skills_dir / f"{name}.json").write_text(
            json.dumps(_make_domain_skill(name)), encoding="utf-8"
        )

    vault = SkillVault(home=tmp_path)
    active = vault.get_active_skills()
    vaulted = vault.list_vaulted()

    # Every lifecycle-active atomic skill remains explicitly equipped.
    assert len(active) == 7
    assert len(vaulted) == 0

    # Park one skill
    ok, msg = vault.park("custom-skill-1")
    assert ok is True
    assert len(vault.get_active_skills()) == 6
    assert len(vault.list_vaulted()) == 1

    # Equip vaulted skill
    ok_equip, msg_equip = vault.equip("custom-skill-1")
    assert ok_equip is True
    assert len(vault.get_active_skills()) == 7
    assert "slot" not in msg_equip.lower()


def test_vault_preserves_more_than_six_equipped_skills_across_reload(tmp_path: Path):
    skills_dir = tmp_path / "brain" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        name = f"unlimited-skill-{i}"
        (skills_dir / f"{name}.json").write_text(
            json.dumps(_make_domain_skill(name)), encoding="utf-8"
        )

    first = SkillVault(home=tmp_path)
    second = SkillVault(home=tmp_path)

    assert len(first.get_active_skills()) == 8
    assert len(second.get_active_skills()) == 8
    assert second.list_vaulted() == []


def test_vault_cleans_legacy_builtins_from_state_file(tmp_path: Path):
    # Simulate an old state file that had builtins in active list
    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "active": ["shell-command-safety", "file-operations", "git-safety"],
            "vaulted": ["systematic-debugging"],
        }),
        encoding="utf-8",
    )

    vault = SkillVault(home=tmp_path)
    # State is cleaned because no custom domain skills exist
    assert len(vault.get_active_skills()) == 0
    assert len(vault.list_vaulted()) == 0
    # Core instincts remain available
    assert len(vault.get_core_skills()) == 12


def test_vault_invalid_skill_names(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    ok_equip, _ = vault.equip("nonexistent-skill-xyz")
    assert ok_equip is False

    ok_park, _ = vault.park("nonexistent-skill-xyz")
    assert ok_park is False

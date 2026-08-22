from pathlib import Path
import pytest

from hund.skills.model import MAX_ACTIVE_SKILLS, Skill
from hund.skills.vault import SkillVault, DEFAULT_ACTIVE_SKILLS, MANDATORY_SECURITY_SKILLS


def test_vault_initialization_defaults(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    active = vault.get_active_skills()
    vaulted = vault.list_vaulted()

    assert len(active) == 6
    assert len(vaulted) == 5
    assert len(active) + len(vaulted) == 11

    # Mandatory security skills must be active by default
    active_names = {s.name for s in active}
    for sec_skill in MANDATORY_SECURITY_SKILLS:
        assert sec_skill in active_names


def test_vault_persistence(tmp_path: Path):
    vault1 = SkillVault(home=tmp_path)
    assert (tmp_path / "brain" / "skill_state.json").exists()

    # Park a non-security skill
    ok, msg = vault1.park("environment-profiling")
    assert ok is True
    assert len(vault1.get_active_skills()) == 5
    assert len(vault1.list_vaulted()) == 6

    # Create a new instance and verify state is loaded
    vault2 = SkillVault(home=tmp_path)
    assert len(vault2.get_active_skills()) == 5
    assert len(vault2.list_vaulted()) == 6
    assert any(s.name == "environment-profiling" for s in vault2.list_vaulted())


def test_vault_security_skills_cannot_be_parked(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    ok, msg = vault.park("shell-command-safety")
    assert ok is False
    assert "mandatory runtime invariant" in msg.lower() or "cannot be parked" in msg.lower()


def test_vault_equip_capacity_enforcement(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    assert len(vault.get_active_skills()) == 6

    # Attempt to equip when capacity is full
    ok, msg = vault.equip("context-condenser")
    assert ok is False
    assert "capacity reached" in msg.lower()

    # Park one non-security skill, then equip
    ok_park, _ = vault.park("systematic-debugging")
    assert ok_park is True
    assert len(vault.get_active_skills()) == 5

    ok_equip, equip_msg = vault.equip("context-condenser")
    assert ok_equip is True
    assert len(vault.get_active_skills()) == 6
    assert any(s.name == "context-condenser" for s in vault.get_active_skills())


def test_vault_swap(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    
    # Swapping a security skill is rejected
    ok_bad, _ = vault.swap("git-safety", "context-condenser")
    assert ok_bad is False

    # Swapping an active non-security skill with a vaulted skill succeeds
    ok_swap, swap_msg = vault.swap("environment-profiling", "context-condenser")
    assert ok_swap is True
    assert "Swapped" in swap_msg

    active_names = {s.name for s in vault.get_active_skills()}
    vaulted_names = {s.name for s in vault.list_vaulted()}

    assert "context-condenser" in active_names
    assert "environment-profiling" in vaulted_names
    assert len(active_names) == 6


def test_vault_invalid_skill_names(tmp_path: Path):
    vault = SkillVault(home=tmp_path)
    ok_equip, _ = vault.equip("nonexistent-skill-xyz")
    assert ok_equip is False

    ok_park, _ = vault.park("nonexistent-skill-xyz")
    assert ok_park is False

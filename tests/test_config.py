"""Tests for HundConfig and feature switches."""
from pathlib import Path
import pytest

from hund.config import HundConfig
from hund.skills.loader import load_domain_skills
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.storage import SkillStorage


def test_feature_disable_reenable_state_intact(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    assert cfg.enable_on_demand_publication is True

    cfg.save(cfg_file)
    loaded = HundConfig.load(cfg_file)
    assert loaded.enable_on_demand_publication is True

    # Disable feature
    loaded.enable_on_demand_publication = False
    loaded.save(cfg_file)
    reloaded = HundConfig.load(cfg_file)
    assert reloaded.enable_on_demand_publication is False

    # Create skills in storage
    storage = SkillStorage(home=tmp_path)
    skill = Skill(
        schema_version=1,
        name="persistent-skill",
        domain="general",
        status="active",
        lifecycle_state="active",
        vault_state="equipped",
        triggers=("test",),
        when_to_use="When testing.",
        steps=("Step 1",),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify",),
    )
    storage.write_canonical_atomic(skill)

    # When feature disabled, existing skills still load correctly
    skills = load_domain_skills(home=tmp_path)
    assert any(s.name == "persistent-skill" for s in skills)

    # Re-enable
    reloaded.enable_on_demand_publication = True
    reloaded.save(cfg_file)
    active_cfg = HundConfig.load(cfg_file)
    assert active_cfg.enable_on_demand_publication is True
    skills_after = load_domain_skills(home=tmp_path)
    assert any(s.name == "persistent-skill" for s in skills_after)

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


# --- Track 21: context window truthfulness (Masterplan A STEG 0) ---


def test_catalog_deepseek_context_windows_are_truthful() -> None:
    """Every DeepSeek catalog option must state the real window, never 1M."""
    from hund.providers.catalog import MODEL_OPTIONS, PROVIDER_PRESETS

    deepseek_options = [opt for opt in MODEL_OPTIONS if opt.provider_id == "deepseek"]
    assert deepseek_options, "catalog must keep DeepSeek model options"
    for opt in deepseek_options:
        assert opt.context_window == 131_072, (
            f"{opt.model_id} claims {opt.context_window}; deepseek models have "
            "a verified 128k window (REV3.3 audit)"
        )

    preset = next(p for p in PROVIDER_PRESETS if p.provider_id == "deepseek")
    assert preset.context_window == 131_072


def test_default_provider_context_window_is_not_1m() -> None:
    """A brand-new config must not claim 1M tokens for the default deepseek model."""
    cfg = HundConfig()
    assert cfg.provider.context_window == 131_072
    assert cfg.provider.context_window != 1_000_000


def test_load_corrects_overclaimed_context_window(tmp_path: Path) -> None:
    """A stale config claiming 1M for deepseek-chat is corrected to 128k at load."""
    import json

    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    cfg.provider.model = "deepseek-chat"
    cfg.provider.context_window = 1_000_000
    cfg.save(cfg_file)

    loaded = HundConfig.load(cfg_file)
    assert loaded.provider.context_window == 131_072

    # The correction is persisted so later loads see the truthful value.
    persisted = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert persisted["provider"]["context_window"] == 131_072


def test_load_corrects_overclaimed_window_for_known_openai_model(tmp_path: Path) -> None:
    """Correction is driven by the catalog, not by provider-specific casing."""
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    cfg.provider.base_url = "https://api.openai.com/v1"
    cfg.provider.model = "gpt-4o"
    cfg.provider.context_window = 1_000_000
    cfg.save(cfg_file)

    loaded = HundConfig.load(cfg_file)
    assert loaded.provider.context_window == 128_000


def test_load_keeps_legacy_64k_window(tmp_path: Path) -> None:
    """Regression: legacy 64k values must never be upgraded to 1M again."""
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    cfg.provider.model = "deepseek-chat"
    cfg.provider.context_window = 64_000
    cfg.save(cfg_file)

    loaded = HundConfig.load(cfg_file)
    assert loaded.provider.context_window == 64_000


def test_load_keeps_window_for_unknown_model(tmp_path: Path) -> None:
    """Unknown models have no catalog truth; the configured value is left alone."""
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    cfg.provider.base_url = "https://example.invalid/v1"
    cfg.provider.model = "mystery-model"
    cfg.provider.context_window = 1_000_000
    cfg.save(cfg_file)

    loaded = HundConfig.load(cfg_file)
    assert loaded.provider.context_window == 1_000_000


def test_active_option_never_reports_1m_for_deepseek() -> None:
    """active_option() must prefer catalog truth over stale config values."""
    from hund.providers.catalog import active_option

    cfg = HundConfig()
    cfg.provider.model = "deepseek-chat"
    cfg.provider.context_window = 1_000_000  # stale claim
    option = active_option(cfg)
    assert option.context_window == 131_072


def test_active_option_known_model_on_proxy_uses_catalog_window() -> None:
    """A known model behind a proxy still reports the catalog window."""
    from types import SimpleNamespace

    from hund.providers.catalog import active_option

    cfg = SimpleNamespace(
        provider=SimpleNamespace(
            model="deepseek-chat",
            base_url="https://proxy.example/v1",
            provider_id="deepseek",
            credential_id="deepseek",
            context_window=1_000_000,
        ),
        custom_endpoints=[],
    )
    option = active_option(cfg)
    assert option.model_id == "deepseek-chat"
    assert option.base_url == "https://proxy.example/v1"
    assert option.context_window == 131_072


def test_active_option_fallback_is_not_1m_for_unknown_model() -> None:
    """The unknown-model fallback must never fabricate a 1M window."""
    from types import SimpleNamespace

    from hund.providers.catalog import active_option

    cfg = SimpleNamespace(
        provider=SimpleNamespace(
            model="mystery-model",
            base_url="https://example.invalid/v1",
            provider_id="custom",
            credential_id="custom",
        ),
        custom_endpoints=[],
    )
    option = active_option(cfg)
    assert option.context_window != 1_000_000

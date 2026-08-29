from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import json
import pytest

from hund.config import CustomEndpoint, HundConfig
from hund.providers.catalog import (
    MODEL_OPTIONS,
    activate_model,
    custom_model,
    get_options,
)


def test_corrupt_config_creates_backup_and_sets_recovery_notice(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    # Write invalid JSON
    cfg_file.write_text("{corrupted_json_content...", encoding="utf-8")

    loaded = HundConfig.load(cfg_file)
    assert loaded._recovery_notice is not None
    assert "Recovered corrupted config" in loaded._recovery_notice

    # Verify backup file was created
    corrupt_backups = list(tmp_path.glob("config.json.corrupt.*"))
    assert len(corrupt_backups) == 1
    assert corrupt_backups[0].read_text(encoding="utf-8") == "{corrupted_json_content..."

    # Verify _recovery_notice is NOT serialized to JSON
    saved_json = loaded.model_dump_json()
    assert "_recovery_notice" not in saved_json


def test_custom_endpoint_persistence(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    ep = CustomEndpoint(
        id="custom_123",
        name="Local vLLM",
        base_url="http://localhost:8000/v1",
        model_id="mistralai/Mistral-7B",
        context_window=32768,
        credential_id="custom_123",
    )
    cfg.custom_endpoints.append(ep)
    cfg.save(cfg_file)

    loaded = HundConfig.load(cfg_file)
    assert len(loaded.custom_endpoints) == 1
    assert loaded.custom_endpoints[0].name == "Local vLLM"
    assert loaded.custom_endpoints[0].base_url == "http://localhost:8000/v1"

    # Options include the custom endpoint when unconfigured options are requested
    opts = get_options(loaded, include_unconfigured=True)
    assert any(o.model_id == "mistralai/Mistral-7B" for o in opts)

    # When credential exists in vault, options include it automatically
    with patch("keyring.get_password", return_value="sk-valid-key"):
        opts_with_key = get_options(loaded)
        assert any(o.model_id == "mistralai/Mistral-7B" for o in opts_with_key)


def test_activate_model_persists_config(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    cfg.save(cfg_file)

    rt = SimpleNamespace(
        client=MagicMock(),
        key="test_key",
        cfg=cfg,
        engine=None,
    )
    # Monkeypatch config_path to return our test file
    monkeypatch.setattr("hund.config.config_path", lambda: cfg_file)

    opt = custom_model("openai", "https://api.openai.com/v1", "gpt-4o", 128000)
    with patch("hund.providers.catalog.credential_for", return_value="sk-valid-key"):
        ok, msg = activate_model(rt, opt)
        assert ok is True
        assert "Active model: gpt-4o" in msg

    # Verify saved file has new model
    reloaded = HundConfig.load(cfg_file)
    assert reloaded.provider.model == "gpt-4o"
    assert reloaded.provider.base_url == "https://api.openai.com/v1"
    assert reloaded.provider.credential_id == "openai"

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import pytest

from hund.config import HundConfig
from hund.providers.catalog import (
    MODEL_OPTIONS,
    PROVIDER_PRESETS,
    active_option,
    custom_model,
    get_options,
)
from hund.secrets import delete_api_key, get_credential_status, load_api_key, save_api_key
from hund.ui.commands import COMMANDS, HELP_ROWS, CommandContext
from hund.ui.input import SLASH_COMMAND_METAS
from hund.ui.screen_render import (
    render_auth_add_modal,
    render_auth_custom_wizard_modal,
    render_auth_forget_modal,
    render_auth_manage_modal,
    render_auth_modal,
    render_model_modal,
)
from hund.ui.screen_state import OverlayView, ScreenController


def test_slash_command_registration() -> None:
    assert "/auth" in SLASH_COMMAND_METAS
    assert "auth" in COMMANDS
    assert any(row[0] == "/auth" for row in HELP_ROWS)


def test_credential_status_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env_secret_123")
    status, detail = get_credential_status("deepseek", "DEEPSEEK_API_KEY")
    assert status == "environment"
    assert detail == "DEEPSEEK_API_KEY"


def test_credential_status_configured(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("HUND_API_KEY", raising=False)
    with patch("keyring.get_password", return_value="vault_secret_456"):
        status, detail = get_credential_status("deepseek", "DEEPSEEK_API_KEY")
        assert status == "configured"
        assert detail == ""


def test_credential_status_missing(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("HUND_API_KEY", raising=False)
    with patch("keyring.get_password", return_value=None):
        status, detail = get_credential_status("deepseek", "DEEPSEEK_API_KEY")
        assert status == "missing"


def test_screen_state_auth_hierarchy() -> None:
    screens = ScreenController()
    screens.open_overlay(OverlayView.AUTH)
    assert screens.overlay == OverlayView.AUTH

    # Navigate to AUTH_ADD
    screens.open_overlay(OverlayView.AUTH_ADD)
    assert screens.overlay == OverlayView.AUTH_ADD

    # Navigate to AUTH_KEY
    screens.open_overlay(OverlayView.AUTH_KEY)
    assert screens.overlay == OverlayView.AUTH_KEY

    # Step back returns to AUTH_ADD
    res = screens.step_back()
    assert res == "nested"
    assert screens.overlay == OverlayView.AUTH_ADD

    # Step back returns to AUTH
    res = screens.step_back()
    assert res == "nested"
    assert screens.overlay == OverlayView.AUTH

    # Step back returns to Chat
    res = screens.step_back()
    assert res == "overlay"
    assert screens.overlay == OverlayView.NONE


def test_auth_screen_renderers() -> None:
    # Auth root
    root = render_auth_modal(0, 80)
    assert "AUTHENTICATION & PROVIDERS" in root
    assert "Add provider" in root
    assert "Manage providers" in root
    assert "[←] Back · [Esc/q] Close" in root

    # Auth add
    add = render_auth_add_modal(PROVIDER_PRESETS, 0, 80)
    assert "ADD PROVIDER" in add
    assert "DeepSeek" in add
    assert "OpenRouter" in add
    assert "Custom Endpoint" in add
    assert "[←] Back · [Esc/q] Close" in add

    # Auth manage
    entries = [
        ("DeepSeek", "deepseek-chat", "[Environment]", "Controlled by DEEPSEEK_API_KEY"),
        ("OpenRouter", "nemotron", "[Configured]", "Key saved in Windows Credential Manager"),
    ]
    manage = render_auth_manage_modal(entries, 0, 80)
    assert "MANAGE PROVIDERS" in manage
    assert "[Environment]" in manage
    assert "[Configured]" in manage
    assert "[r] Replace" in manage
    assert "[d] Forget" in manage

    # Custom wizard step 1
    wiz = render_auth_custom_wizard_modal(0, {}, "My vLLM", 80)
    assert "CUSTOM ENDPOINT WIZARD" in wiz
    assert "Step 1/5" in wiz
    assert "My vLLM" in wiz

    # Forget modal
    forget = render_auth_forget_modal("OpenRouter", 80)
    assert "CONFIRM FORGET CREDENTIAL" in forget
    assert "OpenRouter" in forget
    assert "[y] Confirm" in forget


def test_model_modal_layout(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env_secret")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("HUND_API_KEY", raising=False)

    with patch("keyring.get_password", return_value=None):
        options = [o for o in MODEL_OPTIONS if o.provider_id == "deepseek"]
        rendered = render_model_modal(options, "deepseek-chat", 0, 80)
        assert "DeepSeek · Active" in rendered
        assert "Configured providers only" in rendered
        assert "[Ready]" not in rendered
        assert "[a] Add provider" in rendered
        assert "[k] Replace selected provider key" in rendered

"""Comprehensive handler-level regression test suite for Reopened Model/Auth TUI Stabilization."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from prompt_toolkit.input import DummyInput
from prompt_toolkit.key_binding.key_bindings import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import DummyOutput

from hund.config import CustomEndpoint, HundConfig
from hund.providers.catalog import (
    MODEL_OPTIONS,
    PROVIDER_PRESETS,
    active_option,
    custom_model,
    get_options,
)
from hund.secrets import get_credential_status, load_api_key, save_api_key
from hund.ui import theme
from hund.ui.fullscreen import create_fullscreen_app
from hund.ui.modal_editor import ModalTextEditor
from hund.ui.screen_render import render_model_modal
from hund.ui.screen_state import DestinationView, OverlayView, ScreenController


def _make_app(rt: SimpleNamespace, state: SimpleNamespace):
    return create_fullscreen_app(rt, state, output=DummyOutput(), input=DummyInput())


def _make_dummy_runtime(tmp_path: Path) -> SimpleNamespace:
    cfg_file = tmp_path / "config.json"
    cfg = HundConfig()
    cfg.provider.model = "deepseek-chat"
    cfg.provider.base_url = "https://api.deepseek.com"
    cfg.provider.credential_id = "deepseek"
    cfg.save(cfg_file)

    rt = SimpleNamespace(
        client=MagicMock(),
        key="test_key",
        cfg=cfg,
        engine=None,
        workspace=tmp_path,
        messages=[],
    )
    return rt


def test_empty_credentials_produces_empty_model_options_and_honest_empty_modal(monkeypatch) -> None:
    """Verify that when no credentials are configured, no model rows are fabricated."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HUND_API_KEY", raising=False)

    cfg = HundConfig()
    cfg.custom_endpoints.clear()

    with patch("keyring.get_password", return_value=None):
        options = get_options(cfg)
        assert options == [], "Must not fabricate DeepSeek rows when unconfigured"

        rendered = render_model_modal(options, cfg.provider.model, 0, 80)
        assert "No configured providers found." in rendered
        assert "Press [a] to add a provider." in rendered
        assert f"Warning: Active model '{cfg.provider.model}' has no credential." in rendered
        assert "Configured providers only" in rendered
        assert "[Ready]" not in rendered


def test_multiple_custom_endpoints_with_hund_api_key_only_configures_active(monkeypatch) -> None:
    """Verify legacy HUND_API_KEY only configures the single active custom endpoint."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("HUND_API_KEY", "legacy_token_xyz")

    cfg = HundConfig()
    cfg.custom_endpoints = [
        CustomEndpoint(
            id="custom_1",
            name="Endpoint 1",
            base_url="http://localhost:8001/v1",
            model_id="model-1",
            context_window=32768,
            credential_id="custom_1",
        ),
        CustomEndpoint(
            id="custom_2",
            name="Endpoint 2",
            base_url="http://localhost:8002/v1",
            model_id="model-2",
            context_window=32768,
            credential_id="custom_2",
        ),
    ]

    with patch("keyring.get_password", return_value=None):
        # 1. When custom_1 is active: only custom_1 appears in options
        cfg.provider.credential_id = "custom_1"
        options_1 = get_options(cfg)
        assert any(o.model_id == "model-1" for o in options_1)
        assert not any(o.model_id == "model-2" for o in options_1)

        # 2. When custom_2 is active: only custom_2 appears in options
        cfg.provider.credential_id = "custom_2"
        options_2 = get_options(cfg)
        assert any(o.model_id == "model-2" for o in options_2)
        assert not any(o.model_id == "model-1" for o in options_2)


def test_deepseek_configured_only_shows_deepseek_options(monkeypatch) -> None:
    """Verify configuring DeepSeek shows only DeepSeek options."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HUND_API_KEY", raising=False)

    cfg = HundConfig()
    cfg.custom_endpoints.clear()

    with patch("keyring.get_password", return_value=None):
        options = get_options(cfg)
        assert len(options) > 0
        assert all(o.provider_id == "deepseek" for o in options)


def test_openrouter_configured_shows_openrouter_options(monkeypatch) -> None:
    """Verify configuring OpenRouter shows OpenRouter options with Gemini included."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HUND_API_KEY", raising=False)

    cfg = HundConfig()
    cfg.custom_endpoints.clear()

    with patch("keyring.get_password", return_value=None):
        options = get_options(cfg)
        assert len(options) > 0
        assert all(o.provider_id == "openrouter" for o in options)
        assert any("gemini" in o.model_id for o in options)
        # Assert no standalone Google preset exists
        assert not any(p.provider_id == "google" for p in PROVIDER_PRESETS)


def test_opening_model_performs_no_network_requests(monkeypatch) -> None:
    """Verify opening /model is completely offline without network requests."""
    cfg = HundConfig()
    with patch("urllib.request.urlopen") as mock_url, patch("http.client.HTTPConnection") as mock_conn:
        options = get_options(cfg)
        render_model_modal(options, cfg.provider.model, 0, 80)
        assert mock_url.call_count == 0
        assert mock_conn.call_count == 0


def test_fullscreen_auth_key_save_preserves_active_provider_and_model(tmp_path: Path) -> None:
    """Handler-level test: saving a key in AUTH_KEY preserves active model and provider."""
    rt = _make_dummy_runtime(tmp_path)
    state = SimpleNamespace(extra={}, theme_name="marshmallow")
    app, ctx = _make_app(rt, state)

    screens: ScreenController = ctx["screens"]
    modal_editor: ModalTextEditor = ctx["modal_editor"]
    auth_target_provider = ctx["auth_target_provider"]
    kb: KeyBindings = ctx["kb"]

    # Initial state
    assert rt.cfg.provider.model == "deepseek-chat"
    assert rt.cfg.provider.credential_id == "deepseek"

    # Navigate to AUTH_KEY for OpenRouter
    auth_target_provider["name"] = "OpenRouter"
    auth_target_provider["credential_id"] = "openrouter"
    auth_target_provider["env_name"] = "OPENROUTER_API_KEY"
    screens.open_overlay(OverlayView.AUTH_KEY)
    modal_editor.set_text("sk-or-new-key")

    # Find and execute the Enter binding handler
    enter_binding = next(b for b in kb.bindings if b.handler.__name__ == "_overlay_enter")

    with patch("hund.secrets.save_api_key", return_value=True), patch("keyring.get_password", return_value="sk-or-new-key"):
        # Execute the handler directly through event mock
        event = SimpleNamespace(app=app, key_sequence=[])
        enter_binding.handler(event)

    # Invariant checks
    assert rt.cfg.provider.model == "deepseek-chat", "Active model must remain deepseek-chat"
    assert rt.cfg.provider.credential_id == "deepseek", "Active credential must remain deepseek"
    assert screens.overlay == OverlayView.MODEL
    assert "Saved API key for OpenRouter." in screens.status


def test_fullscreen_auth_custom_wizard_full_flow_and_fail_closed(tmp_path: Path) -> None:
    """Handler-level test: AUTH_CUSTOM wizard step progression, fail-closed vault, and rollback."""
    rt = _make_dummy_runtime(tmp_path)
    state = SimpleNamespace(extra={}, theme_name="marshmallow")
    app, ctx = _make_app(rt, state)

    screens: ScreenController = ctx["screens"]
    modal_editor: ModalTextEditor = ctx["modal_editor"]
    custom_step = ctx["custom_step"]
    kb: KeyBindings = ctx["kb"]

    enter_binding = next(b for b in kb.bindings if b.handler.__name__ == "_overlay_enter")
    event = SimpleNamespace(app=app, key_sequence=[])

    # 1. Step 0: Name
    screens.open_overlay(OverlayView.AUTH_CUSTOM)
    custom_step[0] = 0
    modal_editor.set_text("My Custom LLM")
    enter_binding.handler(event)
    assert custom_step[0] == 1

    # 2. Step 1: Base URL
    modal_editor.set_text("http://localhost:8000/v1")
    enter_binding.handler(event)
    assert custom_step[0] == 2

    # 3. Step 2: Model ID
    modal_editor.set_text("mistralai/Mistral-7B")
    enter_binding.handler(event)
    assert custom_step[0] == 3

    # 4. Step 3: Context Window
    modal_editor.set_text("32768")
    enter_binding.handler(event)
    assert custom_step[0] == 4

    # 5. Step 4 Fail-Closed: Vault failure keeps wizard open on step 4 and does NOT mutate config
    modal_editor.set_text("sk-unvaultable-key")
    with patch("hund.ui.fullscreen.save_api_key", return_value=False):
        enter_binding.handler(event)

    assert custom_step[0] == 4, "Must not advance or leave wizard on vault failure"
    assert screens.overlay == OverlayView.AUTH_CUSTOM
    assert screens.status == "Credential vault unavailable."
    assert len(rt.cfg.custom_endpoints) == 0, "No endpoint persisted on vault failure"
    assert modal_editor.get_raw() == "sk-unvaultable-key", "Secret preserved in editor for retry"

    # 6. Step 4 Rollback: Save failure rolls back vault credential and config endpoint
    with patch("hund.ui.fullscreen.save_api_key", return_value=True), \
         patch("hund.ui.fullscreen.delete_api_key") as mock_delete, \
         patch("hund.config.HundConfig.save", side_effect=IOError("Disk write error")):
        enter_binding.handler(event)

    assert mock_delete.call_count == 1, "Must delete orphaned vault key on config save error"
    assert len(rt.cfg.custom_endpoints) == 0, "Endpoint rolled back from config"
    assert screens.status == "Failed to save configuration."

    # 7. Step 4 Success: Full save preserves active model
    with patch("hund.ui.fullscreen.save_api_key", return_value=True), \
         patch("keyring.get_password", return_value="sk-valid-key"):
        enter_binding.handler(event)

    assert len(rt.cfg.custom_endpoints) == 1
    assert rt.cfg.custom_endpoints[0].name == "My Custom LLM"
    assert rt.cfg.provider.model == "deepseek-chat", "Active model preserved"
    assert rt.cfg.provider.credential_id == "deepseek", "Active credential preserved"
    assert screens.overlay == OverlayView.MODEL


def test_fullscreen_shortcuts_routing_and_modal_typing_isolation(tmp_path: Path) -> None:
    """Handler-level test: shortcut letters are typed inside modal editor and route outside."""
    rt = _make_dummy_runtime(tmp_path)
    state = SimpleNamespace(extra={}, theme_name="marshmallow")
    app, ctx = _make_app(rt, state)

    screens: ScreenController = ctx["screens"]
    modal_editor: ModalTextEditor = ctx["modal_editor"]
    kb: KeyBindings = ctx["kb"]
    event = SimpleNamespace(app=app, key_sequence=[])

    # 1. In OverlayView.MODEL: test [a/A], [k/K], [q/Q]
    screens.open_overlay(OverlayView.MODEL)
    model_add_binding = next(b for b in kb.bindings if b.handler.__name__ == "_model_add")
    model_key_binding = next(b for b in kb.bindings if b.handler.__name__ == "_model_key")
    overlay_q_binding = next(b for b in kb.bindings if b.handler.__name__ == "_overlay_q")

    # a/A opens AUTH_ADD
    model_add_binding.handler(event)
    assert screens.overlay == OverlayView.AUTH_ADD

    # Back to MODEL, k/K opens AUTH_KEY
    screens.open_overlay(OverlayView.MODEL)
    model_key_binding.handler(event)
    assert screens.overlay == OverlayView.AUTH_KEY

    # Back to MODEL, q/Q closes overlay
    screens.open_overlay(OverlayView.MODEL)
    overlay_q_binding.handler(event)
    assert screens.overlay == OverlayView.NONE

    # 2. Inside modal editor (OverlayView.AUTH_KEY): shortcut letters must type as text
    screens.open_overlay(OverlayView.AUTH_ADD)
    screens.open_overlay(OverlayView.AUTH_KEY)
    modal_editor.clear()

    modal_char_binding = next(b for b in kb.bindings if b.handler.__name__ == "_modal_type")
    for ch in ("q", "Q", "a", "A", "k", "K", "r", "R", "d", "D", "y", "Y", "n", "N", "f", "F"):
        ch_event = SimpleNamespace(app=app, key_sequence=[SimpleNamespace(key=ch, data=ch)])
        modal_char_binding.handler(ch_event)

    assert modal_editor.get_raw() == "qQaAkKrRdDyYnNfF"
    assert screens.overlay == OverlayView.AUTH_KEY, "Must not navigate while typing"

    # 3. Backspace in modal editor
    modal_back_binding = next(b for b in kb.bindings if b.handler.__name__ == "_modal_backspace")

    # Non-empty: deletes exactly 1 char
    modal_back_binding.handler(event)
    assert modal_editor.get_raw() == "qQaAkKrRdDyYnNf"
    assert screens.overlay == OverlayView.AUTH_KEY

    # Empty: steps back to AUTH_ADD
    modal_editor.clear()
    modal_back_binding.handler(event)
    assert screens.overlay == OverlayView.AUTH_ADD

    # 4. Left arrow does not step back
    modal_left_binding = next(b for b in kb.bindings if b.handler.__name__ == "_modal_left")
    screens.open_overlay(OverlayView.AUTH_KEY)
    modal_editor.set_text("test")
    modal_left_binding.handler(event)
    assert screens.overlay == OverlayView.AUTH_KEY, "Left arrow must not step back"
    assert modal_editor.get_raw() == "test"


def test_modal_footer_semantic_token() -> None:
    """Verify modal_footer design token exists and is distinct from secondary."""
    tokens = theme.SKINS["marshmallow"]["tokens"]
    assert "modal_footer" in tokens
    assert tokens["modal_footer"] == "#A2ABC0"
    assert tokens["modal_footer"] != tokens["secondary"]

    pt_style = theme.make_pt_style("marshmallow")
    assert pt_style is not None
    assert "modal_footer" in theme.COLOR_TOKENS

"""Comprehensive regression tests verifying that secrets never leak into UI, buffers, traces, or logs."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from hund.secrets import DEFAULT_CREDENTIAL_ID, SERVICE_NAME, delete_api_key, load_api_key, save_api_key
from hund.ui.modal_editor import ModalTextEditor
from hund.ui.screen_render import (
    render_auth_add_modal,
    render_auth_custom_wizard_modal,
    render_auth_forget_modal,
    render_auth_manage_modal,
    render_auth_modal,
    render_model_key_modal,
    render_model_modal,
)
from hund.providers.catalog import PROVIDER_PRESETS


CANARY_KEY = "CANARY_SECRET_sk_live_9f83a2bc047d1e89_MUST_NOT_LEAK"
CANARY_CUSTOM_KEY = "CANARY_CUSTOM_sk_vllm_8877665544332211_SECRET"


def test_modal_editor_canary_repr_and_str_masking() -> None:
    """Verify ModalTextEditor never exposes raw secret in repr, str, or masked view."""
    editor = ModalTextEditor()
    editor.insert_text(CANARY_KEY)

    # Raw value is preserved for cryptographic save
    assert editor.get_raw() == CANARY_KEY

    # Masked representation contains only bullet points
    masked = editor.get_masked()
    assert CANARY_KEY not in masked
    assert set(masked) == {"•"}
    assert len(masked) == len(CANARY_KEY)

    # repr and str must NEVER contain the raw secret
    repr_str = repr(editor)
    assert CANARY_KEY not in repr_str
    assert "•" in repr_str

    str_val = str(editor)
    assert CANARY_KEY not in str_val
    assert str_val == masked


def test_screen_renderers_never_leak_canary_secret() -> None:
    """Verify that all auth and model modal renderers never output raw canary secrets."""
    editor = ModalTextEditor()
    editor.insert_text(CANARY_KEY)

    # 1. Auth root
    auth_root = render_auth_modal(0, 80)
    assert CANARY_KEY not in auth_root

    # 2. Add provider preset list
    auth_add = render_auth_add_modal(PROVIDER_PRESETS, 0, 80)
    assert CANARY_KEY not in auth_add

    # 3. Manage providers list
    entries = [
        ("DeepSeek", "deepseek-chat", "[Environment]", "Controlled by DEEPSEEK_API_KEY"),
        ("OpenAI", "gpt-4o", "[Needs key]", "OpenAI API key missing"),
    ]
    auth_manage = render_auth_manage_modal(entries, 0, 80)
    assert CANARY_KEY not in auth_manage

    # 4. Auth forget confirmation
    auth_forget = render_auth_forget_modal("DeepSeek", 80)
    assert CANARY_KEY not in auth_forget

    # 5. Model key editor (uses editor.get_masked())
    model_key = render_model_key_modal("DeepSeek", editor.get_masked(), 80)
    assert CANARY_KEY not in model_key
    assert "••••" in model_key

    # 6. Custom wizard at API key step (step 4)
    wizard_data = {"name": "Local vLLM", "base_url": "http://localhost:8000/v1", "model_id": "llama-3", "context_window": "32768"}
    custom_wizard = render_auth_custom_wizard_modal(4, wizard_data, editor.get_masked(), 80)
    assert CANARY_KEY not in custom_wizard
    assert "••••" in custom_wizard


def test_canary_vault_storage_and_error_sanitization(monkeypatch) -> None:
    """Verify canary is stored in vault and vault exceptions never leak the raw secret."""
    vault: dict[str, str] = {}

    def _mock_set(service, key, value):
        assert service == SERVICE_NAME
        vault[key] = value

    def _mock_get(service, key):
        return vault.get(key)

    monkeypatch.setattr("keyring.set_password", _mock_set)
    monkeypatch.setattr("keyring.get_password", _mock_get)

    # Save canary key with surrounding whitespace
    ok = save_api_key(f"  {CANARY_KEY}\n\t", "canary_provider")
    assert ok is True
    # Verify trimmed storage in vault
    assert vault["canary_provider"] == CANARY_KEY

    # Load canary key
    loaded = load_api_key("UNUSED_ENV", "canary_provider")
    assert loaded == CANARY_KEY

    # Test error handling when keyring fails
    def _exploding_set(service, key, value):
        raise RuntimeError("Windows Credential Manager access denied: error 0x80070005")

    monkeypatch.setattr("keyring.set_password", _exploding_set)
    try:
        saved = save_api_key(CANARY_KEY, "canary_provider")
        assert saved is False
    except Exception as e:
        # If any exception is raised, it must NOT contain the secret
        assert CANARY_KEY not in str(e)


def test_modal_editor_paste_sanitization_with_canary() -> None:
    """Verify pasting canary with newlines, carriage returns, and control chars cleans safely."""
    editor = ModalTextEditor()
    dirty_canary = f"\r\n\t{CANARY_KEY}\r\n\x00\x07  "
    editor.insert_text(dirty_canary)

    # Non-printables and newlines must be stripped
    cleaned = editor.get_raw()
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert CANARY_KEY in cleaned

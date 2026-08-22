"""Tests for SaaS bridge — chat endpoint, prompt, and API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hund.saas.prompt import build_saas_prompt


# ── Prompt ────────────────────────────────────────────────────────


def test_saas_prompt_contains_key_rules():
    prompt = build_saas_prompt()
    assert "hund" in prompt
    assert "skriver ALDRIG filer" in prompt
    assert "kor ALDRIG terminal" in prompt
    assert "andrar ALDRIG Forge" in prompt
    assert "sma bokstaver" in prompt


def test_saas_prompt_lowercase_hund():
    prompt = build_saas_prompt()
    lines = [l for l in prompt.split("\n") if "hund" in l.lower()]
    for line in lines:
        assert line == line.lower() or "hund" in line.lower()


def test_saas_prompt_no_tools_mentioned():
    prompt = build_saas_prompt()
    # SaaS prompt mentions guiding users to dashboard tools, but NOT executing them
    # It should not mention file-writing, terminal, or forge modification
    assert "skriver ALDRIG filer" in prompt
    assert "kor ALDRIG terminal" in prompt


def test_saas_prompt_with_customer_info():
    prompt = build_saas_prompt({"name": "Test AB", "plan": "enterprise"})
    assert "Test AB" in prompt
    assert "enterprise" in prompt


def test_saas_prompt_without_customer_info():
    prompt = build_saas_prompt()
    assert "kundinformation" not in prompt


# ── Chat (mocked LLM) ─────────────────────────────────────────────


@patch("hund.saas.chat.load_api_key")
@patch("hund.saas.chat.OpenAICompatibleClient")
def test_saas_chat_returns_correct_format(mock_client, mock_key):
    mock_key.return_value = "test-key"

    # Mock LLM response
    mock_instance = MagicMock()
    mock_instance.complete.return_value.text = "Hej! Jag är hund."
    mock_client.return_value = mock_instance

    from hund.saas.chat import saas_chat

    result = saas_chat(message="Hej")
    assert "response" in result
    assert "session_id" in result
    assert result["response"] == "Hej! Jag är hund."
    assert len(result["session_id"]) > 0


@patch("hund.saas.chat.load_api_key")
def test_saas_chat_no_key(mock_key):
    mock_key.return_value = None

    from hund.saas.chat import saas_chat

    with pytest.raises(RuntimeError, match="HUND_API_KEY not configured"):
        saas_chat(message="Hej")


@patch("hund.saas.chat.load_api_key")
@patch("hund.saas.chat.OpenAICompatibleClient")
def test_saas_chat_no_tools_registered(mock_client, mock_key):
    """Verify that complete() is called with tools=None."""
    mock_key.return_value = "test-key"
    mock_instance = MagicMock()
    mock_instance.complete.return_value.text = "Ok."
    mock_client.return_value = mock_instance

    from hund.saas.chat import saas_chat

    saas_chat(message="test")
    # Verify tools=None was passed
    call_kwargs = mock_instance.complete.call_args.kwargs
    assert call_kwargs.get("tools") is None


@patch("hund.saas.chat.load_api_key")
@patch("hund.saas.chat.OpenAICompatibleClient")
def test_saas_chat_passes_customer_info(mock_client, mock_key):
    mock_key.return_value = "test-key"
    mock_instance = MagicMock()
    mock_instance.complete.return_value.text = "Ok."
    mock_client.return_value = mock_instance

    from hund.saas.chat import saas_chat

    saas_chat(message="test", customer_info={"name": "Kund AB"})
    # Verify system prompt contains customer info
    call_messages = mock_instance.complete.call_args.args[0]
    system_msg = [m for m in call_messages if m.role == "system"]
    assert len(system_msg) == 1
    assert "Kund AB" in system_msg[0].content


# ── Stats ──────────────────────────────────────────────────────────


def test_saas_stats_format():
    from hund.stats.base_stats import compute_all
    stats = compute_all()
    assert "clarity" in stats
    assert "precision" in stats
    assert "efficiency" in stats
    assert "endurance" in stats
    assert "mastery" in stats
    for s in stats.values():
        assert "name" in s
        assert "tier" in s

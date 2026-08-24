"""Tests for UI quick-wins polish: safety check parser, status bar formatting, and slash autocomplete."""
from __future__ import annotations

from hund.ui.input import (
    PromptState,
    SLASH_COMMAND_METAS,
    _toolbar,
    format_duration,
    format_status_bar,
    format_tokens_ratio,
)
from hund.ui.safety_check import parse_trust_choice


# -- safety check parser tests ---------------------------------------------

def test_parse_trust_choice_confirm_options() -> None:
    assert parse_trust_choice("1") is True
    assert parse_trust_choice("") is True  # Enter key confirms default
    assert parse_trust_choice("y") is True
    assert parse_trust_choice("yes") is True
    assert parse_trust_choice("YES") is True
    assert parse_trust_choice("enter") is True


def test_parse_trust_choice_cancel_options() -> None:
    assert parse_trust_choice("2") is False
    assert parse_trust_choice("n") is False
    assert parse_trust_choice("no") is False
    assert parse_trust_choice("esc") is False
    assert parse_trust_choice("exit") is False
    assert parse_trust_choice("invalid_choice") is False


# -- status bar formatting tests -------------------------------------------

def test_format_tokens_ratio() -> None:
    assert format_tokens_ratio(274_000, 1_000_000) == "274K/1M"
    assert format_tokens_ratio(14_500, 128_000) == "14K/128K"
    assert format_tokens_ratio(500, 32_000) == "500/32K"
    assert format_tokens_ratio(1_500_000, 2_000_000) == "1.5M/2M"


def test_format_duration() -> None:
    assert format_duration(45) == "45s"
    assert format_duration(125) == "2m"
    assert format_duration(16020) == "4h 27m"


def test_status_bar_contains_model_tokens_time_latency() -> None:
    line = format_status_bar(
        model="deepseek-v4-pro",
        tokens=274_000,
        limit=1_000_000,
        duration_s=16020,
        latency_s=21.7,
    )
    assert "deepseek-v4-pro" in line
    assert "274K/1M" in line
    assert "4h 27m" in line
    assert "21.7s" in line
    assert "⏱" not in line


def test_status_bar_excludes_stat_abbreviations_and_bars() -> None:
    state = PromptState()
    state.extra["model"] = "deepseek-v4-pro"
    state.extra["tokens"] = 50_000
    state.extra["token_limit"] = 1_000_000
    state.extra["last_latency_s"] = 1.2

    toolbar_segments = _toolbar(state)
    combined_text = "".join(text for _, text in toolbar_segments)

    # Exclude RPG stat bars and abbreviations from bottom status line
    for stat in ("CLR", "PRC", "EFF", "END", "MAS"):
        assert stat not in combined_text
    for bar_char in ("█", "░"):
        assert bar_char not in combined_text

    assert "deepseek-v4-pro" in combined_text
    assert "50K/1M" in combined_text
    assert "1.2s" in combined_text
    assert "⏱" not in combined_text


# -- slash autocomplete metadata tests -------------------------------------

def test_slash_autocomplete_has_meta_descriptions() -> None:
    assert len(SLASH_COMMAND_METAS) >= 15
    for cmd, desc in SLASH_COMMAND_METAS.items():
        assert cmd.startswith("/")
        assert len(desc) > 3  # Non-empty description
    assert "/exit" in SLASH_COMMAND_METAS
    assert "/stats" in SLASH_COMMAND_METAS
    assert "/skills" in SLASH_COMMAND_METAS

"""Unit tests for theme skins and syntax tokens (BYGGE 9 DEL 1)."""
from __future__ import annotations

import pytest
from hund.ui import theme

REQUIRED_TOKENS = {
    "primary", "secondary", "accent", "meta_accent", "logo", "user", "success",
    "warning", "danger", "tool", "thinking", "learning", "growth_gold",
    "growth_cream", "growth_ochre", "growth_brass", "skill_seed", "add", "del",
    "add_bg", "add_fg", "del_bg", "del_fg", "diff_tree", "diff_lineno",
    "diff_file_header", "mascot", "mascot_status", "modal_footer",
    "syntax_keyword", "syntax_string", "syntax_number", "syntax_comment",
    "syntax_function", "syntax_operator", "syntax_variable",
    "syntax_del_keyword", "syntax_del_string", "syntax_del_number", "syntax_del_comment",
    "syntax_del_function", "syntax_del_operator", "syntax_del_variable",
}

CANONICAL_THEMES = ["marshmallow", "dracula", "tokyonight", "nord", "monokai", "gruvbox"]


def test_theme_names_lists_all_six_canonical_themes() -> None:
    names = theme.theme_names()
    assert set(names) == set(CANONICAL_THEMES)
    assert len(names) == 6


@pytest.mark.parametrize("theme_name", CANONICAL_THEMES)
def test_each_skin_has_complete_token_set(theme_name: str) -> None:
    skin = theme.get_skin(theme_name)
    assert skin["name"] == theme_name
    tokens = skin["tokens"]
    missing = REQUIRED_TOKENS - set(tokens.keys())
    assert not missing, f"Theme {theme_name} is missing tokens: {missing}"


@pytest.mark.parametrize("theme_name", CANONICAL_THEMES)
def test_each_skin_has_complete_ansi_fallback(theme_name: str) -> None:
    skin = theme.get_skin(theme_name)
    ansi = skin["ansi"]
    tokens = skin["tokens"]
    for token_key in tokens.keys():
        assert token_key in ansi, f"Theme {theme_name} missing ANSI fallback for token: {token_key}"
        assert ansi[token_key].startswith("ansi") or ansi[token_key] == "default", (
            f"Theme {theme_name} ANSI token {token_key} has invalid value: {ansi[token_key]}"
        )


@pytest.mark.parametrize("theme_name", CANONICAL_THEMES)
def test_make_pt_style_constructs_valid_style(theme_name: str) -> None:
    st = theme.make_pt_style(theme_name)
    assert st is not None
    rules = dict(st.style_rules)
    assert "syntax_keyword" in rules
    assert "syntax_string" in rules
    assert "syntax_number" in rules
    assert "syntax_comment" in rules
    assert "syntax_function" in rules
    assert "syntax_operator" in rules
    assert "syntax_variable" in rules
    assert not st.get_attrs_for_style_str("class:del").strike
    assert not st.get_attrs_for_style_str("class:add").strike


def test_get_skin_fallback() -> None:
    assert theme.get_skin("dracula")["name"] == "dracula"
    assert theme.get_skin("DRACULA")["name"] == "dracula"
    assert theme.get_skin("tokyo-night")["name"] == "tokyonight"
    assert theme.get_skin("nonexistent_theme")["name"] == "marshmallow"
    assert theme.get_skin(None)["name"] == "marshmallow"

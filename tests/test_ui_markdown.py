"""Unit tests for UI markdown transformer, confirm parser, and diff rendering."""
from __future__ import annotations

from io import StringIO
from rich.console import Console

from hund.ui.output import parse_confirm_input, strip_markdown, transform_streaming_markdown
from hund.ui.render import render_diff


# -- markdown transformer tests --------------------------------------------

def test_transform_bold_to_ansi() -> None:
    text = transform_streaming_markdown("This is **bold** and __also bold__.")
    assert "**" not in text
    assert "__" not in text
    assert "\x1b[1mbold\x1b[22m" in text
    assert "\x1b[1malso bold\x1b[22m" in text


def test_transform_bullet_lists_to_unicode_bullet() -> None:
    text = transform_streaming_markdown("* first item\n* second item\n- third item")
    lines = text.splitlines()
    assert lines[0].startswith("• first item")
    assert lines[1].startswith("• second item")
    assert lines[2].startswith("• third item")


def test_transform_heading_markers_stripped() -> None:
    text = transform_streaming_markdown("# Heading 1\n## Heading 2\n### Heading 3")
    assert "#" not in text
    assert "Heading 1" in text
    assert "Heading 2" in text


def test_strip_markdown_helper() -> None:
    text = strip_markdown("* item with **bold** text and `code`")
    assert "**" not in text
    assert "`" not in text
    assert "• item with bold text and code" == text.strip()


# -- confirm parser tests --------------------------------------------------

def test_confirm_parser_approve() -> None:
    assert parse_confirm_input("y") == "approve"
    assert parse_confirm_input("yes") == "approve"
    assert parse_confirm_input("j") == "approve"
    assert parse_confirm_input("ja") == "approve"
    assert parse_confirm_input(" Y ") == "approve"


def test_confirm_parser_edit() -> None:
    assert parse_confirm_input("e") == "edit"
    assert parse_confirm_input("edit") == "edit"
    assert parse_confirm_input(" E ") == "edit"


def test_confirm_parser_session() -> None:
    assert parse_confirm_input("a") == "session"
    assert parse_confirm_input("all") == "session"
    assert parse_confirm_input("alla") == "session"


def test_confirm_parser_deny_and_empty() -> None:
    assert parse_confirm_input("n") == "deny"
    assert parse_confirm_input("no") == "deny"
    assert parse_confirm_input("nej") == "deny"
    assert parse_confirm_input("") == "deny"
    assert parse_confirm_input("random_invalid") == "deny"


# -- diff rendering tests --------------------------------------------------

def test_render_diff_green_additions_red_deletions() -> None:
    out = StringIO()
    console = Console(force_terminal=True, color_system="truecolor", width=120, file=out)
    old = "def foo():\n    return 1\n"
    new = "def foo():\n    return 2\n"
    render_diff(console, old, new, filename="test.py")
    res = out.getvalue()
    assert "DIFF: test.py" in res
    # Contains color codes for addition and deletion
    assert "return 2" in res
    assert "return 1" in res
    # Zero emojis
    assert all(ord(c) < 0x1F000 for c in res)

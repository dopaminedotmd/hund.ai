"""Tests for UI text handling, clipboard, multiline input, history, and keybindings."""
from __future__ import annotations

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory

from hund.ui import clipboard, theme
from hund.ui.fullscreen import _OutputLexer
from hund.ui.input import normalize_terminal_input
from hund.ui.keys import KEYMAP


@pytest.fixture(autouse=True)
def mock_in_memory_clipboard(monkeypatch):
    """Ensure clipboard operations in tests never touch the host OS clipboard."""
    store = {"text": ""}

    def _mock_copy(text: str) -> bool:
        store["text"] = text
        return True

    def _mock_paste() -> str:
        return store["text"]

    monkeypatch.setattr(clipboard, "copy_text", _mock_copy)
    monkeypatch.setattr(clipboard, "paste_text", _mock_paste)


def test_clipboard_copy_and_paste() -> None:
    """Test clipboard read/write operations with mocked store."""
    sample = "hund-test-clipboard-1234"
    ok = clipboard.copy_text(sample)
    assert ok is True
    pasted = clipboard.paste_text()
    assert pasted == sample


def test_output_lexer_preserves_user_class_across_blank_lines() -> None:
    """Test that multiline user prompts with code & blank lines stay class:user."""
    doc = Document(
        "  ❯ def hello_world():\n"
        "\n"
        "      x = 1\n"
        "      # comment with -\n"
        "      + 2\n"
        "\n"
        "      return x\n"
        "┌─ hund ────────────────────────────────────────────────────────┐\n"
        "│ Hello there!                                                  │\n"
        "└───────────────────────────────────────────────────────────────┘\n"
    )
    get_line = _OutputLexer().lex_document(doc)

    # Lines 0 to 6 are the user block
    for lineno in range(7):
        toks = get_line(lineno)
        assert len(toks) > 0
        assert toks[0][0] == "class:user", f"Line {lineno} failed: {toks}"

    # Line 7 is the assistant box top header
    toks_assistant = get_line(7)
    assert toks_assistant[0][0] != "class:user"


def test_output_lexer_handles_single_line_user_prompt() -> None:
    """Test single line user prompts get colored as class:user."""
    doc = Document(
        "  ❯ show me the status\n"
        "  ┊ ⟳ preparing stats…\n"
    )
    get_line = _OutputLexer().lex_document(doc)

    user_toks = get_line(0)
    assert user_toks[0][0] == "class:user"

    tool_toks = get_line(1)
    assert tool_toks[0][0] != "class:user"


def test_keymap_registry_has_enhanced_shortcuts() -> None:
    """Verify KEYMAP in keys.py documents history, paste, undo/redo, and scrolling."""
    chat_keys = {item["key"]: item["action"] for item in KEYMAP["Chat Input"]}
    assert "Ctrl+V" in chat_keys
    assert "Up / Down" in chat_keys
    assert "Ctrl+Z / Ctrl+Y" in chat_keys
    assert chat_keys["Ctrl+C"] == "Cancel active work or clear the current line"
    assert "exit" not in chat_keys["Ctrl+C"].casefold()

    nav_keys = {item["key"]: item["action"] for item in KEYMAP["Navigation & Scrolling"]}
    assert any("Shift+Up" in k for k in nav_keys)


def test_terminal_input_normalizes_windows_surrogate_pairs_before_history() -> None:
    """A Win32 UTF-16 surrogate pair must become one valid Unicode scalar."""
    raw = 'print("Building the app \ud83d\ude80")'

    normalized = normalize_terminal_input(raw)

    assert normalized == 'print("Building the app 🚀")'
    assert normalized.encode("utf-8")
    history = InMemoryHistory()
    history.append_string(normalized)
    assert history.get_strings() == [normalized]


def test_terminal_input_replaces_only_unpaired_surrogates() -> None:
    """Malformed lone surrogates are made safe without changing valid text."""
    raw = "before \ud83d middle \ude80 after åäö"

    assert normalize_terminal_input(raw) == "before � middle � after åäö"
    assert normalize_terminal_input("already valid 🚀 åäö") == "already valid 🚀 åäö"


def test_user_input_echo_sanitization() -> None:
    """Verify tabs are expanded to 4 spaces and carriage returns stripped."""
    import re
    import textwrap

    raw_input = "\tdef foo():\r\n\t\tx = 1\r\n\r\n\t\treturn x"
    w = 80
    wrapped_lines: list[str] = []
    for raw_line in raw_input.splitlines():
        clean_l = raw_line.replace("\t", "    ").rstrip("\r")
        clean_l = "".join(ch for ch in clean_l if ch >= " " or ch == "\t")
        if not clean_l.strip():
            wrapped_lines.append("")
        elif len(clean_l) <= w:
            wrapped_lines.append(clean_l)
        else:
            indent_match = re.match(r"^(\s*)", clean_l)
            lead_indent = indent_match.group(1) if indent_match else ""
            wrapped_lines.extend(
                textwrap.wrap(
                    clean_l,
                    width=w,
                    subsequent_indent=lead_indent,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [clean_l]
            )

    assert wrapped_lines[0] == "    def foo():"
    assert wrapped_lines[1] == "        x = 1"
    assert wrapped_lines[2] == ""
    assert wrapped_lines[3] == "        return x"


def test_history_navigation_with_memory_history() -> None:
    """Test buffer history backward and forward cycling across multiple entries."""
    from collections import deque

    hist = InMemoryHistory()
    hist.append_string("cmd 1")
    hist.append_string("cmd 2")
    hist.append_string("cmd 3")

    buf = Buffer(history=hist, enable_history_search=False)
    buf._working_lines = deque(list(hist.get_strings()) + [""])
    buf.working_index = len(buf._working_lines) - 1

    assert buf.text == ""

    buf.history_backward()
    assert buf.text == "cmd 3"

    buf.history_backward()
    assert buf.text == "cmd 2"

    buf.history_backward()
    assert buf.text == "cmd 1"

    buf.history_forward()
    assert buf.text == "cmd 2"

    buf.history_forward()
    assert buf.text == "cmd 3"

    buf.history_forward()
    assert buf.text == ""


def test_screen_controller_step_back_and_close() -> None:
    """Test hierarchical navigation: Backspace acts as browser back all the way to chat."""
    from hund.ui.screen_state import DestinationView, OverlayView, ScreenController

    screens = ScreenController()
    screens.open_destination(DestinationView.TOOLS)
    screens.detail["tools"] = "read_file"

    # Detail -> Backspace -> List
    res = screens.step_back()
    assert res == "detail"
    assert screens.detail.get("tools") is None
    assert screens.destination == DestinationView.TOOLS

    # List -> Backspace -> Closes to Chat
    res2 = screens.step_back()
    assert res2 == "destination"
    assert screens.destination == DestinationView.CHAT

    # Overlay Root -> Backspace -> Closes to Chat
    screens.open_overlay(OverlayView.THEME)
    res_theme = screens.step_back()
    assert res_theme == "overlay"
    assert screens.overlay == OverlayView.NONE

    # Nested model modal -> Backspace -> Parent modal
    screens.open_overlay(OverlayView.MODEL_CUSTOM)
    res_mod = screens.step_back()
    assert res_mod == "nested"
    assert screens.overlay == OverlayView.MODEL

    # Parent modal -> Backspace -> Closes to Chat
    res_mod_parent = screens.step_back()
    assert res_mod_parent == "overlay"
    assert screens.overlay == OverlayView.NONE


def test_screen_tokens_design_facit() -> None:
    """Test that _SCREEN_TOKEN_RE correctly matches column headers, badges, and labels."""
    from hund.ui.fullscreen import _SCREEN_TOKEN_RE

    text = "TOOL CATEGORY SAFETY LEVEL DISPATCH [safe] [dangerous] [moderate] Domain: Lv.3"
    matches = {m.lastgroup: m.group(0) for m in _SCREEN_TOKEN_RE.finditer(text)}

    assert "meta_label" in matches
    assert "good" in matches
    assert "bad" in matches
    assert "warning" in matches
    assert "label" in matches


def test_format_runtime_error() -> None:
    """Test clean plain text formatting of API 401, 402, 429, and connection errors without box borders."""
    from hund.ui.fullscreen import _format_runtime_error

    e401 = RuntimeError('Provider HTTP 401 — {"error":{"message":"Authentication Fails, Your api key: 8ecf is invalid","type":"authenticationerror","param":null,"code":"invalidrequest_error"}}')
    out401 = _format_runtime_error(e401)
    assert "API Authentication Error (HTTP 401)" in out401
    assert "Invalid or missing API key." in out401
    assert "/setup" in out401
    assert "╭─" not in out401
    assert "│" not in out401

    e402 = RuntimeError("Provider HTTP 402 — invalid_request_error: Insufficient Balance")
    out402 = _format_runtime_error(e402)
    assert "API Quota / Balance Error (HTTP 402)" in out402
    assert "Account has insufficient balance" in out402
    assert "╭─" not in out402

    e429 = RuntimeError("Provider HTTP 429 — Rate limit reached")
    out429 = _format_runtime_error(e429)
    assert "API Rate Limit Error (HTTP 429)" in out429
    assert "╭─" not in out429

    str_err = "Provider HTTP 401 — Invalid API key"
    out_str = _format_runtime_error(str_err)
    assert "API Authentication Error (HTTP 401)" in out_str
    assert "╭─" not in out_str


def test_resolve_slash_command_prefix_and_args() -> None:
    """Test slash command auto-resolution for prefixes and argument preservation."""
    from hund.ui.input import resolve_slash_command

    assert resolve_slash_command("/mod") == "/model"
    assert resolve_slash_command("/mod deepseek") == "/model deepseek"
    assert resolve_slash_command("/sk") == "/skills"
    assert resolve_slash_command("/the") == "/theme"
    assert resolve_slash_command("/sta") == "/stats"
    assert resolve_slash_command("/ex") == "/exit"
    assert resolve_slash_command("/us") == "/usage"
    assert resolve_slash_command("/doc") == "/doctor"
    assert resolve_slash_command("not a slash") == "not a slash"


def test_select_all_and_cut_in_buffer() -> None:
    """Test Ctrl+A selection range and Ctrl+X cut in prompt buffer with mocked clipboard."""
    buf = Buffer()
    buf.insert_text("hello hund world")
    assert buf.text == "hello hund world"

    # Select all
    buf.cursor_position = 0
    buf.start_selection()
    buf.cursor_position = len(buf.text)

    r = buf.document.selection_range()
    assert r == (0, len("hello hund world"))
    assert buf.text[r[0]:r[1]] == "hello hund world"

    # Cut
    clipboard.copy_text(buf.text[r[0]:r[1]])
    buf.cut_selection()
    assert buf.text == ""
    assert clipboard.paste_text() == "hello hund world"


def test_selection_delete_and_replace() -> None:
    """Test deleting selection on backspace and replacing with typed characters."""
    buf = Buffer()
    buf.insert_text("replace this entire sentence")
    buf.cursor_position = 0
    buf.start_selection()
    buf.cursor_position = len(buf.text)

    r = buf.document.selection_range()
    assert r == (0, len("replace this entire sentence"))

    # Delete selection
    start, end = r
    buf.text = buf.text[:start] + buf.text[end:]
    buf.cursor_position = start
    buf.exit_selection()
    assert buf.text == ""
    assert buf.selection_state is None

    # Replace selection with character
    buf.insert_text("foo bar")
    buf.cursor_position = 0
    buf.start_selection()
    buf.cursor_position = len(buf.text)
    r = buf.document.selection_range()
    start, end = r
    buf.text = buf.text[:start] + "Z" + buf.text[end:]
    buf.cursor_position = start + 1
    buf.exit_selection()
    assert buf.text == "Z"
    assert buf.selection_state is None


def test_delete_word_before_cursor() -> None:
    """Test deleting words backwards (Ctrl+W)."""
    buf = Buffer()
    buf.insert_text("alpha beta gamma")

    pos = buf.document.find_previous_word_beginning(count=1)
    assert pos == -5
    buf.delete_before_cursor(count=-pos)
    assert buf.text == "alpha beta "

    pos = buf.document.find_previous_word_beginning(count=1)
    buf.delete_before_cursor(count=-pos)
    assert buf.text == "alpha "


def test_semantic_screen_fragments_footer_styling() -> None:
    """Test that modal and fullscreen footers are styled as class:secondary."""
    from datetime import date, timedelta
    from hund.ui.fullscreen import _semantic_screen_fragments
    from hund.ui.screen_render import render_model_modal, render_stats
    from hund.providers.catalog import MODEL_OPTIONS
    from hund.ui.snapshots import StatsSnapshot

    # Modal with wrapped footer lines
    modal_rendered = render_model_modal(MODEL_OPTIONS, "deepseek-chat", 0, 50)
    fragments = _semantic_screen_fragments(modal_rendered)

    # Check footer line fragments
    footer_fragments = [frag for frag in fragments if "Back" in frag[1] or "Close" in frag[1]]
    assert len(footer_fragments) > 0
    for style, text in footer_fragments:
        assert style == "class:modal_footer"

    # Fullscreen stats
    today = date(2026, 8, 25)
    stats_snap = StatsSnapshot(
        "0.2.0", (), (), (0,) * 7,
        tuple(today - timedelta(days=n) for n in range(6, -1, -1)),
        (), False,
    )
    stats_rendered = render_stats(stats_snap, width=80, height=24)
    stats_frags = _semantic_screen_fragments(stats_rendered)
    stats_footer = [frag for frag in stats_frags if "[←] Back" in frag[1] or "[Esc/q] Close" in frag[1]]
    assert len(stats_footer) > 0
    for style, text in stats_footer:
        assert style == "class:modal_footer"


def test_all_screens_have_standard_back_and_close_footer() -> None:
    """Verify all screens and modals have standardized navigation footers."""
    from hund.ui.screen_render import (
        render_stats, render_usage, render_skills, render_tools,
        render_theme_modal, render_model_modal, render_model_custom_modal, render_model_key_modal
    )
    from hund.ui.snapshots import (
        StatsSnapshot, UsageSnapshot, SessionUsage,
        SkillsSnapshot, ToolsSnapshot
    )
    from hund.providers.catalog import MODEL_OPTIONS
    from datetime import date, timedelta

    today = date(2026, 8, 25)
    stats_snap = StatsSnapshot(
        "0.2.0", (), (), (0,) * 7,
        tuple(today - timedelta(days=n) for n in range(6, -1, -1)),
        (), False,
    )
    usage_snap = UsageSnapshot((), date(2026, 2, 1), today, None, SessionUsage(None, None, None))
    skills_snap = SkillsSnapshot((), (), 8)
    tools_snap = ToolsSnapshot((), ())

    # Stats
    s = render_stats(stats_snap, width=80, height=24)
    assert "[←] Back · [Esc/q] Close" in s
    s_ascii = render_stats(stats_snap, width=80, height=24, ascii_only=True)
    assert "<- Back * [Esc/q] Close" in s_ascii

    # Usage
    u = render_usage(usage_snap, width=80, height=24)
    assert "[←] Back · [Esc/q] Close" in u

    # Skills
    sk = render_skills(skills_snap, width=80, height=24)
    assert "[←] Back · [Esc/q] Close" in sk

    # Tools
    t = render_tools(tools_snap, width=80, height=24)
    assert "[←] Back · [Esc/q] Close" in t

    # Theme
    th = render_theme_modal("marshmallow", 0, 80)
    assert "[←] Back · [Esc/q] Close" in th

    # Model
    m = render_model_modal(MODEL_OPTIONS, "deepseek-chat", 0, 80)
    assert "[←] Back · [Esc/q] Close" in m

    # Custom model
    mc = render_model_custom_modal("", 80)
    assert "[←] Back · [Esc/q] Close" in mc

    # Key modal
    mk = render_model_key_modal("DeepSeek", "", 80)
    assert "[←] Back · [Esc/q] Close" in mk


def test_multiline_input_height_bounded_to_6_lines() -> None:
    """Test that input height calculates correctly and caps at 6 lines."""
    from prompt_toolkit.buffer import Buffer

    buf = Buffer()
    paste_folded = [False]

    def _calc_height(width: int = 80) -> int:
        if paste_folded[0]:
            return 1
        text = buf.text
        if not text:
            return 1
        w = max(width - 4, 15)
        lines = text.split("\n")
        total_rows = 0
        for l in lines:
            if not l:
                total_rows += 1
            else:
                total_rows += max(1, (len(l) + w - 1) // w)
        return min(max(total_rows, 1), 6)

    # Empty text -> 1
    assert _calc_height() == 1

    # 3 short lines -> 3
    buf.text = "line1\nline2\nline3"
    assert _calc_height() == 3

    # 10 lines -> bounded to 6
    buf.text = "\n".join(f"line {i}" for i in range(10))
    assert _calc_height() == 6

    # When folded with F2 -> 1 line
    paste_folded[0] = True
    assert _calc_height() == 1
    # Raw buffer text remains 100% intact!
    assert len(buf.text.splitlines()) == 10


def test_delete_last_word_behavior() -> None:
    def _delete_last_word(text: str) -> str:
        if not text:
            return ""
        i = len(text)
        while i > 0 and text[i - 1].isspace():
            i -= 1
        if i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
            while i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
                i -= 1
        elif i > 0 and not text[i - 1].isspace():
            while i > 0 and not text[i - 1].isalnum() and not text[i - 1].isspace() and text[i - 1] != "_":
                i -= 1
        return text[:i]

    assert _delete_last_word("hello world") == "hello "
    assert _delete_last_word("hello ") == ""
    assert _delete_last_word("sk-proj-123456") == "sk-proj-"
    assert _delete_last_word("sk-proj-") == "sk-proj"
    assert _delete_last_word("https://api.openai.com/v1") == "https://api.openai.com/"
    assert _delete_last_word("") == ""

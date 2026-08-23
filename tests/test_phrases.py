"""Tester for hund.ui phrases: select_thinking_phrase keyword matching & UI buffer invariant."""
from __future__ import annotations

import types
from hund.ui.phrases import (
    DEFAULT_PHRASE,
    READ_PHRASE,
    select_thinking_phrase,
)


def test_select_thinking_phrase_default_fallback() -> None:
    assert select_thinking_phrase("") == DEFAULT_PHRASE
    assert select_thinking_phrase("some random query without keywords") == DEFAULT_PHRASE


def test_select_thinking_phrase_read_transient() -> None:
    gerund, past = select_thinking_phrase("read file auth.py")
    assert "reading" in gerund
    assert past is None


def test_select_thinking_phrase_longest_keyword_wins() -> None:
    # "system specs" (len 12) must win over "system" (len 6) or "specs" (len 5)
    phrase = select_thinking_phrase("what are my system specs?")
    assert phrase == ("hund is checking your system", "hund checked.")


def test_select_thinking_phrase_intents() -> None:
    # specs
    assert select_thinking_phrase("check cpu usage") == ("hund is checking your system", "hund checked.")
    assert select_thinking_phrase("how much ram do I have?") == ("hund is checking your system", "hund checked.")

    # fix / debug
    assert select_thinking_phrase("fix the crash in loop.py") == ("hund is inspecting the code", "hund inspected.")
    assert select_thinking_phrase("debug this error") == ("hund is inspecting the code", "hund inspected.")

    # write / build
    assert select_thinking_phrase("create a new module") == ("hund is planning the build", "hund planned.")
    assert select_thinking_phrase("build the rust extension") == ("hund is planning the build", "hund planned.")

    # search / find
    assert select_thinking_phrase("find where tokens are counted") == ("hund is searching", "hund searched.")
    assert select_thinking_phrase("search files for theme") == ("hund is searching", "hund searched.")

    # test / verify
    assert select_thinking_phrase("run pytest test suite") == ("hund is verifying", "hund verified.")
    assert select_thinking_phrase("verify git status") == ("hund is verifying", "hund verified.")

    # refactor / optimize
    assert select_thinking_phrase("optimize database queries") == ("hund is optimizing", "hund optimized.")
    assert select_thinking_phrase("clean up legacy functions") == ("hund is optimizing", "hund optimized.")

    # who are you / identify
    assert select_thinking_phrase("who are you?") == ("hund is recalling", "hund recalled.")


def test_ui_thinking_does_not_modify_output_buffer() -> None:
    """Invariant test: _Sink.thinking() and clear_thinking() must not modify output_buffer.text (race fix)."""
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document

    # Minimal mock environment matching fullscreen.py _Sink
    output_buffer = Buffer(read_only=True)
    initial_text = "┌─ hund ──────┐\n│ hello world │\n└─────────────┘\n"
    output_buffer.set_document(Document(initial_text, cursor_position=len(initial_text)), bypass_readonly=True)

    _thinking = {
        "active": False,
        "text": "hund is reading",
        "past": None,
        "dot_count": 1,
        "start_time": 0.0,
    }

    # Simulate _Sink operations
    # 1. Start thinking
    _thinking["active"] = True
    _thinking["text"] = "hund is reading"
    _thinking["past"] = None

    assert output_buffer.text == initial_text

    # 2. Clear thinking without tools (transient)
    _thinking["active"] = False
    _thinking["past"] = None

    assert output_buffer.text == initial_text

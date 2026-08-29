from __future__ import annotations

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.keys import Keys

from hund.ui.modal_editor import ModalTextEditor
from hund.ui.screen_state import DestinationView, OverlayView, ScreenController


def test_modal_editor_insert_and_masking() -> None:
    editor = ModalTextEditor()
    editor.insert_text("sk-ant-api03-secretkey123")
    assert editor.get_raw() == "sk-ant-api03-secretkey123"
    assert editor.get_masked() == "•" * len("sk-ant-api03-secretkey123")
    assert "secretkey" not in editor.get_masked()


def test_modal_editor_paste_sanitization() -> None:
    editor = ModalTextEditor()
    # Pasted string with \r\n and control characters
    pasted = "  sk-proj-abc123xyz\r\n\t\x00\x1b  "
    editor.insert_text(pasted)
    assert "\r" not in editor.get_raw()
    assert "\n" not in editor.get_raw()
    assert "\x00" not in editor.get_raw()
    assert "\x1b" not in editor.get_raw()
    assert editor.get_raw() == "  sk-proj-abc123xyz   "


def test_modal_editor_word_deletion_tokens() -> None:
    editor = ModalTextEditor()

    # Hyphenated API key tokens
    editor.set_text("sk-proj-123456")
    editor.delete_word()
    assert editor.get_raw() == "sk-proj-"
    editor.delete_word()
    assert editor.get_raw() == "sk-proj"
    editor.delete_word()
    assert editor.get_raw() == "sk-"
    editor.delete_word()
    assert editor.get_raw() == "sk"
    editor.delete_word()
    assert editor.get_raw() == ""

    # URLs and Paths
    editor.set_text("https://api.openai.com/v1")
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai.com/"
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai.com"
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai."
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai"
    editor.delete_word()
    assert editor.get_raw() == "https://api."
    editor.delete_word()
    assert editor.get_raw() == "https://api"
    editor.delete_word()
    assert editor.get_raw() == "https://"
    editor.delete_word()
    assert editor.get_raw() == "https"
    editor.delete_word()
    assert editor.get_raw() == ""

    # Multiple trailing spaces
    editor.set_text("hello     world")
    editor.delete_word()
    assert editor.get_raw() == "hello     "
    editor.delete_word()
    assert editor.get_raw() == ""


def test_chat_input_buffer_word_deletion_in_middle() -> None:
    buf = Buffer()
    buf.text = "first second third"
    # Put cursor right after 'second'
    buf.cursor_position = len("first second")

    pos = buf.cursor_position
    before = buf.text[:pos]
    new_before = ModalTextEditor.calc_deleted_word(before)
    deleted_count = len(before) - len(new_before)
    buf.delete_before_cursor(count=deleted_count)

    assert buf.text == "first  third"


def test_backspace_vs_left_arrow_navigation_isolation() -> None:
    screens = ScreenController()
    screens.open_destination(DestinationView.SKILLS)
    screens.detail["skills"] = "test_skill"

    # Physical Backspace steps back in hierarchy: Detail -> Skills list -> Chat
    assert screens.step_back() == "detail"
    assert screens.detail.get("skills") is None
    assert screens.destination == DestinationView.SKILLS

    assert screens.step_back() == "destination"
    assert screens.destination == DestinationView.CHAT

    # Overlay hierarchy
    screens.open_overlay(OverlayView.AUTH)
    screens.open_overlay(OverlayView.AUTH_ADD)
    screens.open_overlay(OverlayView.AUTH_KEY)

    assert screens.step_back() == "nested"
    assert screens.overlay == OverlayView.AUTH_ADD

    assert screens.step_back() == "nested"
    assert screens.overlay == OverlayView.AUTH

    assert screens.step_back() == "overlay"
    assert screens.overlay == OverlayView.NONE

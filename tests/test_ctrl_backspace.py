"""Tests for Ctrl+Backspace / Ctrl+W / Alt+Backspace word deletion behavior."""
from __future__ import annotations

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document

from hund.ui.modal_editor import ModalTextEditor


def test_modal_editor_calc_deleted_word_various_patterns() -> None:
    # Python code / function call
    assert ModalTextEditor.calc_deleted_word("def calculate_total(items):") == "def calculate_total(items"
    assert ModalTextEditor.calc_deleted_word("def calculate_total(items") == "def calculate_total("
    assert ModalTextEditor.calc_deleted_word("def calculate_total(") == "def calculate_total"
    assert ModalTextEditor.calc_deleted_word("def calculate_total") == "def "
    assert ModalTextEditor.calc_deleted_word("def ") == ""
    assert ModalTextEditor.calc_deleted_word("def") == ""

    # Paths and URLs
    assert ModalTextEditor.calc_deleted_word("c:\\Users\\William\\hund.ai") == "c:\\Users\\William\\hund."
    assert ModalTextEditor.calc_deleted_word("c:\\Users\\William\\hund.") == "c:\\Users\\William\\hund"
    assert ModalTextEditor.calc_deleted_word("c:\\Users\\William\\hund") == "c:\\Users\\William\\"
    assert ModalTextEditor.calc_deleted_word("c:\\Users\\William\\") == "c:\\Users\\William"
    assert ModalTextEditor.calc_deleted_word("https://api.deepseek.com/v1/chat") == "https://api.deepseek.com/v1/"

    # API keys with hyphens
    assert ModalTextEditor.calc_deleted_word("sk-proj-abc-123") == "sk-proj-abc-"
    assert ModalTextEditor.calc_deleted_word("sk-proj-abc-") == "sk-proj-abc"


def test_buffer_word_deletion_simulation() -> None:
    buf = Buffer()
    buf.set_document(Document("hello world test", 16))

    # Simulate deleting 'test'
    pos = buf.cursor_position
    before = buf.text[:pos]
    new_before = ModalTextEditor.calc_deleted_word(before)
    deleted_count = len(before) - len(new_before)
    buf.delete_before_cursor(count=deleted_count)
    assert buf.text == "hello world "

    # Simulate deleting 'world ' (skips trailing space and deletes word)
    pos = buf.cursor_position
    before = buf.text[:pos]
    new_before = ModalTextEditor.calc_deleted_word(before)
    deleted_count = len(before) - len(new_before)
    buf.delete_before_cursor(count=deleted_count)
    assert buf.text == "hello "

    # Simulate deleting 'hello '
    pos = buf.cursor_position
    before = buf.text[:pos]
    new_before = ModalTextEditor.calc_deleted_word(before)
    deleted_count = len(before) - len(new_before)
    buf.delete_before_cursor(count=deleted_count)
    assert buf.text == ""


def test_modal_editor_word_deletion_edge_cases() -> None:
    """Test ModalTextEditor delete_word and delete_char methods."""
    editor = ModalTextEditor("https://api.openai.com/v1/chat")

    # delete_char
    editor.delete_char()
    assert editor.get_raw() == "https://api.openai.com/v1/cha"

    # delete_word removes "cha"
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai.com/v1/"

    # delete_word removes "/"
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai.com/v1"

    # delete_word removes "v1"
    editor.delete_word()
    assert editor.get_raw() == "https://api.openai.com/"

    # delete_word on empty string
    empty_editor = ModalTextEditor("")
    empty_editor.delete_word()
    assert empty_editor.get_raw() == ""
    empty_editor.delete_char()
    assert empty_editor.get_raw() == ""

    # whitespace only
    ws_editor = ModalTextEditor("     ")
    ws_editor.delete_word()
    assert ws_editor.get_raw() == ""

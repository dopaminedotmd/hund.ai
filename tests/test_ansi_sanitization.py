"""Tests for ANSI/CSI/OSC stream sanitization and display safety."""
import pytest
from hund.ui.unicode_cells import (
    AnsiStreamSanitizer,
    sanitize_display_line,
    strip_ansi_sequences,
)


def test_strip_ansi_csi_colors():
    raw = "\x1b[31;1mError:\x1b[0m Failed to execute"
    assert strip_ansi_sequences(raw) == "Error: Failed to execute"


def test_strip_ansi_osc_titles_and_hyperlinks():
    # OSC title
    title_raw = "\x1b]0;Terminal Title\x07Hello"
    assert strip_ansi_sequences(title_raw) == "Hello"

    # OSC 8 Hyperlink with BEL
    link_bel = "\x1b]8;;https://example.com\x07Link Text\x1b]8;;\x07"
    assert strip_ansi_sequences(link_bel) == "Link Text"

    # OSC 8 Hyperlink with String Terminator (ST = ESC \)
    link_st = "\x1b]8;;https://example.com\x1b\\Link Text\x1b]8;;\x1b\\"
    assert strip_ansi_sequences(link_st) == "Link Text"


def test_stream_sanitizer_split_sequences():
    sanitizer = AnsiStreamSanitizer()

    # Split CSI sequence: "\x1b[3" in chunk 1, "1mRed Text\x1b[0m" in chunk 2
    out1 = sanitizer.feed("\x1b[3")
    assert out1 == ""  # buffered

    out2 = sanitizer.feed("1mRed Text\x1b[0m")
    assert out2 == "Red Text"

    # Trailing bare ESC
    out3 = sanitizer.feed("More\x1b")
    assert out3 == "More"

    # Completed sequence
    out4 = sanitizer.feed("[32mGreen\x1b[0m")
    assert out4 == "Green"

    # Clean EOF discard of malformed / unterminated sequence
    out5 = sanitizer.feed("End\x1b[")
    assert out5 == "End"
    flushed = sanitizer.flush()
    assert flushed == ""


def test_sanitize_display_line_preserves_literal_brackets():
    # Literal "[31m" without ESC should be preserved as user prose
    prose = "The regex matched [31m in the text."
    cleaned = sanitize_display_line(prose)
    assert cleaned == "The regex matched [31m in the text."

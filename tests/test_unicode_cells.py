"""Tests for unicode_cells: grapheme cluster slicing, safe cell width measurement, and wrapping."""
import pytest
from hund.ui.unicode_cells import (
    cell_width,
    iter_grapheme_clusters,
    sanitize_display_line,
    slice_cells,
    wrap_cells,
)


def test_cell_width_ascii_and_empty():
    assert cell_width("") == 0
    assert cell_width("hello") == 5
    assert cell_width("a b c") == 5


def test_cell_width_cjk_and_emojis():
    # CJK characters are width 2
    assert cell_width("你好") == 4
    assert cell_width("世界") == 4
    # Standard emoji
    assert cell_width("🚀") >= 1
    assert cell_width("hund 🐶") >= 6


def test_combining_marks_and_variation_selectors():
    # e + combining acute accent -> é (1 visual cell)
    combined_e = "e\u0301"
    assert cell_width(combined_e) == 1
    clusters = list(iter_grapheme_clusters(combined_e))
    assert len(clusters) == 1
    assert clusters[0] == combined_e

    # Swedish å ä ö
    assert cell_width("smörgåsbord") == 11


def test_slice_cells_without_breaking_clusters():
    # Slicing CJK: "你好世界" (2+2+2+2 = 8 cells)
    # Slicing at 3 cells should only yield "你" (2 cells), not half of "好"
    sliced, width = slice_cells("你好世界", 3)
    assert sliced == "你"
    assert width == 2

    # Slicing at 4 cells should yield "你好" (4 cells)
    sliced, width = slice_cells("你好世界", 4)
    assert sliced == "你好"
    assert width == 4

    # Slicing combining mark
    combined_str = "e\u0301cole"
    sliced, width = slice_cells(combined_str, 1)
    assert sliced == "e\u0301"
    assert width == 1


def test_sanitize_display_line_tabs_and_controls():
    # Tab expanded to 4 spaces
    assert sanitize_display_line("def\tfoo():") == "def    foo():"
    # Null byte and ANSI sequence stripped
    assert sanitize_display_line("hello\x00world\x1b[31m") == "helloworld"
    # Literal brackets without ESC preserved
    assert sanitize_display_line("hello [31m world") == "hello [31m world"
    # Newlines preserved
    assert sanitize_display_line("line1\nline2") == "line1\nline2"


def test_wrap_cells_preserves_empty_lines_and_wraps_long_tokens():
    text = "Line 1\n\nLine 3 is a bit longer and should wrap nicely when width is small"
    wrapped = wrap_cells(text, max_cells=20)
    assert "" in wrapped  # Empty line preserved!
    for line in wrapped:
        assert cell_width(line) <= 20

    # Unbreakable long word
    long_token = "https://verylongdomainname.example.com/some/extremely/deep/nested/path/to/resource"
    wrapped_long = wrap_cells(long_token, max_cells=15)
    assert len(wrapped_long) > 1
    for chunk in wrapped_long:
        assert cell_width(chunk) <= 15

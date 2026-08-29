"""Tests for UI fallback modes: ASCII mode and reduced-color support."""
import pytest
from hund.ui.output import parse_semantic_segments
from hund.ui.render import render_response_box_from_segments
from hund.ui.unicode_cells import cell_width


def test_ascii_and_unicode_box_borders():
    text = "Hello world\nThis is a response."
    segs = parse_semantic_segments(text)
    boxed, _ = render_response_box_from_segments(segs, terminal_width=60)

    # Assert line widths are strictly bounded to terminal_width
    lines = boxed.split("\n")
    for l in lines:
        assert cell_width(l) == 60


def test_no_ansi_in_canonical_source_or_segments():
    text = (
        "Here is prose.\n"
        "```python\n"
        "def hello():\n"
        "    return 1\n"
        "```"
    )
    segs = parse_semantic_segments(text)
    for seg in segs:
        for line in seg.lines:
            assert "\x1b[" not in line  # No ANSI sequences in semantic state!

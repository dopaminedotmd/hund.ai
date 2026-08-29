"""Tests for responsive geometry and mid-stream resize behavior."""
import pytest
from hund.ui.render import (
    box_bottom,
    box_top,
    render_response_box,
    render_response_box_from_segments,
    response_content_width,
    response_padding,
)
from hund.ui.output import parse_semantic_segments
from hund.ui.unicode_cells import cell_width


@pytest.mark.parametrize("width", [40, 48, 60, 80, 100, 120])
def test_response_box_widths_and_padding(width):
    padding = response_padding(width)
    cw = response_content_width(width)
    assert cw > 0
    assert cw + 2 * padding + 2 == width

    text = "Short line\nA somewhat longer line that will test responsive word wrapping across different terminal sizes."
    boxed = render_response_box(text, terminal_width=width)
    lines = boxed.split("\n")
    for line in lines:
        assert cell_width(line) == width


def test_box_top_and_bottom_alignment():
    for w in [40, 60, 80, 100]:
        top = box_top(w)
        bottom = box_bottom(w, meta="2.3s")
        assert cell_width(top) == w
        assert cell_width(bottom) == w


def test_mid_stream_resize_re_rendering_idempotence():
    text = (
        "Here is prose before code.\n"
        "```python\n"
        "def compute(data):\n"
        "    return sum(data)\n"
        "```\n"
        "Prose after code."
    )
    segs = parse_semantic_segments(text)

    # Render at width 80
    box_80, _ = render_response_box_from_segments(segs, terminal_width=80)
    for l in box_80.split("\n"):
        assert cell_width(l) == 80

    # Resize to width 50
    box_50, _ = render_response_box_from_segments(segs, terminal_width=50)
    for l in box_50.split("\n"):
        assert cell_width(l) == 50

    # Resize back to 80 - assert exact idempotence
    box_80_again, _ = render_response_box_from_segments(segs, terminal_width=80)
    assert box_80_again == box_80

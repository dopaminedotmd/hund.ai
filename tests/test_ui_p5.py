"""Tester for hund.ui P5: Response box side rails, deterministic word-wrap, and meta border."""
from __future__ import annotations

from io import StringIO
from rich.console import Console

from hund.ui.output import StreamingSink
from hund.ui.render import box_bottom, box_top, render_response_box, wrap_content


def test_wrap_content_deterministic_line_lengths() -> None:
    term_width = 80
    content_width = term_width - 4  # 76
    long_text = (
        "Hund is an autonomous AI agent engineered for deep developer workflows, "
        "local tool dispatching, code generation, and self-improving motor skills. "
        "Every single line inside the response box must be hard-wrapped deterministically."
    )
    wrapped = wrap_content(long_text, content_width)
    assert len(wrapped) > 1
    for line in wrapped:
        assert len(line) <= content_width
        assert len(line) <= term_width - 2


def test_wrap_content_preserves_empty_lines() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    wrapped = wrap_content(text, 76)
    assert "" in wrapped
    assert wrapped[0] == "First paragraph."
    assert wrapped[1] == ""
    assert wrapped[2] == "Second paragraph."


def test_wrap_content_unbreakable_long_word() -> None:
    long_url = "https://example.com/very/deep/nested/directory/structure/and/unbreakable/token/identifier/file.json"
    wrapped = wrap_content(long_url, 30)
    assert len(wrapped) == 1
    assert wrapped[0] == long_url


def test_render_response_box_short_compact() -> None:
    short_reply = "hund är vaken."
    box = render_response_box(short_reply, terminal_width=80)
    lines = box.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("┌─ hund ")
    assert lines[0].endswith("┐")
    assert lines[1].startswith("│ ")
    assert lines[1].endswith(" │")
    assert lines[2].startswith("└")
    assert lines[2].endswith("┘")

    # Assert all lines have identical compact width (< 80)
    w0 = len(lines[0])
    assert w0 < 80
    assert len(lines[1]) == w0
    assert len(lines[2]) == w0


def test_render_response_box_long_full_width() -> None:
    long_reply = (
        "Hund analyserar repot och ser flera ändringar i konfigurationen. "
        "Alla moduler har validerats och testats utan regressioner eller problem. "
        "Koden är optimerad och redo för produktion."
    )
    term_width = 80
    box = render_response_box(long_reply, terminal_width=term_width)
    lines = box.split("\n")
    assert len(lines) >= 4
    for line in lines:
        assert len(line) == term_width
        if line.startswith("│"):
            assert line.startswith("│ ")
            assert line.endswith(" │")


def test_box_bottom_meta_render() -> None:
    bottom_plain = box_bottom(80, meta=None)
    assert bottom_plain.startswith("└")
    assert bottom_plain.endswith("┘")
    assert len(bottom_plain) == 80

    bottom_meta = box_bottom(80, meta="2.3s")
    assert "2.3s ┘" in bottom_meta
    assert len(bottom_meta) == 80

    # Short box
    bottom_short = box_bottom(12, meta="2.3s")
    assert "└── 2.3s ┘" in bottom_short or "2.3s ┘" in bottom_short


def test_streaming_sink_renders_rails_and_meta() -> None:
    out = StringIO()
    console = Console(force_terminal=False, width=80, file=out)
    sink = StreamingSink(console, stream_delay_s=0)

    sink.chunk("hund svarar med sidolinjer.")
    sink.end_assistant()

    captured = out.getvalue()
    assert "┌─ hund " in captured
    assert "│ hund svarar med sidolinjer." in captured
    assert "│" in captured
    assert "└" in captured
    assert "┘" in captured

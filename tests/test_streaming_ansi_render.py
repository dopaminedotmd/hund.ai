"""Tests for streaming ANSI sanitization in the presentation rendering pipeline."""
from __future__ import annotations

from hund.ui.output import StreamingMarkdownFilter
from hund.ui.render import render_response_box_from_segments


def test_char_by_char_streaming_ansi_csi_sanitization() -> None:
    """Test feeding CSI color sequences 1 character at a time never flashes control fragments."""
    filter_instance = StreamingMarkdownFilter()
    sample = "Prefix \x1b[38;2;255;0;0mRED TEXT\x1b[0m Postfix"

    for i, ch in enumerate(sample):
        filter_instance.feed(ch)
        segs = filter_instance.get_segments()
        boxed, _ = render_response_box_from_segments(segs, terminal_width=80)

        # Inspect all rendered lines in this intermediate snapshot
        for line in boxed.split("\n"):
            # Raw control sequence indicators must never appear in rendered display text
            assert "\x1b" not in line
            # Intermediate fragments like '[38;2' or '0;0m' should not appear outside literal context
            assert "[38;2;" not in line
            assert ";255;0;0m" not in line

    # Final boxed output must contain the clean sanitized text
    final_boxed, _ = render_response_box_from_segments(filter_instance.get_segments(), terminal_width=80)
    assert "Prefix RED TEXT Postfix" in final_boxed

    # Canonical source must retain exact raw escape bytes verbatim
    assert filter_instance.canonical_source == sample


def test_char_by_char_streaming_ansi_osc_sanitization() -> None:
    """Test feeding OSC 8 hyperlinks and OSC title sequences 1 char at a time."""
    filter_instance = StreamingMarkdownFilter()
    sample = "Link: \x1b]8;;https://example.com/api\x1b\\API Docs\x1b]8;;\x1b\\ and title: \x1b]0;Title\x07Done"

    for ch in sample:
        filter_instance.feed(ch)
        segs = filter_instance.get_segments()
        boxed, _ = render_response_box_from_segments(segs, terminal_width=80)

        for line in boxed.split("\n"):
            assert "\x1b" not in line
            # The hidden URL in OSC 8 hyperlink should not flash visibly in box presentation
            assert "https://example.com/api" not in line
            assert "]0;Title" not in line

    final_boxed, _ = render_response_box_from_segments(filter_instance.get_segments(), terminal_width=80)
    assert "Link: API Docs and title: Done" in final_boxed
    assert filter_instance.canonical_source == sample


def test_literal_bracket_not_stripped_without_esc() -> None:
    """Test that literal bracket patterns like [31m without ESC remain visible."""
    filter_instance = StreamingMarkdownFilter()
    filter_instance.feed("Literal text [31m is preserved.")
    final_boxed, _ = render_response_box_from_segments(filter_instance.get_segments(), terminal_width=80)
    assert "Literal text [31m is preserved." in final_boxed


def test_fence_metadata_is_sanitized_without_mutating_canonical_source() -> None:
    """Provider-controlled language and filename metadata cannot inject terminal controls."""
    filter_instance = StreamingMarkdownFilter()
    sample = (
        "```python\x1b[31m "
        "report.py\x1b]8;;https://secret.example/path\x1b\\hidden\x1b]8;;\x1b\\\n"
        "print('safe')\n"
        "```\n"
    )

    for ch in sample:
        filter_instance.feed(ch)
        boxed, _ = render_response_box_from_segments(filter_instance.get_segments(), terminal_width=48)
        assert "\x1b" not in boxed
        assert "https://secret.example/path" not in boxed
        assert "]8;;" not in boxed

    boxed, line_meta = render_response_box_from_segments(filter_instance.get_segments(), terminal_width=48)
    assert "report.pyhidden" in boxed
    assert "print('safe')" in boxed
    assert all("\x1b" not in language for _, language in line_meta.values())
    assert filter_instance.canonical_source == sample


def test_incomplete_escape_in_fence_label_is_hidden_and_width_bounded() -> None:
    """Incomplete control sequences and oversized labels cannot escape response geometry."""
    filter_instance = StreamingMarkdownFilter()
    sample = "```python " + ("very-long-name-" * 10) + "\x1b[31\npass\n```\n"
    filter_instance.feed(sample)

    boxed, _ = render_response_box_from_segments(filter_instance.get_segments(), terminal_width=40)
    assert "\x1b" not in boxed
    assert "[31" not in boxed
    assert all(len(line) <= 40 for line in boxed.splitlines())
    assert filter_instance.canonical_source == sample

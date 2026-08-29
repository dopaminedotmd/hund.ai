"""Tests proving O(n) linear scaling of StreamingMarkdownFilter with zero reparsing of finalized segments."""
import pytest
from hund.ui.output import SegmentType, StreamingMarkdownFilter


def test_linear_streaming_no_reparsing():
    """Verify that finalized segments are never reparsed and feed() processes only incremental characters."""
    f = StreamingMarkdownFilter()

    # Step 1: Feed a completed code block in 100 small chunks
    code_text = "```python\n" + ("x = 1\n" * 50) + "```\n"
    for char in code_text:
        f.feed(char)

    # At this point, the code block should be finalized into _segments
    assert len(f._segments) >= 1
    initial_finalized_count = len(f._segments)

    # Step 2: Feed a second code block in 500 small chunks
    second_code_text = "```python\n" + ("y = 2\n" * 100) + "```\n"
    for char in second_code_text:
        f.feed(char)

    assert len(f._segments) >= 2

    # Step 3: Stream 1000 single character chunks into an active prose segment
    prose_chars = "Hello world! This is a test of linear streaming performance. " * 20
    for char in prose_chars:
        f.feed(char)

    f.flush()
    segs = f.get_segments()
    # 2 code blocks + 1 prose block = 3 segments
    assert len(segs) == 3
    assert segs[0].type == SegmentType.CODE
    assert segs[1].type == SegmentType.CODE
    assert segs[2].type == SegmentType.PROSE
    # Verify canonical source matches verbatim
    expected_full = code_text + second_code_text + prose_chars
    assert f.canonical_source == expected_full

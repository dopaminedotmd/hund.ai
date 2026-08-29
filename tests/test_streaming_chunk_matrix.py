"""Tests for StreamingMarkdownFilter: chunk boundary matrix, unterminated fences, and O(n) streaming."""
import pytest
from hund.ui.output import (
    SegmentType,
    StreamingMarkdownFilter,
    parse_semantic_segments,
)


def test_chunk_matrix_single_char_streaming():
    text = (
        "Here is some prose before.\n\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n\n"
        "And prose after."
    )
    # Stream character by character
    f = StreamingMarkdownFilter()
    emitted = []
    for ch in text:
        emitted.append(f.feed(ch))
    emitted.append(f.flush())

    assert f.canonical_source == text
    segs = f.get_segments()
    assert len(segs) == 3
    assert segs[0].type == SegmentType.PROSE
    assert segs[1].type == SegmentType.CODE
    assert segs[1].language == "python"
    assert "def add(a, b):" in segs[1].lines
    assert segs[2].type == SegmentType.PROSE


def test_split_fence_header_across_chunks():
    # Split opening fence: "`", "`", "`py", "thon\n"
    f = StreamingMarkdownFilter()
    f.feed("`")
    f.feed("`")
    f.feed("`py")
    f.feed("thon\nprint('hello')\n```\n")
    f.flush()

    segs = f.get_segments()
    assert len(segs) >= 1
    code_seg = next(s for s in segs if s.type == SegmentType.CODE)
    assert code_seg.language == "python"
    assert "print('hello')" in code_seg.lines
    assert not code_seg.is_open
    assert not code_seg.closed_by_eof


def test_split_closing_fence_across_chunks():
    # Split closing fence: "```\n"
    f = StreamingMarkdownFilter()
    f.feed("```python\nx = 1\n")
    f.feed("`")
    f.feed("`")
    f.feed("`\n")
    f.flush()

    segs = f.get_segments()
    assert len(segs) == 1
    assert segs[0].type == SegmentType.CODE
    assert not segs[0].is_open
    assert not segs[0].closed_by_eof


def test_crlf_normalization():
    text = "```bash\r\necho 'hi'\r\n```\r\n"
    f = StreamingMarkdownFilter()
    f.feed(text)
    f.flush()

    segs = f.get_segments()
    assert len(segs) == 1
    assert segs[0].type == SegmentType.CODE
    assert segs[0].language == "bash"
    assert "echo 'hi'" in segs[0].lines


def test_unterminated_fence_preserves_canonical_source_and_marks_closed_by_eof():
    # An unclosed code fence at stream end
    text = "```python\ndef incomplete():\n    pass"
    f = StreamingMarkdownFilter()
    f.feed(text)
    f.flush()

    assert f.canonical_source == text  # Exact verbatim preservation! No fake closing ``` appended!
    segs = f.get_segments()
    assert len(segs) == 1
    assert segs[0].type == SegmentType.CODE
    assert not segs[0].is_open
    assert segs[0].closed_by_eof is True  # Marked as closed by EOF


def test_linear_scaling_without_reparsing_finalized_segments():
    f = StreamingMarkdownFilter()
    # Feed 10 completed code blocks + prose
    for i in range(10):
        f.feed(f"Prose block {i}\n")
        f.feed(f"```python\n# block {i}\nx = {i}\n```\n")

    initial_segment_count = len(f._segments)
    assert initial_segment_count == 20  # 10 prose + 10 code segments finalized and immutable

    # Capture identity / objects of finalized segments
    finalized_snapshot = list(f._segments)

    # Now stream a large 100-character code block in single-character chunks
    active_code_chunk = "```python\nfor j in range(50):\n    print(j)\n```\n"
    for ch in active_code_chunk:
        f.feed(ch)

    # Assert that all earlier finalized segments were NOT mutated or reparsed
    for idx, seg in enumerate(finalized_snapshot):
        assert f._segments[idx] is seg  # Same immutable objects in list!

    f.flush()

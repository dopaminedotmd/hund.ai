"""Tests proving character-for-character canonical source preservation across chunk boundaries."""
import pytest
from hund.ui.output import StreamingMarkdownFilter
from hund.ui.fullscreen import ResponsePayloadRecord


def test_canonical_source_crlf_and_split_chunks():
    """Verify that decoded Python string chunks are preserved exactly without newline conversion."""
    chunks = [
        "First line\r\n",
        "Second line with \r",
        "\n split CRLF\r\n",
        "```python\r\n",
        "def foo():\r\n",
        "    return 42\r\n",
        "```\r\n",
        "Trailing prose without newline",
    ]

    f = StreamingMarkdownFilter()
    for c in chunks:
        f.feed(c)
    f.flush()

    expected_full = "".join(chunks)
    assert f.canonical_source == expected_full

    record = ResponsePayloadRecord(
        block_id=1,
        canonical_chunks=list(f._canonical_chunks),
        segments=f.get_segments(),
    )
    assert record.canonical_source == expected_full


def test_canonical_source_unterminated_code_block():
    """Verify that unclosed code fences are marked closed for presentation but canonical source is verbatim."""
    chunks = [
        "Starting explanation:\n",
        "```python\n",
        "def unfinished():\n",
        "    pass\n",
    ]

    f = StreamingMarkdownFilter()
    for c in chunks:
        f.feed(c)
    f.flush()

    # Presentation segments mark closed_by_eof=True
    segs = f.get_segments()
    assert len(segs) == 2
    assert segs[1].closed_by_eof is True

    # Canonical source is verbatim without synthetic trailing fence
    expected_full = "".join(chunks)
    assert f.canonical_source == expected_full
    assert not f.canonical_source.endswith("```\n")

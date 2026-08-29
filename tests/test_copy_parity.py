"""Tests for copy and source parity."""
import pytest
from hund.providers.base import Message
from hund.ui.output import StreamingMarkdownFilter


def test_copy_last_response_copies_pure_canonical_source():
    raw_markdown = (
        "Here is the solution:\n\n"
        "```python\n"
        "def solve(n):\n"
        "    return n * 2\n"
        "```"
    )
    # Simulate turn
    filter_instance = StreamingMarkdownFilter()
    filter_instance.feed(raw_markdown)
    filter_instance.flush()

    msg = Message(role="assistant", content=filter_instance.canonical_source)
    messages = [Message(role="user", content="help"), msg]

    # Verify copy_last_response logic
    last = next(
        (m.content for m in reversed(messages) if getattr(m, "role", "") == "assistant"),
        "",
    )
    assert last == raw_markdown
    assert "╭─ hund" not in last
    assert "│" not in last
    assert "╰──" not in last


def test_unterminated_fence_copies_without_synthetic_backticks():
    unterminated_markdown = (
        "```python\n"
        "x = 100\n"
    )
    filter_instance = StreamingMarkdownFilter()
    filter_instance.feed(unterminated_markdown)
    filter_instance.flush()

    assert filter_instance.canonical_source == unterminated_markdown
    # Verbatim preservation without adding closing ```
    assert not filter_instance.canonical_source.endswith("```\n")

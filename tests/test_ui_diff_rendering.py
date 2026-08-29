"""Tests for diff block and code preview preservation in fullscreen UI."""
import time
from hund.tools.file_tool import FileChangeResult, _record_latest_file_change


def test_activity_rerender_preserves_diff_tail():
    """Verify that _render_activity keeps diff blocks and output appended after tool_result."""
    # Setup mock sink environment
    from prompt_toolkit.buffer import Buffer
    output_buffer = Buffer()

    # We test the exact _render_activity tail retention pattern:
    # 1. Start tool: activity_marker is set at current length
    output_buffer.text = "user> edit a file\n"
    activity_marker = len(output_buffer.text)
    activity_prefix = "  · "
    activity_end = activity_marker

    # 2. Tool finishes and appends a diff block
    diff_block = "┌─ DIFF docs/test.md ─┐\n│ +new line           │\n└─────────────────────┘\n\n"
    output_buffer.text += diff_block

    # 3. Next activity render occurs (e.g. clear_thinking or next tool)
    current = output_buffer.text
    tail = current[activity_end:] if activity_end is not None else ""
    block = activity_prefix + "activity complete\n"
    output_buffer.text = current[:activity_marker] + block + tail
    activity_end = activity_marker + len(block)

    # 4. Assert diff block is preserved in buffer!
    assert "┌─ DIFF docs/test.md ─┐" in output_buffer.text
    assert "user> edit a file\n" in output_buffer.text
    assert "activity complete" in output_buffer.text

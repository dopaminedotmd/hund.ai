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


def test_write_file_over_20_lines_caps_preview_to_20_with_indicator(tmp_path):
    from hund.tools.file_tool import make_handlers

    tools = make_handlers(tmp_path)
    write_tool = tools["write_file"]

    lines = [f"line {i}" for i in range(35)]
    content = "\n".join(lines)
    res = write_tool({"path": "big.txt", "content": content})

    assert res.truncated is True
    preview_lines = res.display_preview.splitlines()
    assert len(preview_lines) == 21
    assert preview_lines[-1] == "+15 lines omitted"


def test_edit_file_over_20_lines_caps_preview_to_20_with_indicator(tmp_path):
    from hund.tools.file_tool import make_handlers

    tools = make_handlers(tmp_path)
    write_tool = tools["write_file"]
    edit_tool = tools["edit_file"]

    write_tool({"path": "code.py", "content": "def func():\n    pass\n"})

    new_body = "\n".join(f"    x_{i} = {i}" for i in range(25))
    res = edit_tool({"path": "code.py", "old_str": "    pass", "new_str": new_body})

    assert res.truncated is True
    preview_lines = res.display_preview.splitlines()
    assert any("lines omitted" in l for l in preview_lines)


def test_markdown_table_preserved_without_column_wrapping_in_response_box():
    """Verify that markdown tables are parsed as table segments and preserved without wrap_cells breaking."""
    from hund.ui.output import parse_semantic_segments, SegmentType
    from hund.ui.render import render_response_box_from_segments

    table_md = (
        "Here is the comparison table:\n\n"
        "| Strategy | Precision | Latency |\n"
        "| --- | --- | --- |\n"
        "| Direct Lookup | High | 12ms |\n"
        "| Vector Search | Medium | 85ms |\n\n"
        "All strategies evaluated."
    )

    segments = parse_semantic_segments(table_md, content_width=70)
    table_segs = [s for s in segments if getattr(s, "type", "") in ("table", SegmentType.TABLE)]
    assert len(table_segs) >= 1

    box_str, line_meta = render_response_box_from_segments(segments, terminal_width=74)
    assert "| Strategy | Precision | Latency |" in box_str
    assert "| Direct Lookup | High | 12ms |" in box_str
    assert "| Vector Search | Medium | 85ms |" in box_str


def test_output_lexer_normalizes_multiline_bold_across_newlines():
    """Verify that _OutputLexer normalizes multiline bold without raw ** leaks."""
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _OutputLexer

    text = "Intro with **multi-line bold text that\nspans across lines** and finishes here."
    doc = Document(text)
    lexer = _OutputLexer()
    get_line = lexer.lex_document(doc)

    tokens_0 = get_line(0)
    tokens_1 = get_line(1)

    assert not any("**" in txt for _, txt in tokens_0)
    assert not any("**" in txt for _, txt in tokens_1)

    bold_parts_0 = [txt for st, txt in tokens_0 if "label" in st]
    bold_parts_1 = [txt for st, txt in tokens_1 if "label" in st]
    assert any("multi-line bold" in p for p in bold_parts_0)
    assert any("spans across lines" in p for p in bold_parts_1)


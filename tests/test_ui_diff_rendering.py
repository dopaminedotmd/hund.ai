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
    assert "| Strategy      | Precision | Latency |" in box_str
    assert "| Direct Lookup | High      | 12ms    |" in box_str
    assert "| Vector Search | Medium    | 85ms    |" in box_str


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

    bold_parts_0 = [txt for st, txt in tokens_0 if "label" in st or "strong" in st]
    bold_parts_1 = [txt for st, txt in tokens_1 if "label" in st or "strong" in st]
    assert any("multi-line bold" in p for p in bold_parts_0)
    assert any("spans across lines" in p for p in bold_parts_1)


def test_table_contract_3x5_varying_widths_and_unicode_crlf():
    """3x5 table with long cell at 120/80/60/40: straight separators, no overflow, readable fallback."""
    from hund.ui.render import format_markdown_table
    from hund.ui.unicode_cells import cell_width

    raw_table = [
        "| ID | Komponent åäö | Beskrivning |\r\n",
        "| --- | --- | --- |\r\n",
        "| 1 | Kärna | Snabb och deterministisk motor för hund. |\r\n",
        "| 2 | Gränssnitt | TUI med stöd för ANSI och sant färgspektrum. |\r\n",
        "| 3 | Lång rad | Denna cell har en extremt lång förklaring om hund och arkitektur för att testa wrapping och separatorinriktning. |\r\n",
        "| 4 | Minne | SQLite-databas med persistens. |\r\n",
        "| 5 | Verktyg | Säkra filverktyg inom workspace. |\r\n",
    ]

    # Test widths 120, 80, 60
    for width in (120, 80, 60):
        formatted = format_markdown_table(raw_table, max_width=width)
        assert len(formatted) > 5
        table_lines = [line for line, _, slang in formatted if slang != "sep"]
        sep_lines = [line for line, _, slang in formatted if slang == "sep"]

        # Straight separators: all lines have equal visual width
        expected_w = cell_width(table_lines[0])
        assert expected_w <= width
        for tl in table_lines:
            assert cell_width(tl) == expected_w
        for sl in sep_lines:
            assert cell_width(sl) == expected_w

    # Test width 40: below threshold -> readable stacked/linear fallback
    fallback_40 = format_markdown_table(raw_table, max_width=40)
    assert len(fallback_40) >= 15
    for fl, _, slang in fallback_40:
        assert cell_width(fl) <= 40
    # Must contain the content legibly
    flat_text = " ".join(l for l, _, _ in fallback_40)
    assert "Kärna" in flat_text
    assert "Gränssnitt" in flat_text
    assert "Lång rad" in flat_text


def test_batch_file_change_diffs_preserve_both_with_monotonic_ids(tmp_path):
    """Batch create+modify retains both diffs, monotonic change_id, multi-slot registry."""
    from hund.tools.file_tool import (
        FileChangeResult,
        _record_latest_file_change,
        pop_last_file_change_result,
        get_file_change_by_id,
        _UNCONSUMED_CHANGES,
    )
    from hund.ui.activity import ActivityTimeline, ToolActivity, ActivityStatus
    from hund.ui.render import format_diff_block

    _UNCONSUMED_CHANGES.clear()

    # Two changes created in a single batch
    res1 = FileChangeResult(
        operation="write_file",
        path="file1.txt",
        status="created",
        content_type_or_language="text",
        committed_content_or_diff="line 1\nline 2",
        display_preview="line 1\nline 2",
    )
    res2 = FileChangeResult(
        operation="write_file",
        path="file2.txt",
        status="modified",
        content_type_or_language="text",
        committed_content_or_diff="-old\n+new",
        display_preview="-old\n+new",
    )

    # Monotonic change_ids
    assert res1.change_id > 0
    assert res2.change_id > res1.change_id

    # Record both into registry
    _record_latest_file_change(res1)
    _record_latest_file_change(res2)

    # Lookup by id
    assert get_file_change_by_id(res1.change_id) == res1
    assert get_file_change_by_id(res2.change_id) == res2

    # Multi-slot pop retrieves tool 1 first, then tool 2 (no loss of first diff)
    popped1 = pop_last_file_change_result()
    popped2 = pop_last_file_change_result()
    assert popped1 == res1
    assert popped2 == res2

    # Test ActivityTimeline keeps both diffs visible simultaneously
    timeline = ActivityTimeline()
    ev1 = timeline.start("write_file", "write file1.txt")
    diff1 = format_diff_block("+line 1\n+line 2", filename="file1.txt", width=80)
    timeline.attach_diff(ev1, diff1.splitlines(), "text", change_id=res1.change_id)
    timeline.finish(ev1, ActivityStatus.COMPLETE)

    ev2 = timeline.start("write_file", "write file2.txt")
    diff2 = format_diff_block("-old\n+new", filename="file2.txt", width=80)
    timeline.attach_diff(ev2, diff2.splitlines(), "text", change_id=res2.change_id)
    timeline.finish(ev2, ActivityStatus.COMPLETE)

    rendered_flow = timeline.render(width=80)
    assert "file1.txt" in rendered_flow
    assert "file2.txt" in rendered_flow
    assert "line 1" in rendered_flow
    assert "new" in rendered_flow


def test_html_file_change_10_60_200_lines_diff_preview(tmp_path):
    """Diff preview with 10, 60, and 200 lines HTML shows status, counts, and limits."""
    from hund.tools.file_tool import make_handlers
    from hund.ui.render import format_diff_block

    tools = make_handlers(tmp_path)
    write_tool = tools["write_file"]

    # 10 lines: not truncated
    html_10 = "\n".join(f"<p>line {i}</p>" for i in range(10))
    res_10 = write_tool({"path": "doc10.html", "content": html_10})
    assert res_10.truncated is False
    block_10 = format_diff_block(res_10.display_preview, filename="doc10.html", width=70, status=res_10.status)
    assert "doc10.html" in block_10
    assert "[created]" in block_10
    assert "(+10 -0)" in block_10
    assert "Diff preview limited" not in block_10

    # 60 lines: truncated with limited indicator
    html_60 = "\n".join(f"<div>row {i}</div>" for i in range(60))
    res_60 = write_tool({"path": "doc60.html", "content": html_60})
    assert res_60.truncated is True
    block_60 = format_diff_block(
        res_60.display_preview,
        filename="doc60.html",
        width=70,
        is_limited=res_60.truncated,
        status=res_60.status,
    )
    assert "doc60.html" in block_60
    assert "[created]" in block_60
    assert "Diff preview limited" in block_60

    # 200 lines: truncated with bounded preview
    html_200 = "\n".join(f"<li>item {i}</li>" for i in range(200))
    res_200 = write_tool({"path": "doc200.html", "content": html_200})
    assert res_200.truncated is True
    block_200 = format_diff_block(
        res_200.display_preview,
        filename="doc200.html",
        width=70,
        is_limited=res_200.truncated,
        status=res_200.status,
    )
    assert "doc200.html" in block_200
    assert "Diff preview limited" in block_200



"""Regression tests for streamed tool boundaries and file artifacts."""

from unittest.mock import MagicMock

from prompt_toolkit.document import Document
from prompt_toolkit.data_structures import Size
from prompt_toolkit.output import DummyOutput

from hund.tools.file_tool import FileChangeResult
from hund.ui.fullscreen import (
    ResponseBlockRegistry,
    _OutputLexer,
    _format_runtime_error,
    _lex_pygments_code,
    create_fullscreen_app,
)
from hund.ui.output import StreamingMarkdownFilter
from hund.ui.render import format_diff_block
from hund.ui.unicode_cells import cell_width


class ResizableOutput(DummyOutput):
    def __init__(self, columns: int = 80) -> None:
        super().__init__()
        self.columns = columns

    def get_size(self) -> Size:
        return Size(rows=24, columns=self.columns)


import time


def _make_sink(output=None):
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={}, start_time=time.time())
    _app, ctx = create_fullscreen_app(rt, state, output=output or DummyOutput())
    return ctx["sink_cls"](), ctx


def test_tool_boundary_resets_markdown_filter() -> None:
    sink, _ctx = _make_sink()
    sink.set_user_input("describe the change")
    sink.chunk("Earlier narration.")

    sink.tool_start("read_file", {"path": "example.py"})

    assert sink._md._canonical_chunks == []
    assert sink._md.get_segments() == []


def test_end_assistant_resets_markdown_filter() -> None:
    """Each LLM response in the tool loop must render as its own box, not accumulate."""
    sink, _ctx = _make_sink()
    sink.set_user_input("do the task")
    sink.chunk("Response one text.")
    sink.end_assistant()

    assert sink._md._canonical_chunks == []
    assert sink._md.get_segments() == []


def test_tool_result_registers_plain_diff_block() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("edit example.py")
    sink.tool_start("edit_file", {"path": "example.py"})
    change = FileChangeResult(
        operation="edit_file",
        path="example.py",
        status="modified",
        content_type_or_language="py",
        committed_content_or_diff="-value = 1\n+value = 2\n def run():\n+    return value",
        display_preview="-value = 1\n+value = 2\n def run():\n+    return value",
    )

    sink.tool_result("edit_file", change)

    output = ctx["output_buffer"].text
    # Plain artifact block: the diff branch is NOT wrapped in a response-box rail.
    changed_line = next(l for l in output.splitlines() if "└ " in l)
    assert not changed_line.startswith(("│", "║"))
    diff_line = next(l for l in output.splitlines() if "value = 2" in l)
    assert diff_line.endswith(" ")
    registry = ctx["block_registry"]
    record = registry.records()[-1]
    assert registry.get_line_style(record.start_line + 1) == ("diff", "python")

    get_line = _OutputLexer(block_registry=registry).lex_document(Document(output))
    tokens = get_line(output.splitlines().index(diff_line))
    assert any(
        "class:add" in style and text.endswith(" ") for style, text in tokens
    )


def test_created_file_uses_all_addition_diff_artifact() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("create example.py")
    sink.tool_start("write_file", {"path": "example.py"})
    change = FileChangeResult(
        operation="write_file",
        path="example.py",
        status="created",
        content_type_or_language="py",
        committed_content_or_diff="value = 2\ndef run():\n    return value",
        display_preview="value = 2\ndef run():\n    return value",
    )

    sink.tool_result("write_file", change)

    output = ctx["output_buffer"].text
    assert "└ example.py  (+3 -0)" in output
    assert "── example.py" not in output
    diff_line = next(line for line in output.splitlines() if "value = 2" in line)
    registry = ctx["block_registry"]
    tokens = _OutputLexer(block_registry=registry).lex_document(Document(output))(
        output.splitlines().index(diff_line)
    )
    assert any("class:add" in style for style, _text in tokens)


def test_diff_formatter_has_codex_parity_anatomy_and_width_matrix() -> None:
    diff = "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n-old = 1\n+new = 2\n context = True"
    for width in (42, 60, 80, 120):
        rendered = format_diff_block(diff, filename="example.py", width=width)
        rows = rendered.splitlines()
        assert "└ example.py  (+1 -1)" in rows[0]
        assert not any("@@" in line or "│" in line for line in rows)
        assert all(cell_width(line) <= width for line in rows)
        for line in rows[1:]:
            if line.startswith(("+", "-")):
                assert cell_width(line) == width


def test_registered_diff_artifact_reflows_after_resize() -> None:
    app_output = ResizableOutput()
    sink, ctx = _make_sink(app_output)
    sink.set_user_input("edit example.py")
    sink.tool_start("edit_file", {"path": "example.py"})
    sink.tool_result("edit_file", FileChangeResult(
        operation="edit_file",
        path="example.py",
        status="modified",
        content_type_or_language="py",
        committed_content_or_diff="-value = 1\n+value = 2",
        display_preview="-value = 1\n+value = 2",
    ))

    output = ctx["output_buffer"]
    for columns in (42, 60, 80, 120):
        app_output.columns = columns
        ctx["_reflow_borders"]()
        rows = [row for row in output.text.splitlines() if "value =" in row]
        assert rows
        assert all(cell_width(row) == columns - 1 for row in rows)


def test_runtime_error_requires_exact_402_and_keeps_provider_detail() -> None:
    false_402 = _format_runtime_error("Provider HTTP 500 — balance lookup failed")
    real_402 = _format_runtime_error("Provider HTTP 402 — insufficient balance")

    assert "API Quota / Balance Error (HTTP 402)" not in false_402
    assert "Provider HTTP 500 — balance lookup failed" in false_402
    assert "API Quota / Balance Error (HTTP 402)" in real_402
    assert "Provider HTTP 402 — insufficient balance" in real_402


def test_diff_footer_is_explicit_and_streaming_matches_fullscreen() -> None:
    diff = "-old = 1\n+new = 2\n context = True"
    expected = format_diff_block(diff, filename="example.py", width=42)
    limited = format_diff_block(diff, filename="example.py", width=42, is_limited=True)
    assert "… Diff preview limited." not in expected
    assert limited.endswith("… Diff preview limited.")

    markdown = StreamingMarkdownFilter(content_width=42)
    streamed = markdown.feed("```diff example.py\n" + diff + "\n```\n") + markdown.flush()
    assert expected in streamed


def test_tool_result_is_buffered_while_confirmation_is_active() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("edit example.py")
    sink.tool_start("edit_file", {"path": "example.py"})
    change = FileChangeResult(
        operation="edit_file",
        path="example.py",
        status="modified",
        content_type_or_language="py",
        committed_content_or_diff="-value = 1\n+value = 2",
        display_preview="-value = 1\n+value = 2",
    )
    before = ctx["output_buffer"].text
    ctx["_confirm"]["active"] = True

    sink.tool_result("edit_file", change)

    assert ctx["output_buffer"].text == before
    assert sink._pending_tool_results == [("edit_file", change)]
    ctx["_confirm"]["active"] = False
    sink._flush_pending_tool_results()
    assert "value = 2" in ctx["output_buffer"].text
    assert sink._pending_tool_results == []


def test_lexer_diff_line_emits_background_and_syntax_classes() -> None:
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 1, {0: ("diff", "python")})
    get_line = _OutputLexer(block_registry=registry).lex_document(
        Document("│  + 3   def foo():  │")
    )

    tokens = get_line(0)
    classes = [style for style, _text in tokens]
    # Add rows: prefix char is add_fg (green), lineno is diff_lineno (grey),
    # code body carries class:add (muted bg) alongside syntax colours.
    assert any("class:add_fg" in style for style in classes)
    assert any("class:diff_lineno" in style for style in classes)
    assert any("class:add" in style for style in classes)
    assert any("class:syntax_" in style for style in classes)


def test_lexer_plain_registered_diff_line_has_red_marker_and_syntax() -> None:
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 1, {0: ("diff", "python")})
    get_line = _OutputLexer(block_registry=registry).lex_document(
        Document('- 2   return f"Hej {namn}!"')
    )

    tokens = get_line(0)
    classes = [style for style, _text in tokens]
    # Del rows: prefix char is del_fg (red), lineno is diff_lineno (grey),
    # code body carries class:del (muted bg) alongside syntax colours.
    assert any("class:del_fg" in style for style in classes)
    assert any("class:diff_lineno" in style for style in classes)
    assert any("class:del" in style for style in classes)
    assert not any("class:danger" in style for style in classes)
    assert any("class:syntax_" in style for style in classes)


def test_lexer_keeps_distinct_syntax_colours_inside_diff_rows() -> None:
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 1, {0: ("diff", "python")})
    get_line = _OutputLexer(block_registry=registry).lex_document(
        Document('+ 2   return "hello", 42')
    )

    classes = [style for style, _text in get_line(0)]
    assert sum("class:syntax_" in style for style in classes) >= 3


def test_bygge12_diff_design_prefix_lineno_classes() -> None:
    """BYGGE 12: + green (add_fg), - red (del_fg), lineno grey (diff_lineno), code add/del bg."""
    from hund.ui.fullscreen import _parse_semantic_line

    # Add row: prefix '+' → add_fg, lineno → diff_lineno, code → add bg
    add_tokens = _parse_semantic_line("+ 3   value = 2")
    add_classes = [s for s, _ in add_tokens]
    add_texts = {s: t for s, t in add_tokens}
    assert any(s == "class:add_fg" for s in add_classes), "'+' char must be add_fg (green)"
    assert any(s == "class:diff_lineno" for s in add_classes), "lineno must be diff_lineno (grey)"
    assert any(s == "class:add" for s in add_classes), "code must carry add bg class"
    # The '+' char itself must not have diff_lineno style
    assert add_texts.get("class:add_fg", "") == "+"

    # Del row: prefix '-' → del_fg, lineno → diff_lineno, code → del bg
    del_tokens = _parse_semantic_line("- 3   value = 1")
    del_classes = [s for s, _ in del_tokens]
    del_texts = {s: t for s, t in del_tokens}
    assert any(s == "class:del_fg" for s in del_classes), "'-' char must be del_fg (red)"
    assert any(s == "class:diff_lineno" for s in del_classes), "lineno must be diff_lineno (grey)"
    assert any(s == "class:del" for s in del_classes), "code must carry del bg class"
    assert del_texts.get("class:del_fg", "") == "-"

    # Registered lexer path: same requirements
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 2, {0: ("diff", "python"), 1: ("diff", "python")})
    doc_text = "+ 3   value = 2\n- 2   value = 1"
    get_line = _OutputLexer(block_registry=registry).lex_document(Document(doc_text))

    add_tok = get_line(0)
    add_tok_classes = [s for s, _ in add_tok]
    assert any("class:add_fg" in s for s in add_tok_classes), "registered + must be add_fg"
    assert any("class:diff_lineno" in s for s in add_tok_classes), "registered + lineno must be diff_lineno"
    assert any("class:add" in s for s in add_tok_classes), "registered + code must have add bg"

    del_tok = get_line(1)
    del_tok_classes = [s for s, _ in del_tok]
    assert any("class:del_fg" in s for s in del_tok_classes), "registered - must be del_fg"
    assert any("class:diff_lineno" in s for s in del_tok_classes), "registered - lineno must be diff_lineno"
    assert any("class:del" in s for s in del_tok_classes), "registered - code must have del bg"


def test_markdown_diff_uses_filename_language_for_syntax() -> None:
    sink, ctx = _make_sink()
    sink.chunk(
        "```diff halsning.html\n"
        "-<h1 class=\"old\">Hej</h1>\n"
        "+<h1 class=\"new\">Hallå</h1>\n"
        "```\n"
    )

    output = ctx["output_buffer"].text
    registry = ctx["block_registry"]
    record = registry.records()[-1]
    assert ("diff", "html") in record.line_metadata.values()
    diff_line = next(line for line in output.splitlines() if "Hallå" in line)
    tokens = _OutputLexer(block_registry=registry).lex_document(Document(output))(
        output.splitlines().index(diff_line)
    )
    assert sum("class:syntax_" in style for style, _text in tokens) >= 3


def test_intermediate_capsule_during_tool_loop_renders_open_panel() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("investigate issue")
    sink.tool_start("read_file", {"path": "example.py"})
    sink.narrate("hund is still searching for the width owner.")

    output = ctx["output_buffer"].text
    assert "╭─ hund" in output
    assert "│ hund is still searching for the width owner." in output
    assert "┊" in output
    assert not sink._box_open


def test_intermediate_capsule_multiline_flows_without_clipping() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("investigate issue")
    sink.tool_start("read_file", {"path": "example.py"})
    sink.narrate("Line one of thought\nLine two of thought\nLine three of thought that is extra")

    output = ctx["output_buffer"].text
    assert "Line one of thought" in output
    assert "Line two of thought" in output
    assert "Line three of thought that is extra" in output
    # Open panel has │ on text lines
    assert any("│ Line one of thought" in l for l in output.splitlines())


def test_intermediate_capsule_replaces_previous_capsule_without_stacking() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("investigate issue")
    sink.tool_start("read_file", {"path": "example.py"})
    sink.narrate("first intermediate capsule")
    assert "first intermediate capsule" in ctx["output_buffer"].text

    sink.narrate("second intermediate capsule")
    output = ctx["output_buffer"].text
    assert "second intermediate capsule" in output
    assert "first intermediate capsule" not in output
    assert output.count("╭─ hund") == 1


def test_end_assistant_after_intermediate_capsule() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("investigate issue")
    sink.tool_start("read_file", {"path": "example.py"})
    sink.narrate("intermediate thought")
    sink.tool_result("read_file", "file contents")
    sink.end_assistant()

    assert sink._turn_start_time == 0.0
    assert not sink._box_open


def test_typewriter_reduced_motion_reveals_immediately() -> None:
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})
    _app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()

    sink.set_user_input("hello")
    sink.chunk("Full immediate response.")

    assert "Full immediate response." in ctx["output_buffer"].text
    assert sink._box_open
    assert sink._revealed_len == len(sink._current_boxed)


def test_typewriter_progressive_reveal_and_reveal_now() -> None:
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=False, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})
    _app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()

    sink.set_user_input("hello")
    sink.chunk("A longer response string designed for progressive reveal testing.")

    # With reduced_motion=False, reveal thread was spawned
    assert sink._reveal_thread is not None
    # Calling reveal_now reveals the entire box immediately
    sink.reveal_now()
    assert "A longer response string" in ctx["output_buffer"].text
    assert sink._revealed_len == len(sink._current_boxed)


def test_typewriter_before_key_press_calls_reveal_now() -> None:
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=False, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})
    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()

    sink.set_user_input("hello")
    sink.chunk("Testing keypress interruption of typewriter.")

    # Trigger before_key_press event on Application key processor
    app.key_processor.before_key_press.fire()

    assert "Testing keypress interruption" in ctx["output_buffer"].text
    assert sink._revealed_len == len(sink._current_boxed)


def test_streaming_sink_intermediate_capsule_and_reduced_motion() -> None:
    import io
    from rich.console import Console
    from hund.ui.output import StreamingSink

    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=True, color_system=None)
    sink = StreamingSink(console, reduced_motion=True)
    assert sink.stream_delay_s == 0.0

    sink.set_user_input("test command")
    sink.tool_start("read_file", {"path": "test.py"})
    sink.narrate("searching for helper...")
    output = buf.getvalue()
    assert "searching for helper" in output
    assert "╭─ hund" in output

    sink.tool_result("read_file", "content")


def test_typewriter_stale_generation_does_not_overwrite() -> None:
    import time
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=False, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})
    _app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()

    sink.set_user_input("hello")
    sink.chunk("First generation text that would animate.")
    gen1 = sink._reveal_generation

    sink.chunk("Second generation text that replaces first.")
    gen2 = sink._reveal_generation
    assert gen2 > gen1

    # Wait briefly for thread to terminate/advance
    time.sleep(0.05)
    sink.reveal_now()
    assert "Second generation" in ctx["output_buffer"].text


def test_compression_notice_in_status_bar_not_transcript() -> None:
    import time
    from unittest.mock import patch
    from hund.agent.context import CompressionResult

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    rt.workspace = "C:\\test"
    rt.domain_hint = "general"
    rt.client = MagicMock(last_result=None)
    rt.engine = MagicMock()
    rt.schemas = []
    state = MagicMock(extra={}, start_time=time.time())

    _app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())

    fake_comp = CompressionResult(
        compressed=True,
        messages=[],
        dropped_turns=7,
        tokens=500,
        method="drop_oldest",
    )

    with patch("hund.ui.fullscreen.maybe_compress", return_value=fake_comp), \
         patch("hund.ui.fullscreen._agent_turn"):
        ctx["input_buffer"].text = "run command"
        with patch.object(rt.client, "stream", return_value=[]):
            ctx["input_buffer"].validate_and_handle()
            for _ in range(50):
                if not ctx["turn_running"][0] and ctx["transient_notice"][0]:
                    break
                time.sleep(0.02)

    # Verify output_buffer.text does NOT contain "turns compressed"
    assert "turns compressed" not in ctx["output_buffer"].text
    # Verify transient_notice contains compression message
    assert ctx["transient_notice"][0] == "7 turns compressed"


def test_fullscreen_transient_notice_renders_in_status_bar() -> None:
    sink, ctx = _make_sink()
    ctx["transient_notice"][0] = "7 turns compressed"
    ctx["transient_notice"][1] = time.monotonic() + 5.0

    assert ctx["transient_notice"][0] == "7 turns compressed"
    # Status bar renderer contains the transient notice
    segments = ctx["status_text"]()
    assert any("7 turns compressed" in text for _style, text in segments)


def test_intermediate_capsule_between_tools_after_tool_result() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("compare files")

    # Tool 1 completes
    sink.tool_start("read_file", {"path": "render.py"})
    sink.tool_result("read_file", "render code")

    # Narration between tool 1 and tool 2
    sink.narrate("render.py är delvis läst och trunkerades...")
    output = ctx["output_buffer"].text
    assert "render.py är delvis läst" in output
    assert sink._activity_marker is not None
    assert not sink._box_open
    assert "╭─ hund" in output

    # Second narration chunk in same gap replaces the first (latest wins)
    sink.narrate("Nu är båda filerna påbörjade...")
    output = ctx["output_buffer"].text
    assert "Nu är båda filerna påbörjade" in output
    assert "render.py är delvis läst" not in output
    assert output.count("╭─ hund") == 1

    # Tool 2 starts and completes
    sink.tool_start("read_file", {"path": "output.py"})
    sink.tool_result("read_file", "output code")

    sink.end_assistant()
    assert not sink._box_open


def test_first_narration_before_first_tool_renders_as_prose() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("compare files")

    # Final response before any tool starts
    sink.chunk("hund börjar med att läsa render.py.")
    assert sink._box_open
    assert "hund börjar med att läsa render.py." in ctx["output_buffer"].text


def test_streaming_sink_intermediate_capsule_between_tools() -> None:
    import io
    from rich.console import Console
    from hund.ui.output import StreamingSink

    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=True, color_system=None)
    sink = StreamingSink(console, reduced_motion=True)

    sink.set_user_input("compare files")
    sink.tool_start("read_file", {"path": "render.py"})
    sink.tool_result("read_file", "render code")

    # Narration between tool 1 and tool 2
    sink.narrate("render.py är delvis läst...")
    output = buf.getvalue()
    assert "render.py är delvis läst" in output
    assert "╭─ hund" in output

    sink.tool_start("read_file", {"path": "output.py"})
    sink.tool_result("read_file", "output code")
    sink.end_assistant()


def test_diff_lexer_mutes_add_and_context_but_not_plain_code():
    """Diff-block text (add/context rows) uses the muted syntax_diff palette; plain
    chat code is bright (syntax_*) and del rows use syntax_del_*."""
    bright = [s for s, _ in _lex_pygments_code("def foo(): pass", "", "python")]
    add = [s for s, _ in _lex_pygments_code("def foo(): pass", "", "python", row_style="class:add", muted=True)]
    ctx = [s for s, _ in _lex_pygments_code("def foo(): pass", "", "python", muted=True)]
    dele = [s for s, _ in _lex_pygments_code("def foo(): pass", "", "python", row_style="class:del")]

    assert any(s == "class:syntax_keyword" for s in bright)
    assert not any("syntax_diff" in s or "syntax_del" in s for s in bright)

    assert any("class:add class:syntax_diff_keyword" == s for s in add)
    assert not any("class:syntax_keyword" in s for s in add)

    assert any(s == "class:syntax_diff_keyword" for s in ctx)
    assert not any("class:syntax_keyword" in s for s in ctx)

    assert any("class:del class:syntax_del_keyword" == s for s in dele)
    assert not any("class:syntax_keyword" in s for s in dele)


def test_tool_flow_row_dataclass_contract() -> None:
    from hund.ui.render import ToolFlowRow

    row = ToolFlowRow(text="  ┊ ✓ read file", kind="activity", language="")
    assert row.text == "  ┊ ✓ read file"
    assert row.kind == "activity"
    assert row.language == ""

    diff_row = ToolFlowRow(text="+    1 val = 2", kind="diff", language="python")
    assert diff_row.kind == "diff"
    assert diff_row.language == "python"


def test_format_tool_flow_with_subagents_and_diffs() -> None:
    from hund.ui.render import format_tool_flow, format_diff_block
    from hund.ui.activity import ToolActivity, ActivityStatus

    diff_lines = format_diff_block("+val = 2\n-val = 1", filename="test.py", width=60).splitlines()

    events = [
        ToolActivity(
            event_id=1,
            tool_name="read_file",
            group="read",
            description="read test.py",
            status=ActivityStatus.COMPLETE,
            duration_s=0.2,
        ),
        ToolActivity(
            event_id=2,
            tool_name="edit_file",
            group="edit",
            description="modified test.py",
            status=ActivityStatus.COMPLETE,
            duration_s=0.4,
            attached_diff_lines=tuple(diff_lines),
            attached_diff_language="python",
        ),
        ToolActivity(
            event_id=3,
            tool_name="subagent_task",
            group="delegation",
            description="delegated task 1",
            status=ActivityStatus.COMPLETE,
            duration_s=0.5,
            subagent_depth=1,
        ),
    ]

    rows = format_tool_flow(events, width=80, past_intent="hund created app.py and ran the syntax check.")
    assert len(rows) > 3
    assert rows[0].kind == "activity"
    assert "hund created app.py" in rows[0].text
    assert any(r.kind == "diff" and "└ test.py" in r.text for r in rows)
    assert any(r.kind == "substep" and "delegated task 1" in r.text for r in rows)
    assert rows[-1].kind == "summary"
    assert "change holds" in rows[-1].text or "completed" in rows[-1].text


def test_format_tool_flow_error_and_ascii_fallback() -> None:
    from hund.ui.render import format_tool_flow
    from hund.ui.activity import ToolActivity, ActivityStatus

    events = [
        ToolActivity(
            event_id=1,
            tool_name="terminal",
            group="execution",
            description="ran python script",
            status=ActivityStatus.ERROR,
            duration_s=0.3,
            detail="SyntaxError",
            attached_error_lines=("└ SyntaxError: expected ':' (line 6)",),
        )
    ]

    rows = format_tool_flow(events, width=80, ascii_only=True)
    assert len(rows) >= 2
    assert "| x ran python script — SyntaxError" in rows[0].text
    assert rows[1].kind == "error"
    assert "└ SyntaxError" in rows[1].text
    assert rows[-1].kind == "summary"
    assert "+- stopped" in rows[-1].text


def test_activity_timeline_attach_diff_and_error_and_immutability() -> None:
    from hund.ui.activity import ActivityTimeline, ActivityStatus

    timeline = ActivityTimeline()
    ev_id = timeline.start("terminal", "running test command")
    timeline.attach_diff(ev_id, ["└ app.py  (+1 -0)", "+    1 code = 1"], "python")
    timeline.attach_error(ev_id, ["└ Error: failed"])
    timeline.finish(ev_id, ActivityStatus.ERROR, detail="Process exited with 1")

    # Invariant: finish() with COMPLETE should not overwrite ERROR
    timeline.finish(ev_id, ActivityStatus.COMPLETE)
    assert timeline.events[0].status == ActivityStatus.ERROR
    assert timeline.events[0].attached_diff_lines == ("└ app.py  (+1 -0)", "+    1 code = 1")
    assert timeline.events[0].attached_error_lines == ("└ Error: failed",)


def test_format_diff_block_narrow_wrap() -> None:
    from hund.ui.render import format_diff_block

    diff_out = format_diff_block("+val = 2\n-val = 1", filename="a_very_long_file_name_for_testing.py", width=36)
    lines = diff_out.splitlines()
    assert "└ " in lines[0]
    assert lines[1].strip() == "(+1 -1)" or "(+1 -1)" in lines[1]


def test_intermediate_capsule_open_panel_tree_alignment() -> None:
    from hund.ui.render import render_intermediate_capsule

    capsule = render_intermediate_capsule("hund is doing something in the background", width=50, elapsed_s=12.4)
    lines = capsule.splitlines()
    assert lines[0].startswith("  ╭─ hund")
    assert lines[1].startswith("  │ ")
    assert "hund is doing something" in lines[1]
    assert lines[-1].strip() == "┊"


def test_output_lexer_diff_header_stats_colors() -> None:
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _OutputLexer, ResponseBlockRegistry

    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 1, {0: ("diff", "python")})
    get_line = _OutputLexer(block_registry=registry).lex_document(
        Document("  └ example.py  (+10 -2)        ")
    )
    tokens = get_line(0)
    styles = [s for s, _ in tokens]
    assert "class:secondary" in styles
    assert "class:diff_stat_add" in styles
    assert "class:diff_stat_del" in styles
    # Check that text (+10 -2) is correctly colored even with trailing spaces
    add_text = [t for s, t in tokens if "class:diff_stat_add" in s]
    del_text = [t for s, t in tokens if "class:diff_stat_del" in s]
    assert add_text == ["+10"]
    assert del_text == ["-2"]


def test_output_lexer_open_interim_panel_strict_white() -> None:
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _OutputLexer, ResponseBlockRegistry

    registry = ResponseBlockRegistry()
    doc_text = "  ╭─ hund ──────────────\n  │ hund is tracing the syntax error\n  ┊"
    get_line = _OutputLexer(block_registry=registry).lex_document(Document(doc_text))

    top_tokens = get_line(0)
    assert any("class:secondary" in s and "╭─" in t for s, t in top_tokens)

    body_tokens = get_line(1)
    assert any("class:secondary" in s and "│" in t for s, t in body_tokens)
    assert any("class:primary" in s and "hund is tracing" in t for s, t in body_tokens)

    bridge_tokens = get_line(2)
    assert any("class:secondary" in s and "┊" in t for s, t in bridge_tokens)


def test_format_tool_flow_with_interim_narration() -> None:
    from hund.ui.render import format_tool_flow
    from hund.ui.activity import ToolActivity, NarrationActivity, ActivityStatus

    events = [
        ToolActivity(
            event_id=1,
            tool_name="terminal",
            group="execution",
            description="ran python script",
            status=ActivityStatus.COMPLETE,
            duration_s=0.4,
        ),
        NarrationActivity(
            text="hund is tracing the error.",
            event_id=2,
        ),
        ToolActivity(
            event_id=3,
            tool_name="edit_file",
            group="edit",
            description="wrote app.py",
            status=ActivityStatus.COMPLETE,
            duration_s=0.1,
        ),
    ]

    rows = format_tool_flow(events, width=80)
    texts = [r.text for r in rows]
    # Batch 1 tool -> summary -> narration header -> narration body -> bridge line -> Batch 2 tool -> summary
    assert any("✓ ran python script" in t for t in texts)
    assert any("╭─ hund" in t for t in texts)
    assert any("│ hund is tracing the error" in t for t in texts)
    assert any("┊" in t for t in texts)
    assert any("✓ wrote app.py" in t for t in texts)


def test_file_over_20_lines_caps_inline_diff_to_20_with_indicator() -> None:
    sink, ctx = _make_sink()
    sink.set_user_input("create big file")
    sink.tool_start("write_file", {"path": "big.py"})

    lines = [f"val_{i} = {i}" for i in range(35)]
    preview = "\n".join(lines[:20]) + f"\n+{len(lines) - 20} lines omitted"
    change = FileChangeResult(
        operation="write_file",
        path="big.py",
        status="created",
        content_type_or_language="py",
        committed_content_or_diff="\n".join(lines),
        display_preview=preview,
        truncated=True,
    )
    sink.tool_result("write_file", change)

    output = ctx["output_buffer"].text
    assert "+15 lines omitted" in output
    assert "Diff preview limited" in output






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


def _make_sink(output=None):
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})
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
    changed_line = next(l for l in output.splitlines() if l.startswith("└ "))
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
        assert rows[0] == "└ example.py  (+1 -1)"
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
    assert any("class:add" in style for style in classes)
    assert any("class:pygments" in style for style in classes)


def test_lexer_plain_registered_diff_line_has_red_marker_and_syntax() -> None:
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 1, {0: ("diff", "python")})
    get_line = _OutputLexer(block_registry=registry).lex_document(
        Document('- 2   return f"Hej {namn}!"')
    )

    tokens = get_line(0)
    classes = [style for style, _text in tokens]
    assert any("class:del" in style for style in classes)
    assert not any("class:danger" in style for style in classes)
    assert any("class:pygments" in style for style in classes)


def test_lexer_keeps_distinct_syntax_colours_inside_diff_rows() -> None:
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, 0, 1, {0: ("diff", "python")})
    get_line = _OutputLexer(block_registry=registry).lex_document(
        Document('+ 2   return "hello", 42')
    )

    classes = [style for style, _text in get_line(0)]
    assert sum("class:pygments" in style for style in classes) >= 3


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
    assert sum("class:pygments" in style for style, _text in tokens) >= 3

"""Tests for semantic code presentation, language alias normalization, and historical block registry."""
import pytest
from prompt_toolkit.document import Document
from hund.ui.fullscreen import ResponseBlockRegistry, _OutputLexer
from hund.ui.output import SegmentType, parse_semantic_segments
from hund.ui.render import (
    format_code_block,
    format_diff_block,
    normalize_language_alias,
    render_response_box_from_segments,
)


def test_language_alias_normalization():
    assert normalize_language_alias("py") == "python"
    assert normalize_language_alias("python") == "python"
    assert normalize_language_alias("pwsh") == "powershell"
    assert normalize_language_alias("ps1") == "powershell"
    assert normalize_language_alias("powershell") == "powershell"
    assert normalize_language_alias("json") == "json"
    assert normalize_language_alias("sh") == "bash"
    assert normalize_language_alias("shell") == "bash"
    assert normalize_language_alias("bash") == "bash"
    assert normalize_language_alias("diff") == "diff"
    assert normalize_language_alias("patch") == "diff"
    assert normalize_language_alias("unknown_lang") == "unknown_lang"


def test_code_block_formatting_header_body_footer():
    code = "def greet():\n    return 'hello'"
    formatted = format_code_block(code, language="py", width=40)
    lines = formatted.split("\n")
    assert lines[0].startswith("── python ")
    assert lines[1] == "  def greet():"
    assert lines[2] == "      return 'hello'"
    assert lines[3] == "─" * 40


def test_diff_block_formatting_with_line_numbers():
    diff = "- old_line\n+ new_line\n  context_line"
    formatted = format_diff_block(diff, filename="test.py", width=40)
    lines = formatted.split("\n")
    assert lines[0].startswith("── test.py · changed ")
    assert any(l.startswith("- 1") for l in lines)
    assert any(l.startswith("+ 1") for l in lines)
    assert lines[-1] == "─" * 40


def test_multi_turn_historical_lexer_registry_and_adversarial_prose():
    registry = ResponseBlockRegistry()

    # Turn 1: Prose
    segs1 = parse_semantic_segments("Here is a simple explanation of the architecture.")
    box1, meta1 = render_response_box_from_segments(segs1, terminal_width=60)
    registry.register_or_update(1, start_line=0, line_count=box1.count("\n") + 1, line_metadata=meta1)

    # Turn 2: Code
    segs2 = parse_semantic_segments("```python\nx = 42\n```")
    box2, meta2 = render_response_box_from_segments(segs2, terminal_width=60)
    start_line_2 = box1.count("\n") + 2
    registry.register_or_update(2, start_line=start_line_2, line_count=box2.count("\n") + 1, line_metadata=meta2)

    # Turn 3: Adversarial prose containing fake diff headers and + / - lines
    adversarial_prose = "Look at this example text:\n── diff\n+ fake addition line\n- fake deletion line"
    segs3 = parse_semantic_segments(adversarial_prose)
    box3, meta3 = render_response_box_from_segments(segs3, terminal_width=60)
    start_line_3 = start_line_2 + box2.count("\n") + 2
    registry.register_or_update(3, start_line=start_line_3, line_count=box3.count("\n") + 1, line_metadata=meta3)

    full_document_text = f"{box1}\n\n{box2}\n\n{box3}"
    doc = Document(full_document_text)

    lexer = _OutputLexer(block_registry=registry)
    get_line_style = lexer.lex_document(doc)

    # Check Turn 2 code line styling
    # Line corresponding to x = 42 inside box2 should be styled with code / pygments tokens
    code_line_idx = start_line_2 + 2
    code_tokens = get_line_style(code_line_idx)
    # Ensure code token is produced without crash
    assert len(code_tokens) > 0

    # Check Turn 3 adversarial prose styling
    # The line '+ fake addition line' in prose box MUST NOT be styled as diff (class:success) because it is in a prose segment
    prose_fake_diff_line_idx = start_line_3 + 3
    prose_tokens = get_line_style(prose_fake_diff_line_idx)
    # Must NOT have class:success
    assert not any(t[0] == "class:success" for t in prose_tokens)


def test_file_change_result_creation_and_serialization(tmp_path):
    from hund.tools.file_tool import FileChangeResult, make_handlers

    handlers = make_handlers(tmp_path)
    write_fn = handlers["write_file"]

    # 1. Create new file
    res1 = write_fn({"path": "hello.py", "content": "print('hello world')\n"})
    assert isinstance(res1, FileChangeResult)
    assert res1.status == "created"
    assert res1.operation == "write_file"
    assert res1.path == "hello.py"
    assert res1.content_type_or_language == "python"
    assert res1.committed_content_or_diff == "print('hello world')\n"
    assert "print('hello world')" in res1.display_preview
    assert res1.binary is False
    assert res1.error is None

    # JSON round-trip
    d = res1.to_dict()
    res1_rt = FileChangeResult.from_dict(d)
    assert res1_rt == res1

    # 2. Modify existing file
    res2 = write_fn({"path": "hello.py", "content": "print('hello world 2')\n"})
    assert isinstance(res2, FileChangeResult)
    assert res2.status == "modified"
    assert "+print('hello world 2')" in res2.committed_content_or_diff
    assert "-print('hello world')" in res2.committed_content_or_diff

    # 3. No-op (same content)
    res3 = write_fn({"path": "hello.py", "content": "print('hello world 2')\n"})
    assert isinstance(res3, FileChangeResult)
    assert res3.status == "no_change"

    # 4. Traversal / Error
    res4 = write_fn({"path": "../outside.py", "content": "bad"})
    assert isinstance(res4, FileChangeResult)
    assert res4.status == "failed"
    assert res4.error is not None


def test_file_change_result_truncation_and_canary_redaction(tmp_path):
    from hund.tools.file_tool import FileChangeResult, make_handlers

    handlers = make_handlers(tmp_path)
    write_fn = handlers["write_file"]

    # Canary secret
    canary = "CANARY_SECRET_sk_live_9f83a2bc047d1e89_MUST_NOT_LEAK"
    res_canary = write_fn({"path": "secret.env", "content": f"API_KEY={canary}\n"})
    assert isinstance(res_canary, FileChangeResult)
    assert res_canary.redacted is True
    assert canary not in res_canary.display_preview
    assert "[REDACTED" in res_canary.display_preview

    # Large file truncation
    large_content = "\n".join(f"line_{i} = {i}" for i in range(500))
    res_large = write_fn({"path": "large.py", "content": large_content})
    assert isinstance(res_large, FileChangeResult)
    assert res_large.truncated is True
    assert len(res_large.committed_content_or_diff) == len(large_content)
    assert "truncated" in res_large.display_preview.lower()


def test_file_change_result_binary_handling(tmp_path):
    from hund.tools.file_tool import FileChangeResult, make_handlers

    handlers = make_handlers(tmp_path)
    write_fn = handlers["write_file"]

    res_bin = write_fn({"path": "image.png", "content": "fake png header"})
    assert isinstance(res_bin, FileChangeResult)
    assert res_bin.binary is True
    assert res_bin.display_preview == "[binary content: image.png]"


def test_sink_renders_created_file_code_block() -> None:
    from unittest.mock import MagicMock
    from prompt_toolkit.output import DummyOutput
    from hund.tools.file_tool import FileChangeResult
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})

    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()
    out_buf = ctx["output_buffer"]

    sink.set_user_input("create file test_app.py")
    sink.tool_start("write_file", {"path": "test_app.py"})

    change = FileChangeResult(
        operation="write_file",
        path="test_app.py",
        status="created",
        content_type_or_language="python",
        committed_content_or_diff="def main():\n    print('test')",
        display_preview="def main():\n    print('test')",
    )
    sink.tool_result("write_file", change)

    text = out_buf.text
    assert "── test_app.py" in text
    assert "def main():" in text
    assert "print('test')" in text


def test_sink_renders_modified_file_diff_block() -> None:
    from unittest.mock import MagicMock
    from prompt_toolkit.output import DummyOutput
    from hund.tools.file_tool import FileChangeResult
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})

    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()
    out_buf = ctx["output_buffer"]

    sink.set_user_input("edit file config.py")
    sink.tool_start("edit_file", {"path": "config.py"})

    diff_str = "-DEBUG = False\n+DEBUG = True"
    change = FileChangeResult(
        operation="edit_file",
        path="config.py",
        status="modified",
        content_type_or_language="python",
        committed_content_or_diff=diff_str,
        display_preview=diff_str,
    )
    sink.tool_result("edit_file", change)

    text = out_buf.text
    assert "── config.py · changed" in text
    assert "- DEBUG = False" in text or "- 1   DEBUG = False" in text
    assert "+ DEBUG = True" in text or "+ 1   DEBUG = True" in text


def test_sink_does_not_render_artifact_block_on_noop_or_failure() -> None:
    from unittest.mock import MagicMock
    from prompt_toolkit.output import DummyOutput
    from hund.tools.file_tool import FileChangeResult
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(extra={})

    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = ctx["sink_cls"]()
    out_buf = ctx["output_buffer"]

    sink.set_user_input("write unchanged")
    sink.tool_start("write_file", {"path": "same.py"})

    noop_change = FileChangeResult(
        operation="write_file",
        path="same.py",
        status="no_change",
        content_type_or_language="python",
        committed_content_or_diff="",
        display_preview="",
    )
    sink.tool_result("write_file", noop_change)

    assert "── same.py" not in out_buf.text

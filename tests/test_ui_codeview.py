"""Unit tests for UI code block and diff rendering in response box (Etapp 2.4)."""
from __future__ import annotations

from hund.ui.output import StreamingMarkdownFilter, transform_streaming_markdown
from hund.ui.render import format_code_block, format_diff_block


def test_streaming_markdown_filter_buffers_and_emits_code_fence() -> None:
    f = StreamingMarkdownFilter()
    raw = "Here is the code:\n```python auth.py\ndef hello():\n    return 'world'\n```\nDone."
    streamed = f.feed(raw) + f.flush()

    assert "```" not in streamed
    assert "auth.py" in streamed
    assert "def hello():" in streamed
    assert "Done." in streamed


def test_streaming_markdown_filter_handles_diff_fence() -> None:
    f = StreamingMarkdownFilter()
    raw = "```diff auth.py\n def login():\n-    return None\n+    return user\n```"
    streamed = f.feed(raw) + f.flush()

    assert "```" not in streamed
    assert "auth.py" in streamed
    assert "return None" in streamed
    assert "return user" in streamed


def test_format_code_block_no_raw_fences() -> None:
    code = "def add(a, b):\n    return a + b"
    formatted = format_code_block(code, language="python", filename="math.py", width=70)

    assert "```" not in formatted
    assert "math.py" in formatted
    assert "def add(a, b):" in formatted
    assert "──" in formatted


def test_format_diff_block_line_numbers_are_fixed_for_short_diffs() -> None:
    diff_2 = "- old_line\n+ new_line"
    formatted = format_diff_block(diff_2, filename="short.py", width=70)

    lines = [line for line in formatted.splitlines() if line.startswith(("-", "+"))]
    assert lines[0].startswith("- 1   ")
    assert lines[1].startswith("+ 1   ")


def test_format_diff_block_line_numbers_shown_for_3_or_more_lines() -> None:
    # 4 lines total -> show line numbers
    diff_4 = "  context line 1\n- old line 2\n+ new line 2\n  context line 3"
    formatted = format_diff_block(diff_4, filename="auth.py", width=70)

    assert "auth.py" in formatted
    lines = [line for line in formatted.splitlines() if line.strip() and not line.startswith("└")]
    assert any("1" in line for line in lines)
    assert any("2" in line and "-" in line for line in lines)
    assert any("2" in line and "+" in line for line in lines)
    assert any("3" in line for line in lines)


def test_smart_filename_detection_from_leading_comment() -> None:
    # Python code with # memory.py as first comment line
    code = "# memory.py\nimport sys\ndef mem():\n    return 100"
    formatted = format_code_block(code, language="python", filename="", width=70)

    assert "── memory.py" in formatted
    # Leading redundant comment should be stripped from body
    assert "# memory.py" not in formatted.split("── memory.py")[1].splitlines()[1]

    # Diff with // auth.ts leading comment
    diff = "// auth.ts\n- const a = 1\n+ const a = 2"
    formatted_diff = format_diff_block(diff, filename="", width=70)
    assert "└ auth.ts  (+1 -1)" in formatted_diff


def test_theme_add_del_styles() -> None:
    from hund.ui.theme import make_pt_style
    st = make_pt_style("bone")

    # Check style rules for add and del: bg only, no fg override, no strike
    rules_dict = dict(st.style_rules)
    assert "add" in rules_dict
    assert "del" in rules_dict
    assert "bg:#1e2b22" in rules_dict["add"].lower()
    assert "bg:#3d1e24" in rules_dict["del"].lower()
    assert "fg:" not in rules_dict["add"].lower()
    assert "strike" not in rules_dict["del"].split()
    assert not st.get_attrs_for_style_str("class:del").strike
    assert "backdrop" in rules_dict


def test_parse_semantic_line_unnumbered_diff_del() -> None:
    from hund.ui.fullscreen import _parse_semantic_line
    tokens = _parse_semantic_line("- PORT = 8000")

    assert any(t[0] == "class:del" and "- " in t[1] for t in tokens)
    assert not any(t[0] == "class:bullet" for t in tokens)


def test_parse_semantic_line_regular_bullet_never_del() -> None:
    from hund.ui.fullscreen import _parse_semantic_line
    tokens = _parse_semantic_line("- Vill du att hund kör testet nu?")

    assert any(t[0] == "class:bullet" for t in tokens)
    assert not any(t[0] == "class:del" for t in tokens)


def test_pygments_lex_code_highlighting() -> None:
    from hund.ui.fullscreen import _lex_pygments_code
    tokens = _lex_pygments_code("def hello():", "  ", "python")

    assert tokens[0] == ("", "  ")
    assert any("class:syntax_keyword" in t[0] and t[1] == "def" for t in tokens)
    assert any("class:syntax_function" in t[0] and t[1] == "hello" for t in tokens)

    # Verify diff background row_style is preserved alongside syntax classes
    tokens_add = _lex_pygments_code("def hello():", "  ", "python", row_style="class:add")
    assert tokens_add[0] == ("class:add", "  ")
    assert any(t[0] == "class:add class:syntax_keyword" and t[1] == "def" for t in tokens_add)
    assert any(t[0] == "class:add class:syntax_function" and t[1] == "hello" for t in tokens_add)


def test_deleted_diff_rows_do_not_use_strike() -> None:
    from hund.ui import theme

    st = theme.make_pt_style()
    assert "strike" not in dict(st.style_rules)["del"].split()
    assert not st.get_attrs_for_style_str("class:del").strike


def test_unregistered_box_line_lexes_without_error() -> None:
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _OutputLexer

    get_line = _OutputLexer().lex_document(Document("│ ordinary response │"))
    assert get_line(0)


def test_output_lexer_backdrop_dim_when_modal_active() -> None:
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _MODAL_ACTIVE, _OutputLexer

    doc = Document("Hello world\nThis is chat output")
    lexer = _OutputLexer()

    # When inactive: normal tokens
    _MODAL_ACTIVE[0] = False
    getter = lexer.lex_document(doc)
    normal_tokens = getter(0)
    assert not any(t[0] == "class:backdrop" for t in normal_tokens)

    # When active: backdrop dim token
    _MODAL_ACTIVE[0] = True
    getter = lexer.lex_document(doc)
    dim_tokens = getter(0)
    assert dim_tokens[0][0] == "class:backdrop"
    assert dim_tokens[0][1] == "Hello world"

    _MODAL_ACTIVE[0] = False

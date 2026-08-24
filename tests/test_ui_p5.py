"""Tester for hund.ui P5: Response box side rails, deterministic word-wrap, and meta border."""
from __future__ import annotations

from io import StringIO
from rich.console import Console

from hund.ui.output import StreamingSink
from hund.ui.render import box_bottom, box_top, render_response_box, response_padding, wrap_content


def test_wrap_content_deterministic_line_lengths() -> None:
    term_width = 80
    content_width = term_width - 4  # 76
    long_text = (
        "Hund is an autonomous AI agent engineered for deep developer workflows, "
        "local tool dispatching, code generation, and self-improving motor skills. "
        "Every single line inside the response box must be hard-wrapped deterministically."
    )
    wrapped = wrap_content(long_text, content_width)
    assert len(wrapped) > 1
    for line in wrapped:
        assert len(line) <= content_width
        assert len(line) <= term_width - 2


def test_wrap_content_preserves_empty_lines() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    wrapped = wrap_content(text, 76)
    assert "" in wrapped
    assert wrapped[0] == "First paragraph."
    assert wrapped[1] == ""
    assert wrapped[2] == "Second paragraph."


def test_wrap_content_unbreakable_long_word() -> None:
    long_url = "https://example.com/very/deep/nested/directory/structure/and/unbreakable/token/identifier/file.json"
    wrapped = wrap_content(long_url, 30)
    assert len(wrapped) > 1
    assert "".join(wrapped) == long_url
    assert all(len(line) <= 30 for line in wrapped)


def test_long_horizontal_rule_never_crosses_right_rail() -> None:
    box = render_response_box("─" * 200, terminal_width=48)
    assert all(len(line) == 48 for line in box.splitlines())
    assert all(not line.startswith("│") or line.endswith("│") for line in box.splitlines())


def test_render_response_box_fullscreen_and_padding() -> None:
    short_reply = "hund är vaken."
    box = render_response_box(short_reply, terminal_width=80)
    lines = box.split("\n")
    # Top border, 1 top padding row, content, bottom padding row, bottom border = 5 lines per TUI_FACIT.md §2
    assert len(lines) == 5
    assert lines[0].startswith("╭─ hund ")
    assert lines[0].endswith("╮")
    assert lines[1].startswith("│") and lines[1].endswith("│") and not lines[1].strip("│ ")
    assert lines[2].startswith("│   hund är vaken.")
    assert lines[2].endswith("   │")
    assert lines[3].startswith("│") and lines[3].endswith("│") and not lines[3].strip("│ ")
    assert lines[4].startswith("╰")
    assert lines[4].endswith("╯")

    # Assert all lines span the full terminal width (80)
    for line in lines:
        assert len(line) == 80


def test_render_response_box_long_full_width() -> None:
    long_reply = (
        "Hund analyserar repot och ser flera ändringar i konfigurationen. "
        "Alla moduler har validerats och testats utan regressioner eller problem. "
        "Koden är optimerad och redo för produktion."
    )
    term_width = 80
    box = render_response_box(long_reply, terminal_width=term_width)
    lines = box.split("\n")
    assert len(lines) >= 5
    for line in lines:
        assert len(line) == term_width
        if line.startswith("│") and line.strip("│ "):
            assert line.startswith("│   ")
            assert line.endswith("   │")


def test_response_padding_is_responsive_and_stable() -> None:
    assert response_padding(100) == 3
    assert response_padding(72) == 3
    assert response_padding(71) == 2
    assert response_padding(48) == 2
    assert response_padding(47) == 1


def test_box_bottom_meta_render() -> None:
    bottom_plain = box_bottom(80, meta=None)
    assert bottom_plain.startswith("╰")
    assert bottom_plain.endswith("╯")
    assert len(bottom_plain) == 80

    bottom_meta = box_bottom(80, meta="2.3s")
    assert "2.3s ────╯" in bottom_meta
    assert len(bottom_meta) == 80

    # Short box
    bottom_short = box_bottom(12, meta="2.3s")
    assert "2.3s ────╯" in bottom_short


def test_streaming_sink_renders_rails_and_meta() -> None:
    out = StringIO()
    console = Console(force_terminal=False, width=80, file=out)
    sink = StreamingSink(console, stream_delay_s=0)

    sink.chunk("hund svarar med sidolinjer.")
    sink.end_assistant()

    captured = out.getvalue()
    assert "╭─ hund " in captured
    assert "│   hund svarar med sidolinjer." in captured
    assert "│" in captured
    assert "╰" in captured
    assert "╯" in captured


def test_output_lexer_box_and_thinking_styles() -> None:
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _OUTPUT_LEXER

    doc = Document(
        "  hund planned.\n"
        "╭─ hund ──────────────────────────────────────────────╮\n"
        "│                                                      │\n"
        "│                                                      │\n"
        "│   hund skapar skills som deklarativa JSON-filer      │\n"
        "│   Hur hund går tillväga:                             │\n"
        "│   - 1. Trigger: användaren ber hund skapa            │\n"
        "│   detta är **fetstil** och `inline_kod` här.         │\n"
        "│                                                      │\n"
        "╰──────────────────────────────────────────────────────╯\n"
    )
    lexer_fn = _OUTPUT_LEXER.lex_document(doc)

    # Line 0: "  hund planned." -> class:secondary (dim)
    t0 = lexer_fn(0)
    assert any(style == "class:secondary" for style, text in t0 if "hund planned." in text)

    # Line 1: "┌─ hund ..." -> border with accent bold "hund"
    t1 = lexer_fn(1)
    assert any("hund" in text and "class:accent" in style for style, text in t1)

    # Line 2 & 3: padding lines -> class:secondary
    t2 = lexer_fn(2)
    assert t2[0][0] == "class:secondary"
    t3 = lexer_fn(3)
    assert t3[0][0] == "class:secondary"

    # Line 4: "│  hund skapar skills ...  │" -> primary text
    t4 = lexer_fn(4)
    assert t4[0] == ("class:secondary", "│  ")
    assert any("hund skapar skills" in text and style == "class:primary" for style, text in t4)
    assert t4[-1] == ("class:secondary", "  │")

    # Line 5: "│  Hur hund går tillväga: ...  │" -> label bold
    t5 = lexer_fn(5)
    assert any("Hur hund går tillväga:" in text and "class:label" in style for style, text in t5)

    # Line 6: "│  - 1. Trigger: användaren ber hund skapa ...  │" -> bullet + number + label + primary
    t6 = lexer_fn(6)
    assert any(style == "class:bullet" for style, text in t6)
    assert any(style == "class:number" for style, text in t6)
    assert any("Trigger:" in text and "class:label" in style for style, text in t6)
    assert any("användaren ber hund skapa" in text and style == "class:primary" for style, text in t6)

    # Line 7: "│  detta är **fetstil** och `inline_kod` här.          │"
    # Markers must be stripped in tokens: "fetstil" (no **) and "inline_kod" (no `)
    t7 = lexer_fn(7)
    assert any(style == "class:label" and text == "fetstil" for style, text in t7)
    assert not any("**" in text for style, text in t7)
    assert any(style == "class:code" and text == "inline_kod" for style, text in t7)
    assert not any("`" in text for style, text in t7)


def test_rounded_response_bottom_is_never_user_or_success_green() -> None:
    from prompt_toolkit.document import Document
    from hund.ui.fullscreen import _OUTPUT_LEXER

    doc = Document("╰────────────────────────────────── 0.4s ────╯")
    tokens = _OUTPUT_LEXER.lex_document(doc)(0)
    assert any("class:accent" in style and text == "0.4s" for style, text in tokens)
    assert all("class:user" not in style for style, _text in tokens)
    assert all("class:success" not in style for style, _text in tokens)

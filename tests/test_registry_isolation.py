"""Tests proving app-local ResponseBlockRegistry isolation."""
import pytest
from prompt_toolkit.document import Document
from hund.ui.fullscreen import ResponseBlockRegistry, _OutputLexer
from hund.ui.output import parse_semantic_segments
from hund.ui.render import render_response_box_from_segments


def test_registry_isolation_between_instances():
    """Verify that multiple registries/lexers in the same process do not leak metadata."""
    reg1 = ResponseBlockRegistry()
    reg2 = ResponseBlockRegistry()

    lexer1 = _OutputLexer(block_registry=reg1)
    lexer2 = _OutputLexer(block_registry=reg2)

    # Register code block in registry 1
    segs1 = parse_semantic_segments("```python\nx = 100\n```")
    box1, meta1 = render_response_box_from_segments(segs1, terminal_width=50)
    reg1.register_or_update(1, start_line=0, line_count=box1.count("\n") + 1, line_metadata=meta1)

    # Register diff block in registry 2 at same start line
    segs2 = parse_semantic_segments("```diff\n+ added_line\n```")
    box2, meta2 = render_response_box_from_segments(segs2, terminal_width=50)
    reg2.register_or_update(1, start_line=0, line_count=box2.count("\n") + 1, line_metadata=meta2)

    doc1 = Document(box1)
    doc2 = Document(box2)

    style_fn1 = lexer1.lex_document(doc1)
    style_fn2 = lexer2.lex_document(doc2)

    # Line 2 in box1 is code; line 2 in box2 is diff
    assert reg1.get_line_style(2) == ("code", "python")
    assert reg2.get_line_style(2) == ("diff", "diff")

    # Clearing reg1 has zero effect on reg2
    reg1.clear()
    assert reg1.get_line_style(2) is None
    assert reg2.get_line_style(2) == ("diff", "diff")

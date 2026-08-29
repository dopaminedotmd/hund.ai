"""Tests proving reflow preserves semantic metadata and offsets across resizing."""
import pytest
from prompt_toolkit.document import Document
from hund.ui.fullscreen import ResponseBlockRegistry, ResponsePayloadRecord, _OutputLexer
from hund.ui.output import parse_semantic_segments
from hund.ui.render import render_response_box_from_segments


def test_multi_turn_reflow_metadata_integrity():
    """Verify that reflowing response boxes at different widths preserves exact line styles."""
    turn1_source = "Here is an explanation of the algorithm."
    turn2_source = "```python\ndef factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)\n```"
    turn3_source = "```diff\n--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,3 @@\n-old_func()\n+new_func()\n```"

    segs1 = parse_semantic_segments(turn1_source)
    segs2 = parse_semantic_segments(turn2_source)
    segs3 = parse_semantic_segments(turn3_source)

    payloads = [
        ResponsePayloadRecord(block_id=1, canonical_chunks=[turn1_source], segments=segs1),
        ResponsePayloadRecord(block_id=2, canonical_chunks=[turn2_source], segments=segs2, meta="0.4s"),
        ResponsePayloadRecord(block_id=3, canonical_chunks=[turn3_source], segments=segs3, meta="1.2s"),
    ]

    for width in (40, 70, 120):
        registry = ResponseBlockRegistry()
        lines: list[str] = []
        # Add a simulated activity line between turn 1 and 2
        for idx, rec in enumerate(payloads):
            if idx == 1:
                lines.append("  ┊ ✓ read relevant files    2 files · 0.2s")
                lines.append("")
            re_boxed, line_meta = render_response_box_from_segments(rec.segments, width, meta=rec.meta)
            start_line_idx = len(lines)
            line_count = re_boxed.count("\n") + 1
            registry.register_or_update(rec.block_id, start_line_idx, line_count, line_meta)
            lines.extend(re_boxed.split("\n"))
            lines.append("")

        doc_text = "\n".join(lines)
        doc = Document(doc_text)
        lexer = _OutputLexer(block_registry=registry)
        get_line_style = lexer.lex_document(doc)

        # Check that Turn 2's code lines are typed as ("code", "python")
        rec2_block = registry._blocks[2]
        # Line 2 inside block 2 (def factorial)
        assert registry.get_line_style(rec2_block.start_line + 2) == ("code", "python")

        # Check that Turn 3's diff lines are typed as ("diff", "diff")
        rec3_block = registry._blocks[3]
        # Line with +new_func() inside diff
        assert registry.get_line_style(rec3_block.start_line + 3) == ("diff", "diff")

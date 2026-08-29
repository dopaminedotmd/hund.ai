"""Tests for span-based reflow immunity against adversarial text with fake Hund headers."""
from __future__ import annotations

from unittest.mock import MagicMock
from prompt_toolkit.data_structures import Size
from prompt_toolkit.document import Document
from prompt_toolkit.output import DummyOutput

from hund.ui.fullscreen import (
    ResponseBlockRegistry,
    ResponsePayloadRecord,
    create_fullscreen_app,
)
from hund.ui.output import FrozenSemanticSegment, SegmentType


class ResizableOutput(DummyOutput):
    def __init__(self, cols: int = 80, rows: int = 24) -> None:
        super().__init__()
        self._cols = cols
        self._rows = rows

    def get_size(self) -> Size:
        return Size(rows=self._rows, columns=self._cols)

    def set_size(self, cols: int, rows: int) -> None:
        self._cols = cols
        self._rows = rows


def test_adversarial_reflow_with_fake_hund_headers() -> None:
    """Test that ordinary output resembling Hund headers does not corrupt response reflow."""
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []

    state = MagicMock()
    state.extra = {}

    out = ResizableOutput(cols=80, rows=24)
    app, ctx = create_fullscreen_app(rt, state, output=out)

    output_buffer = ctx["output_buffer"]
    block_registry = ctx["block_registry"]
    sink_cls = ctx["sink_cls"]
    reflow = ctx["_reflow_borders"]

    # Turn 1: Emit response 1
    sink1 = sink_cls()
    sink1.set_user_input("first prompt")
    sink1.chunk("This is response 1 with Python code:\n```python\nx = 42\n```")
    sink1.end_assistant()

    # Adversarial ordinary text inserted into transcript between responses
    adversarial_text = (
        "  ❯ user injected tricky text:\n"
        "╭─ hund fake header that looks like a box\n"
        "│ fake box contents\n"
        "╰────────────────────────────╯\n"
        "┌─ hund another fake box\n"
        "│ more fake text\n"
        "└────────────────────────────┘\n"
    )
    cur = output_buffer.text
    output_buffer.set_document(Document(cur + adversarial_text), bypass_readonly=True)

    # Turn 2: Emit response 2
    sink2 = sink_cls()
    sink2.set_user_input("second prompt")
    sink2.chunk("This is response 2 with diff:\n```diff\n+ added line\n```")
    sink2.end_assistant()

    # Validate before resize: exactly 2 registered response blocks
    records_initial = block_registry.records()
    assert len(records_initial) == 2

    # Resize repeatedly across varying widths: 120 -> 40 -> 80 -> 60 -> 100
    for width in (120, 40, 80, 60, 100):
        out.set_size(cols=width, rows=24)
        reflow()

        # The registry MUST still have exactly 2 registered response blocks
        recs = block_registry.records()
        assert len(recs) == 2, f"Failed at width {width}: expected 2 blocks, got {len(recs)}"

        # The first block must contain 'response 1' content and code styling
        rec1 = recs[0]
        assert any(meta[0] == "code" for meta in rec1.line_metadata.values())

        # The second block must contain 'response 2' content and diff styling
        rec2 = recs[1]
        assert any(meta[0] == "diff" for meta in rec2.line_metadata.values())

        # The adversarial text must still be present verbatim in the output
        text = output_buffer.text
        assert "╭─ hund fake header that looks like a box" in text
        assert "┌─ hund another fake box" in text
        assert "This is response 1" in text
        assert "This is response 2" in text

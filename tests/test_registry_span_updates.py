"""Tests for ResponseBlockRegistry span lifecycle and line offset operations."""
from __future__ import annotations

import re
from unittest.mock import MagicMock
from prompt_toolkit.data_structures import Size
from prompt_toolkit.output import DummyOutput

from hund.ui.fullscreen import (
    ResponseBlockRecord,
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


def test_registry_shift_after_updates_spans_cleanly() -> None:
    """Test shift_after moves all block spans at or below threshold line."""
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, start_line=10, line_count=5, line_metadata={})
    registry.register_or_update(2, start_line=20, line_count=8, line_metadata={})
    registry.register_or_update(3, start_line=35, line_count=4, line_metadata={})

    # Shift after line 15 by +3 lines
    registry.shift_after(line_idx=15, delta_lines=3)

    records = {r.block_id: r for r in registry.records()}
    assert records[1].start_line == 10  # Unchanged (was before 15)
    assert records[2].start_line == 23  # Shifted +3
    assert records[3].start_line == 38  # Shifted +3


def test_malformed_or_overlapping_span_recovery() -> None:
    """Test that reflow recovers safely from malformed/out-of-bounds spans."""
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
    reflow = ctx["_reflow_borders"]

    # Register an invalid span exceeding document bounds
    block_registry.register_or_update(
        999,
        start_line=5000,
        line_count=100,
        line_metadata={0: ("code", "python")},
    )

    # Trigger reflow - it must NOT crash or corrupt the existing document text
    initial_text = output_buffer.text
    out.set_size(cols=100, rows=24)
    reflow()

    assert re.findall(r"[A-Za-z0-9_.]+", output_buffer.text) == re.findall(
        r"[A-Za-z0-9_.]+", initial_text
    )
    assert block_registry.records() == ()
    assert block_registry.get_line_style(5000) is None


def test_overlapping_spans_clear_stale_semantic_metadata() -> None:
    """Overlapping spans preserve text but cannot retain styles for unrelated lines."""
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []

    state = MagicMock()
    state.extra = {}

    out = ResizableOutput(cols=80, rows=24)
    _app, ctx = create_fullscreen_app(rt, state, output=out)
    output_buffer = ctx["output_buffer"]
    block_registry = ctx["block_registry"]
    initial_text = output_buffer.text

    block_registry.register_or_update(1, 0, 2, {0: ("code", "python")})
    block_registry.register_or_update(2, 1, 2, {0: ("diff", "diff")})
    ctx["_reflow_borders"]()

    assert output_buffer.text == initial_text
    assert block_registry.records() == ()
    assert block_registry.get_line_style(0) is None
    assert block_registry.get_line_style(1) is None


def test_reflection_lines_and_multi_turn_history() -> None:
    """Test reflection lines appended after responses preserve correct block spans."""
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []

    state = MagicMock()
    state.extra = {}

    out = ResizableOutput(cols=80, rows=24)
    app, ctx = create_fullscreen_app(rt, state, output=out)

    sink_cls = ctx["sink_cls"]
    block_registry = ctx["block_registry"]
    reflow = ctx["_reflow_borders"]

    # Turn 1
    sink1 = sink_cls()
    sink1.set_user_input("hello")
    sink1.chunk("Response with reflection text.")
    sink1.end_assistant()

    # Turn 2
    sink2 = sink_cls()
    sink2.set_user_input("second message")
    sink2.chunk("Another response block.")
    sink2.end_assistant()

    recs = block_registry.records()
    assert len(recs) == 2
    assert recs[0].start_line < recs[1].start_line

    # Resize output and check spans remain monotonically ordered
    out.set_size(cols=60, rows=24)
    reflow()

    recs_resized = block_registry.records()
    assert len(recs_resized) == 2
    assert recs_resized[0].start_line < recs_resized[1].start_line
    assert recs_resized[0].start_line + recs_resized[0].line_count <= recs_resized[1].start_line

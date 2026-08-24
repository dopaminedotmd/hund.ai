"""Small test seam for Prompt Toolkit construction compatibility."""
from __future__ import annotations

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl


def create_tui_layout() -> Layout:
    """Construct and return a renderable layout using supported public APIs."""
    output = Window(
        content=FormattedTextControl(lambda: [("class:output", "Hund")]),
        wrap_lines=True,
    )
    input_buffer = Buffer()
    input_window = Window(
        content=BufferControl(buffer=input_buffer, focus_on_click=True),
        height=1,
    )
    return Layout(HSplit([output, input_window]), focused_element=input_window)


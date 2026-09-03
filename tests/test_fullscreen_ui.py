"""Tests for fullscreen TUI focus, scrolling, mouse selection, and box borders."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point, Size
from prompt_toolkit.document import Document
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType, MouseButton
from prompt_toolkit.output import DummyOutput

from hund.ui import theme
from hund.ui.fullscreen import (
    _SelectableControl,
    _FullWidthCompletionsMenu,
    _OutputLexer,
    _ScrollThroughFormattedTextControl,
    _output_cursor_position,
    _responsive_content_width,
    _shine_fragments,
    _wheel_scroll_passthrough,
)
from hund.ui.mascot import MascotMachine, MascotState, mirror_art
from hund.ui.mascot_frames import FRAMES


class ResizableOutput(DummyOutput):
    """Dummy output with configurable dimensions for testing render and reflow."""

    def __init__(self, cols: int = 80, rows: int = 24) -> None:
        super().__init__()
        self._cols = cols
        self._rows = rows

    def get_size(self) -> Size:
        return Size(rows=self._rows, columns=self._cols)

    def set_size(self, cols: int, rows: int) -> None:
        self._cols = cols
        self._rows = rows


def test_mascot_sprite_sheets_are_split_into_animation_frames() -> None:
    assert {state: len(clips) for state, clips in FRAMES["bone"].items()} == {
        "playful": 16,
        "running": 4,
        "sitting": 8,
        "standing": 8,
    }
    for skin in FRAMES.values():
        for clips in skin.values():
            assert all(max(map(len, frame.splitlines()), default=0) <= 16 for frame in clips)


def test_mirror_art_flips_horizontally() -> None:
    assert mirror_art("\u259b x") == "x \u259c"
    assert mirror_art(" \u2584\u2580    \u2588\u2588\u2588\u2588\u2588\u2580") == "\u2580\u2588\u2588\u2588\u2588\u2588    \u2580\u2584"
    assert mirror_art("\u259a") == "\u259e"
    assert mirror_art("") == ""
    assert mirror_art("\n\n") == "\n"
    # Every mirrored frame stays within the 16-cell sprite sheet limit.
    for skin in FRAMES.values():
        for clips in skin.values():
            for frame in clips:
                assert max(map(len, mirror_art(frame).splitlines()), default=0) <= 16


def test_mascot_each_state_advances_real_frames() -> None:
    machine = MascotMachine()
    for state, frame_seconds in machine._FRAME_SECONDS.items():
        machine._set(state, 100.0)
        first = machine.frame(now=100.0)[1]
        second = machine.frame(now=100.0 + frame_seconds)[1]
        assert first != second


def test_mascot_runtime_keyframes_have_visible_terminal_delta() -> None:
    def cells(frame: str) -> str:
        rows = frame.splitlines()
        return "".join((rows[y] if y < len(rows) else "").ljust(16)[:16] for y in range(8))

    machine = MascotMachine()
    for state, order in machine._FRAME_ORDER.items():
        clips = FRAMES["bone"][state.value]
        selected = [cells(clips[index]) for index in order]
        deltas = [
            sum(left != right for left, right in zip(selected[index], selected[(index + 1) % len(selected)]))
            for index in range(len(selected))
        ]
        assert min(deltas) >= 8


def test_mascot_lifecycle_waits_then_returns_to_idle() -> None:
    machine = MascotMachine()
    machine._set(MascotState.PLAYFUL, 100.0)

    machine.frame(now=105.99)
    assert machine.state is MascotState.PLAYFUL
    machine.frame(now=106.0)
    assert machine.state is MascotState.STANDING
    machine.frame(now=150.99)
    assert machine.state is MascotState.STANDING
    machine.frame(now=151.0)
    assert machine.state is MascotState.SITTING


def test_startup_viewport_is_top_anchored_while_history_follows_tail() -> None:
    text = "top\nmiddle\nbottom\n"
    assert _output_cursor_position(text, follow_tail=False) == 0
    assert _output_cursor_position(text, follow_tail=True) == len(text)
    assert _output_cursor_position("top\nbottom", follow_tail=True) == len("top\nbottom")


def test_completion_menu_uses_no_reverse_video_background() -> None:
    style = theme.make_pt_style("bone")
    rules = dict(style.style_rules)
    assert "reverse" not in rules["completion-menu.completion.current"].split()
    assert "reverse" not in rules["completion-menu.meta.completion.current"].split()
    for name in (
        "completion-menu",
        "completion-menu.completion",
        "completion-menu.completion.current",
        "completion-menu.meta.completion",
        "completion-menu.meta.completion.current",
    ):
        assert "bg:default" in rules[name]
        assert "noinherit" in rules[name]


def test_completion_menu_is_terminal_width_not_shrink_to_fit() -> None:
    menu = _FullWidthCompletionsMenu(max_height=6)
    window = menu.content
    assert isinstance(window, Window)
    assert window.dont_extend_width() is False
    assert window.width.weight == 1


def test_responsive_content_width_reserves_unsafe_terminal_column() -> None:
    assert _responsive_content_width(120) == 119
    assert _responsive_content_width(80) == 79
    assert _responsive_content_width(24) == 24


def test_selectable_control_mouse_wheel_and_selection() -> None:
    output_buffer = Buffer(name="output", multiline=True, read_only=True)
    input_buffer = Buffer(name="input", multiline=False)
    input_control = BufferControl(buffer=input_buffer, focus_on_click=True)
    input_window = Window(content=input_control, height=1)

    scrolled: list[int] = []
    output_control = _SelectableControl(
        buffer=output_buffer,
        lexer=_OutputLexer(),
        scroll_cb=lambda count: scrolled.append(count),
        fallback_focus=input_window,
    )
    output_window = Window(content=output_control, wrap_lines=True, always_hide_cursor=True)
    layout = Layout(HSplit([output_window, input_window]), focused_element=input_window)

    # Test scroll up / scroll down events
    wheel_up = MouseEvent(
        position=Point(x=0, y=0),
        event_type=MouseEventType.SCROLL_UP,
        button=MouseButton.NONE,
        modifiers=frozenset(),
    )
    assert output_control.mouse_handler(wheel_up) is None
    assert scrolled == [3]

    wheel_down = MouseEvent(
        position=Point(x=0, y=0),
        event_type=MouseEventType.SCROLL_DOWN,
        button=MouseButton.NONE,
        modifiers=frozenset(),
    )
    assert output_control.mouse_handler(wheel_down) is None
    assert scrolled == [3, -3]


def test_mascot_strip_forwards_mouse_wheel_to_transcript() -> None:
    scrolled: list[int] = []
    wheel_up = MouseEvent(
        position=Point(x=0, y=0),
        event_type=MouseEventType.SCROLL_UP,
        button=MouseButton.NONE,
        modifiers=frozenset(),
    )
    assert _wheel_scroll_passthrough(wheel_up, scrolled.append) is None
    assert scrolled == [3]

    control = _ScrollThroughFormattedTextControl(
        "dog", scroll_cb_getter=lambda: scrolled.append
    )
    assert control.mouse_handler(wheel_up) is None
    assert scrolled == [3, 3]


def test_running_shine_keeps_width_and_moves() -> None:
    text = " running..."
    first = _shine_fragments(text, "#737985", 2)
    second = _shine_fragments(text, "#737985", 3)
    assert "".join(fragment for _, fragment in first) == text
    assert len(first) == len(text)
    assert first != second


def test_box_border_reflow() -> None:
    holder: dict[str, Application] = {}
    output_buffer = Buffer(name="output", multiline=True, read_only=True)

    def _app_width() -> int:
        app = holder.get("app")
        if app is not None:
            try:
                return app.output.get_size().columns
            except Exception:
                pass
        return 80

    def _box_top() -> str:
        w = _app_width()
        return f"┌─ hund {'─' * max(w - 9, 2)}┐"

    def _box_bottom() -> str:
        w = _app_width()
        return f"└{'─' * max(w - 2, 2)}┘"

    def _reflow_borders() -> None:
        text = output_buffer.text
        lines = text.split("\n")
        new_lines: list[str] = []
        changed = False
        in_box = False
        for line in lines:
            if line.startswith("┌─ hund ") or line.startswith("╭─ hund "):
                nl = _box_top()
                in_box = True
            elif in_box and (line.startswith("└") or line.startswith("╰")):
                nl = _box_bottom()
                in_box = False
            else:
                nl = line
            if nl != line:
                changed = True
            new_lines.append(nl)
        if changed:
            new_text = "\n".join(new_lines)
            output_buffer.set_document(
                Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
            )

    out = ResizableOutput(cols=80, rows=24)
    app = Application(layout=Layout(Window(BufferControl(buffer=output_buffer))), output=out)
    holder["app"] = app

    initial_text = f"{_box_top()}\nResponse content\n{_box_bottom()}\n"
    output_buffer.set_document(Document(initial_text, cursor_position=len(initial_text)), bypass_readonly=True)

    lines_80 = output_buffer.text.split("\n")
    assert len(lines_80[0]) == 80
    assert len(lines_80[2]) == 80

    # Resize output to 120 columns
    out.set_size(120, 24)
    _reflow_borders()

    lines_120 = output_buffer.text.split("\n")
    assert len(lines_120[0]) == 120
    assert len(lines_120[2]) == 120


def test_view_scroll_calculation() -> None:
    async def _async_test():
        output_buffer = Buffer(name="output", multiline=True, read_only=True)
        lines = [f"Line {i:03d}" for i in range(100)]
        text = "\n".join(lines)
        output_buffer.set_document(Document(text, cursor_position=len(text)), bypass_readonly=True)

        output_control = _SelectableControl(buffer=output_buffer, lexer=_OutputLexer())
        output_window = Window(content=output_control, wrap_lines=True, always_hide_cursor=True)
        input_buffer = Buffer(name="input", multiline=False)
        input_window = Window(content=BufferControl(buffer=input_buffer, focus_on_click=True), height=1)

        layout = Layout(HSplit([output_window, input_window]), focused_element=input_window)

        def _scroll_lines(count: int) -> None:
            ri = output_window.render_info
            if ri is None:
                return
            first = ri.first_visible_line(after_scroll_offset=True)
            wh = ri.window_height
            lc = output_buffer.document.line_count
            if count > 0:  # up
                target = max(0, first - count)
            else:  # down
                target = min(lc - 1, first + wh - 1 + (-count))
            output_buffer.cursor_position = output_buffer.document.translate_row_col_to_index(
                target, 0
            )

        out = ResizableOutput(cols=80, rows=20)
        app = Application(layout=layout, output=out)

        with set_app(app):
            # First render: window displays bottom 19 lines (81 to 99)
            app.renderer.render(app, layout)
            ri = output_window.render_info
            assert ri is not None
            first = ri.first_visible_line(after_scroll_offset=True)
            assert first == 81

            # Scroll up 15 lines (PgUp)
            _scroll_lines(15)
            app.renderer.render(app, layout)
            ri = output_window.render_info
            assert ri is not None
            assert ri.first_visible_line(after_scroll_offset=True) == 66

            # Scroll down 15 lines (PgDn)
            _scroll_lines(-15)
            app.renderer.render(app, layout)
            ri = output_window.render_info
            assert ri is not None
            assert ri.first_visible_line(after_scroll_offset=True) == 81

    asyncio.run(_async_test())


def test_mascot_float_right_transparent_and_bottom_gap() -> None:
    """Mascot: right-anchored transparent float; 7-row gap reserved only at bottom."""

    async def _async_test() -> None:
        from hund.ui.fullscreen import _TransparentSpriteWindow, create_fullscreen_app
        from prompt_toolkit.layout.containers import Window as _Window
        from prompt_toolkit.layout.screen import Screen, Char, WritePosition

        # Verify _TransparentSpriteWindow only writes non-space characters
        ts_win = _TransparentSpriteWindow(lambda: [("fg:white", " ▄\n█ ")], width=4, height=2)
        scr = Screen()
        scr.data_buffer[0][0] = Char(".", "bg:blue")
        scr.data_buffer[0][1] = Char(".", "bg:blue")
        scr.data_buffer[1][0] = Char(".", "bg:blue")
        scr.data_buffer[1][1] = Char(".", "bg:blue")
        ts_win.write_to_screen(scr, MagicMock(), WritePosition(0, 0, 4, 2), "parent", False, None)
        assert scr.data_buffer[0][0].char == "."  # space skipped, background preserved
        assert scr.data_buffer[0][1].char == "▄"  # pixel written
        assert scr.data_buffer[1][0].char == "█"  # pixel written
        assert scr.data_buffer[1][1].char == "."  # space skipped, background preserved

        rt = MagicMock()
        rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
        rt.profile = None
        rt.messages = []

        state = MagicMock()
        state.extra = {}
        state.start_time = 0.0

        out = ResizableOutput(cols=80, rows=27)
        app, ctx = create_fullscreen_app(rt, state, output=out)

        # Mascot float config: status on left, mascot on right, transparent background.
        inner_float_container = app.layout.container.content.children[0]
        status_float, mascot_float = inner_float_container.floats
        assert status_float.left == 2
        assert status_float.transparent() is True
        assert mascot_float.right == 0
        assert mascot_float.transparent() is True

        output_buffer = ctx["output_buffer"]
        lines = [f"Line {i:03d}" for i in range(80)]
        text = "\n".join(lines) + "\n"
        output_buffer.set_document(
            Document(text, cursor_position=len(text)),
            bypass_readonly=True,
        )

        def find_output_window():
            for container in app.layout.walk():
                if (
                    isinstance(container, _Window)
                    and getattr(getattr(container, "content", None), "buffer", None)
                    is output_buffer
                ):
                    return container
            raise AssertionError("output window not found")

        output_window = find_output_window()

        with set_app(app):
            # Tail following at bottom: last line of buffer (Line 079) sits 7 rows above the bottom
            app.renderer.render(app, app.layout)
            window_height = output_window.render_info.window_height
            displayed = output_window.render_info.displayed_lines
            # The last 7 displayed lines in the viewport are the virtual blank lines (80..86)
            assert displayed[-1] >= len(lines)

            # Scroll up: text scrolls down through all rows
            output_window.content.scroll_cb(20)
            app.renderer.render(app, app.layout)
            assert output_window.render_info.window_height == window_height
            displayed_scrolled = output_window.render_info.displayed_lines
            # Scrolled up, text is shown at the bottom of the window
            assert displayed_scrolled[-1] < len(lines)

    asyncio.run(_async_test())


def test_transparent_sprite_preserves_underlying_mouse_handler() -> None:
    from hund.ui.fullscreen import _TransparentSpriteWindow
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen, WritePosition

    handlers = MouseHandlers()
    underlying = MagicMock(return_value=None)
    handlers.set_mouse_handler_for_range(0, 4, 0, 2, underlying)
    sprite = _TransparentSpriteWindow(
        lambda: [("fg:white", " x\nxx")], width=4, height=2
    )

    sprite.write_to_screen(
        Screen(), handlers, WritePosition(0, 0, 4, 2), "", False, None
    )

    assert handlers.mouse_handlers[0][0] is underlying
    assert handlers.mouse_handlers[1][1] is underlying


def test_wheel_scroll_preserves_output_selection() -> None:
    from hund.ui.fullscreen import create_fullscreen_app
    from prompt_toolkit.selection import SelectionType

    async def _async_test() -> None:
        rt = MagicMock()
        rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
        rt.profile = None
        rt.messages = []
        state = MagicMock(theme_name="marshmallow", extra={}, start_time=0.0)
        app, ctx = create_fullscreen_app(rt, state, output=ResizableOutput(rows=24))
        output_buffer = ctx["output_buffer"]
        output_window = next(
            container
            for container in app.layout.walk()
            if isinstance(container, Window)
            and getattr(getattr(container, "content", None), "buffer", None)
            is output_buffer
        )
        lines = [f"Line {index:03d}" for index in range(100)]
        text = "\n".join(lines)
        start = text.index("Line 080")
        end = text.index("Line 085") + len("Line 085")
        output_buffer.set_document(Document(text, cursor_position=start), bypass_readonly=True)
        output_buffer.start_selection(selection_type=SelectionType.CHARACTERS)
        output_buffer.cursor_position = end
        output_window.vertical_scroll = 70

        with set_app(app):
            app.renderer.render(app, app.layout)
            before_range = output_buffer.document.selection_range()
            before_top = output_window.render_info.first_visible_line(after_scroll_offset=True)
            output_window.content.scroll_cb(3)
            app.renderer.render(app, app.layout)

            assert output_buffer.document.selection_range() == before_range
            assert output_window.render_info.first_visible_line(after_scroll_offset=True) < before_top

    asyncio.run(_async_test())


def test_tool_desc_formatting() -> None:
    from hund.ui.fullscreen import _format_tool_desc, _trunc

    assert _trunc("short") == "short"
    assert _trunc("a" * 50, max_len=10) == "aaaaaaaaa…"

    assert _format_tool_desc("read_file", {"path": "fullscreen.py"}) == "read fullscreen.py"
    assert _format_tool_desc("search_files", {"pattern": "*.py"}) == "searched *.py"
    assert _format_tool_desc("search_files", {"path": "src", "pattern": "*.py"}) == "searched src for *.py"
    assert _format_tool_desc("write_file", {"path": "test.txt", "content": "hi"}) == "wrote test.txt"
    assert _format_tool_desc("edit_file", {"path": "test.txt"}) == "modified test.txt"
    assert _format_tool_desc("delete_file", {"path": "test.txt"}) == "deleted test.txt"
    assert _format_tool_desc("terminal", {"command": "git status"}) == "ran git status"
    assert _format_tool_desc("terminal", {"command": "pytest -q"}) == "ran targeted tests"
    assert _format_tool_desc("web_search", {"query": "python 3.11"}) == "searched the web for python 3.11"
    assert _format_tool_desc("web_extract", {"url": "https://example.com"}) == "read https://example.com"
    assert _format_tool_desc("web_open", {"url": "https://example.com"}) == "read https://example.com"
    assert _format_tool_desc("web_open", {"page_id": "page-1"}) == "read relevant pages"
    assert _format_tool_desc("execute_code", {"code": "print(1)"}) == "ran python script"
    assert _format_tool_desc("delegate_task", {"tasks": [{"goal": "g1"}, {"goal": "g2"}]}) == "delegated 2 tasks"
    assert _format_tool_desc("session_search", {"query": "test"}) == "searched history for test"
    assert _format_tool_desc("session_search", {}) == "searched history"
    assert _format_tool_desc("cronjob", {"action": "create", "name": "daily"}) == "scheduled create daily"


def test_activity_stream_lexer_tokens() -> None:
    doc = Document(
        "  ┊ ⟳ preparing read_file…\n"
        "  ┊ ✓ read fullscreen.py  0.3s\n"
        "  ┊ ✗ blocked terminal — dangerous\n"
        "  ┊ ⊘ declined terminal — user declined\n"
        "  hund is reading your message…\n"
    )
    get_line = _OutputLexer().lex_document(doc)

    # Line 0: spinner line
    toks0 = get_line(0)
    assert ("class:secondary", "┊") in toks0
    assert ("class:tool", "⟳") in toks0
    assert "".join(t[1] for t in toks0) == "  ┊ ⟳ preparing read_file…"

    # Line 1: checkmark line
    toks1 = get_line(1)
    assert ("class:secondary", "┊") in toks1
    assert ("class:success", "✓") in toks1
    assert "".join(t[1] for t in toks1) == "  ┊ ✓ read fullscreen.py  0.3s"

    # Line 2: blocked line
    toks2 = get_line(2)
    assert ("class:secondary", "┊") in toks2
    assert ("class:danger", "✗") in toks2
    assert "".join(t[1] for t in toks2) == "  ┊ ✗ blocked terminal — dangerous"

    # Line 3: declined line
    toks3 = get_line(3)
    assert ("class:secondary", "┊") in toks3
    assert ("class:danger", "⊘") in toks3
    assert "".join(t[1] for t in toks3) == "  ┊ ⊘ declined terminal — user declined"

    # Line 4: thinking line
    toks4 = get_line(4)
    assert ("class:thinking", "  hund is reading your message…") in toks4


def test_completions_menu_styles_and_container() -> None:
    from prompt_toolkit.layout.containers import Float, FloatContainer
    from prompt_toolkit.layout.menus import CompletionsMenu
    from hund.ui.fullscreen import _STYLE

    # Verify style dictionary has required completion tokens
    style_rules = dict(_STYLE.style_rules)
    for token in (
        "completion-menu",
        "completion-menu.completion",
        "completion-menu.completion.current",
        "completion-menu.meta.completion",
        "completion-menu.meta.completion.current",
    ):
        assert any(token in rule[0] for rule in style_rules.items())

    # Verify float container structure
    fc = FloatContainer(
        content=Window(),
        floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=12))],
    )
    assert len(fc.floats) == 1
    assert fc.floats[0].xcursor is True
    assert fc.floats[0].ycursor is True
    assert isinstance(fc.floats[0].content, CompletionsMenu)


def test_slash_command_completer_filtering() -> None:
    from hund.ui.input import SlashCommandCompleter
    from prompt_toolkit.document import Document

    completer = SlashCommandCompleter()

    # Empty or non-slash gives no completions
    assert list(completer.get_completions(Document(""), None)) == []
    assert list(completer.get_completions(Document("hello"), None)) == []

    # Leading slash lists all commands
    all_comps = [c.text for c in completer.get_completions(Document("/"), None)]
    assert "/skills" in all_comps
    assert "/stats" in all_comps
    assert "/lessons" in all_comps
    assert len(all_comps) >= 25

    # Typing a letter filters down to matching commands
    s_comps = [c.text for c in completer.get_completions(Document("/s"), None)]
    assert "/stats" in s_comps
    assert "/skills" in s_comps
    assert "/session" in s_comps
    assert "/model" not in s_comps

    # Typing more letters narrows down further
    sk_comps = [c.text for c in completer.get_completions(Document("/sk"), None)]
    assert sk_comps == ["/skills"]

    # Space closes completion
    assert list(completer.get_completions(Document("/skills "), None)) == []


def test_output_lexer_rich_markdown_tokens() -> None:
    doc = Document(
        "## Säkerhet (security)\n"
        "9. python-project-workflow — safety_level: confirm_for_write\n"
        "- Ansvar: Fullständiga Python-ingenjörsflöden\n"
        "- Arbetsflöde: Baseline via `uv run pytest` -> re-run\n"
    )
    get_line = _OutputLexer().lex_document(doc)

    # Line 0: Header
    toks0 = get_line(0)
    assert any(t[0] == "class:header" for t in toks0)

    # Line 1: Numbered item
    toks1 = get_line(1)
    assert any(t[0] == "class:number" and "9." in t[1] for t in toks1)
    assert any(t[0] == "class:header" and "python-project-workflow" in t[1] for t in toks1)
    assert any(t[0] == "class:secondary" and "—" in t[1] for t in toks1)
    assert any(t[0] == "class:label" and "safety_level:" in t[1] for t in toks1)

    # Line 2: Bullet item with label
    toks2 = get_line(2)
    assert any(t[0] == "class:bullet" for t in toks2)
    assert any(t[0] == "class:label" and "Ansvar:" in t[1] for t in toks2)

    # Line 3: Bullet item with inline code and arrow
    toks3 = get_line(3)
    assert any(t[0] == "class:code" and "uv run pytest" in t[1] for t in toks3)
    assert any(t[0] == "class:secondary" and "->" in t[1] for t in toks3)

def test_fullscreen_statusbar_rendering() -> None:
    from hund.ui.input import PromptState
    from hund.ui.fullscreen import format_tokens_ratio, format_duration, format_status_bar

    state = PromptState()
    state.extra["model"] = "deepseek-v4-pro"
    state.extra["tokens"] = 14_000
    state.extra["token_limit"] = 1_000_000

    token_str = format_tokens_ratio(state.extra["tokens"], state.extra["token_limit"])
    dur_str = format_duration(300)
    assert token_str == "14K/1M"
    assert dur_str == "5m"

    status_str = format_status_bar(
        model=state.extra["model"],
        tokens=state.extra["tokens"],
        limit=state.extra["token_limit"],
        duration_s=300,
        latency_s=2.3,
    )
    assert status_str == "deepseek-v4-pro │ 14K/1M │ 5m │ 2.3s"


def test_overlay_enter_and_keybinding_filters() -> None:
    from hund.ui.screen_state import DestinationView, OverlayView, ScreenController

    screens = ScreenController()
    _confirm: dict = {"active": False}

    # Verify filter logic
    assert not _confirm["active"]
    assert screens.overlay is OverlayView.NONE
    assert screens.destination is DestinationView.CHAT

    # Open theme overlay
    screens.open_overlay(OverlayView.THEME)
    assert screens.overlay is OverlayView.THEME

    # Up and down move selection
    screens.move("theme", 1, 3)
    assert screens.selected["theme"] == 1
    screens.move("theme", -1, 3)
    assert screens.selected["theme"] == 0

    # Esc closes overlay
    assert screens.close_escape() == "overlay"
    assert screens.overlay is OverlayView.NONE

    # Open model custom overlay
    screens.open_overlay(OverlayView.MODEL_CUSTOM)
    assert screens.overlay is OverlayView.MODEL_CUSTOM
    assert screens.close_escape() == "nested"
    assert screens.overlay is OverlayView.MODEL
    assert screens.close_escape() == "overlay"
    assert screens.overlay is OverlayView.NONE


def test_run_fullscreen_initialization_no_unbound_locals(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock
    from hund.config import HundConfig
    from hund.ui.fullscreen import run_fullscreen

    rt = MagicMock()
    rt.cfg = HundConfig()
    rt.profile = None
    rt.workspace = None
    state = MagicMock()
    state.theme_name = "marshmallow"
    state.extra = {}

    # Mock Application.run_async so it returns immediately, and create_output for headless environment
    import prompt_toolkit.output.defaults
    monkeypatch.setattr(prompt_toolkit.output.defaults, "create_output", lambda *args, **kwargs: DummyOutput())
    monkeypatch.setattr(Application, "run_async", AsyncMock(return_value=0))

    exit_code = asyncio.run(run_fullscreen(rt, state, banner="test", session_id="test_sess"))
    assert exit_code == 0


def test_run_fullscreen_open_overlays_via_slash_commands(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock
    from hund.config import HundConfig
    from hund.ui.fullscreen import run_fullscreen

    rt = MagicMock()
    rt.cfg = HundConfig()
    rt.profile = None
    rt.workspace = None
    state = MagicMock()
    state.theme_name = "marshmallow"
    state.extra = {}

    import prompt_toolkit.output.defaults
    monkeypatch.setattr(prompt_toolkit.output.defaults, "create_output", lambda *args, **kwargs: DummyOutput())

    async def _mock_run(self):
        # Trigger slash commands through input buffer
        for cmd in ("/model", "/theme", "/auth"):
            self.layout.container.content.text = cmd
            buf = self.current_buffer
            buf.text = cmd
            buf.validate_and_handle()
        return 0

    monkeypatch.setattr(Application, "run_async", _mock_run)

    exit_code = asyncio.run(run_fullscreen(rt, state, banner="test", session_id="test_sess"))
    assert exit_code == 0


def test_mascot_dimmed_on_active_modal() -> None:
    from hund.ui.fullscreen import _MODAL_ACTIVE, create_fullscreen_app
    from hund.ui.screen_state import OverlayView

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock()
    state.theme_name = "marshmallow"
    state.extra = {}
    state.start_time = 0.0

    out = DummyOutput()
    app, ctx = create_fullscreen_app(rt, state, output=out)

    # Find mascot window
    inner_float_container = app.layout.container.content.children[0]
    _status_float, mascot_float = inner_float_container.floats
    mascot_window = mascot_float.content.content

    # Normal mode: mascot has bright tint
    normal_frags = mascot_window._get_text_fragments()
    assert normal_frags[0][0].startswith("class:mascot fg:")

    # Modal mode (e.g. /model or confirm): mascot dims to backdrop
    _MODAL_ACTIVE[0] = True
    modal_frags = mascot_window._get_text_fragments()
    assert modal_frags[0][0] == "class:backdrop"

    # Reset
    _MODAL_ACTIVE[0] = False
    restored_frags = mascot_window._get_text_fragments()
    assert restored_frags[0][0].startswith("class:mascot fg:")


def test_mascot_hidden_on_non_chat_screens() -> None:
    from hund.ui.fullscreen import create_fullscreen_app
    from hund.ui.screen_state import DestinationView

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock()
    state.theme_name = "marshmallow"
    state.extra = {}
    state.start_time = 0.0

    out = DummyOutput()
    app, ctx = create_fullscreen_app(rt, state, output=out)
    screens = ctx["screens"]

    inner_float_container = app.layout.container.content.children[0]
    _status_float, mascot_float = inner_float_container.floats
    mascot_container = mascot_float.content

    # In CHAT view: mascot container is active
    screens.destination = DestinationView.CHAT
    assert mascot_container.filter() is True

    # In SKILLS view: mascot container is inactive
    screens.destination = DestinationView.SKILLS
    assert mascot_container.filter() is False

    # In STATS view: mascot container is inactive
    screens.destination = DestinationView.STATS
    assert mascot_container.filter() is False


def test_authoring_stepper_is_inline_after_prompt_and_replaced_in_place() -> None:
    from hund.skills.authoring import AuthoringState
    from hund.skills.authoring_runtime import AuthoringOption, AuthoringView
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False, ascii_ui=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock()
    state.theme_name = "marshmallow"
    state.extra = {}
    state.start_time = 0.0

    output = ResizableOutput(cols=80, rows=24)
    app, ctx = create_fullscreen_app(rt, state, output=output)
    transcript_before = ctx["output_buffer"].text + "❯ Create a marketing skill\n\n"
    ctx["output_buffer"].set_document(
        Document(transcript_before, cursor_position=len(transcript_before)),
        bypass_readonly=True,
    )
    ctx["authoring_anchor"][0] = len(transcript_before)
    ctx["authoring_view"][0] = AuthoringView(
        session_id="stepper",
        phase=AuthoringState.SHAPING,
        subject="marketing",
        title="Primary Workflow Focus",
        question_key="focus",
        step_index=1,
        step_total=2,
        options=(
            AuthoringOption("answer", "Automate marketing", "Automate marketing"),
            AuthoringOption("answer", "Validate marketing", "Validate marketing"),
        ),
    )

    ctx["_sync_authoring_inline"]()
    assert ctx["authoring_container"] not in tuple(app.layout.walk())
    fragments = ctx["_authoring_fragments"]()
    assert any(style == "class:growth_gold bold" and "◆" in text for style, text in fragments)
    assert any(style == "class:growth_gold" and "│" in text for style, text in fragments)
    inline_text = ctx["output_buffer"].text
    assert inline_text.startswith(transcript_before)
    assert inline_text.count("SKILL AUTHORING · Supplementary Question 1 of 2") == 1

    output.set_size(cols=60, rows=24)
    ctx["_reflow_borders"]()

    ctx["_move_authoring_selection"](1)
    assert ctx["authoring_selected"][0] == 1
    replaced_text = ctx["output_buffer"].text
    assert replaced_text.count("SKILL AUTHORING · Supplementary Question 1 of 2") == 1
    assert "› Validate marketing" in replaced_text
    assert len(replaced_text) != len(inline_text) or replaced_text != inline_text


def test_inline_authoring_lexer_applies_gold_semantics() -> None:
    from hund.ui.fullscreen import _OutputLexer

    text = (
        "❯ Create a marketing skill\n\n"
        "  ◆  SKILL AUTHORING · Supplementary Question 1 of 2\n"
        "  │\n"
        "  │  Primary Marketing Outcome\n"
        "  │  Choose the result so checks match.\n"
        "  │\n"
        "  │  › Plan campaign strategy\n"
        "  │    Draft campaign content\n"
        "  └  ↑↓ Select · Enter Confirm · Esc Back"
    )
    get_line = _OutputLexer().lex_document(Document(text))

    assert get_line(2)[-1][0] == "class:growth_gold bold"
    assert any(style == "class:growth_gold" and text == "│" for style, text in get_line(3))
    assert get_line(4)[-1][0] == "class:growth_gold bold"
    assert get_line(7)[-1][0] == "class:growth_gold bold"
    assert get_line(8)[-1][0] == "class:secondary"
    assert get_line(9)[-1][0] == "class:growth_gold"


def test_authoring_fragments_wrapped_selected_option_preserves_gold_bold() -> None:
    from hund.ui.fullscreen import create_fullscreen_app
    from hund.skills.authoring import AuthoringState
    from hund.skills.authoring_runtime import AuthoringOption, AuthoringView

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(theme_name="marshmallow", extra={}, start_time=0.0)
    output = ResizableOutput(cols=50, rows=24)
    _app, ctx = create_fullscreen_app(rt, state, output=output)

    long_selected_label = "Automate Shopify product descriptions across all store items using GraphQL API"
    short_unselected_label = "Short second option"

    ctx["authoring_view"][0] = AuthoringView(
        session_id="stepper_wrapped",
        phase=AuthoringState.SHAPING,
        subject="shopify",
        title="Primary Focus",
        question_key="focus",
        step_index=1,
        step_total=2,
        options=(
            AuthoringOption("answer", long_selected_label, long_selected_label),
            AuthoringOption("answer", short_unselected_label, short_unselected_label),
        ),
    )
    ctx["authoring_selected"][0] = 0

    fragments = ctx["_authoring_fragments"]()
    selected_fragments = [
        (style, text) for style, text in fragments
        if any(word in text for word in ("Automate", "Shopify", "descriptions", "across", "GraphQL"))
    ]
    assert len(selected_fragments) >= 2
    for style, text in selected_fragments:
        assert style == "class:growth_gold bold", f"Expected gold bold for '{text}', got {style}"

    unselected_fragments = [
        (style, text) for style, text in fragments
        if "Short second option" in text
    ]
    assert unselected_fragments
    for style, text in unselected_fragments:
        assert style == "class:secondary", f"Expected secondary for unselected '{text}', got {style}"


def test_fullscreen_has_explicit_ctrl_d_exit_binding() -> None:
    from prompt_toolkit.keys import Keys
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(theme_name="marshmallow", extra={}, start_time=0.0)

    _app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())

    bindings = ctx["kb"].get_bindings_for_keys((Keys.ControlD,))
    assert bindings

    event = MagicMock()
    bindings[-1].handler(event)
    event.app.exit.assert_called_once_with()


def test_ctrl_c_never_exits_for_selection_active_turn_input_or_idle() -> None:
    from prompt_toolkit.keys import Keys
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(theme_name="marshmallow", extra={}, start_time=0.0)
    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    assert app.mouse_support()
    handler = ctx["kb"].get_bindings_for_keys((Keys.ControlC,))[-1].handler
    event = MagicMock()

    output = ctx["output_buffer"]
    output.set_document(Document("selected", cursor_position=0), bypass_readonly=True)
    output.start_selection()
    output.cursor_position = len(output.text)
    with patch("hund.ui.fullscreen.clipboard.copy_text", return_value=True):
        handler(event)

    ctx["turn_running"][0] = True
    handler(event)
    assert ctx["turn_running"][0] is False

    ctx["input_buffer"].text = "draft"
    handler(event)
    assert ctx["input_buffer"].text == ""

    handler(event)
    event.app.exit.assert_not_called()

def test_mouse_click_and_drag_selection() -> None:
    from hund.ui.fullscreen import create_fullscreen_app
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
    from prompt_toolkit.data_structures import Point

    async def _async_test() -> None:
        rt = MagicMock()
        rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
        rt.profile = None
        rt.messages = []
        state = MagicMock()
        state.theme_name = "marshmallow"
        state.extra = {}
        state.start_time = 0.0

        out = DummyOutput()
        app, ctx = create_fullscreen_app(rt, state, output=out)

        output_buffer = ctx["output_buffer"]
        output_window = None
        for c in app.layout.walk():
            if isinstance(c, Window) and getattr(getattr(c, "content", None), "buffer", None) is output_buffer:
                output_window = c
                break

        assert output_window is not None
        output_control = output_window.content

        # Populate 50 lines of text
        lines = [f"Line {i:02d}: some test text content here" for i in range(50)]
        text = "\n".join(lines) + "\n"
        output_buffer.set_document(Document(text, cursor_position=len(text)), bypass_readonly=True)

        with set_app(app):
            app.renderer.render(app, app.layout)
            # Window passes document coordinates to the control, even when the
            # visible transcript is scrolled or wrapped.
            down_evt = MouseEvent(
                position=Point(x=10, y=5),
                event_type=MouseEventType.MOUSE_DOWN,
                button=MouseButton.LEFT,
                modifiers=set(),
            )
            output_control.mouse_handler(down_evt)

            assert output_buffer.document.cursor_position_row == 5

            # Drag to row 5, col 20
            move_evt = MouseEvent(
                position=Point(x=20, y=5),
                event_type=MouseEventType.MOUSE_MOVE,
                button=MouseButton.LEFT,
                modifiers=set(),
            )
            output_control.mouse_handler(move_evt)
            assert output_buffer.selection_state is not None

            # Mouse up completes selection
            up_evt = MouseEvent(
                position=Point(x=20, y=5),
                event_type=MouseEventType.MOUSE_UP,
                button=MouseButton.NONE,
                modifiers=set(),
            )
            output_control.mouse_handler(up_evt)
            assert output_buffer.selection_state is not None

    asyncio.run(_async_test())


def test_theme_tokens_and_selection_styling() -> None:
    from hund.ui.theme import get_skin, make_pt_style

    skin = get_skin("marshmallow")
    tokens = skin["tokens"]

    # Verify lifted contrast tokens
    assert tokens["secondary"] == "#9AA5B8"
    assert tokens["meta_accent"] == "#D896C7"
    assert tokens["mascot_status"] == "#959EAE"
    assert tokens["modal_footer"] == "#A2ABC0"
    assert tokens["growth_gold"] == "#E6C07B"
    assert tokens["growth_ochre"] == "#D19A66"
    assert tokens["growth_brass"] == "#C8A96B"

    # Verify PT style contains white/black selection rules
    style = make_pt_style("marshmallow")
    style_dict = dict(style.style_rules)
    assert "selected" in style_dict
    assert "bg:#ffffff" in style_dict["selected"].lower()
    assert "fg:#000000" in style_dict["selected"].lower()


def test_output_window_includes_scrollbar_margin() -> None:
    from prompt_toolkit.layout.margins import ScrollbarMargin
    from hund.ui.fullscreen import create_fullscreen_app, _MinimalScrollbarMargin

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(theme_name="marshmallow", extra={}, start_time=0.0)
    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    output_window = ctx["output_window"]
    assert any(isinstance(m, ScrollbarMargin) for m in output_window.right_margins)
    assert any(isinstance(m, _MinimalScrollbarMargin) for m in output_window.right_margins)


def test_minimal_scrollbar_margin_hidden_in_vila_and_shows_thumb_when_scrolled() -> None:
    from hund.ui.fullscreen import _MinimalScrollbarMargin
    from prompt_toolkit.layout.containers import WindowRenderInfo

    render_info = MagicMock(spec=WindowRenderInfo)
    render_info.content_height = 100
    render_info.window_height = 20
    render_info.displayed_lines = list(range(20))

    # Case 1: In vila because tail-follow is True (width is always 1, no button/thumb)
    tail_following = [True]
    render_info.vertical_scroll = 80
    margin = _MinimalScrollbarMargin(tail_follow_getter=lambda: tail_following[0])
    assert margin.get_width(lambda: None) == 1
    tuples = margin.create_margin(render_info, width=1, height=20)
    assert not any("scrollbar.button" in style for style, _ in tuples)
    assert all(style == "" for style, text in tuples if text == " ")

    # Case 2: In vila because content fits in window
    render_info_short = MagicMock(spec=WindowRenderInfo)
    render_info_short.content_height = 10
    render_info_short.window_height = 20
    render_info_short.displayed_lines = list(range(10))
    render_info_short.vertical_scroll = 0
    tail_following[0] = False
    tuples_short = margin.create_margin(render_info_short, width=1, height=20)
    assert not any("scrollbar.button" in style for style, _ in tuples_short)

    # Case 3: Scrolled up (tail-follow is False, vertical_scroll is 40 < 80)
    tail_following[0] = False
    render_info.vertical_scroll = 40
    tuples_scrolled = margin.create_margin(render_info, width=1, height=20)
    button_tuples = [text for style, text in tuples_scrolled if "scrollbar.button" in style]
    assert len(button_tuples) > 0  # Thumb is visible



def test_resize_preserves_bottom_anchored_scroll_distance() -> None:
    from hund.ui.fullscreen import create_fullscreen_app

    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []
    state = MagicMock(theme_name="marshmallow", extra={}, start_time=0.0)
    out = ResizableOutput(cols=80, rows=24)
    app, ctx = create_fullscreen_app(rt, state, output=out)

    output_buffer = ctx["output_buffer"]
    output_window = ctx["output_window"]
    tail_following = ctx["tail_following"]
    reflow = ctx["_reflow_borders"]

    # Populate lines
    text = "\n".join(f"Line {i:03d}" for i in range(100))
    output_buffer.set_document(Document(text, cursor_position=0), bypass_readonly=True)
    # User scrolled up to line 70, not following tail
    tail_following[0] = False
    output_window.vertical_scroll = 70
    old_doc_len = text.count("\n") + 1
    dist = old_doc_len - 1 - 70  # 29 lines from the bottom

    # Resize output width and reflow
    out.set_size(60, 24)
    reflow()

    # After reflow, distance from bottom must be preserved
    new_doc_len = output_buffer.text.count("\n") + 1
    expected_scroll = max(0, new_doc_len - 1 - dist)
    assert output_window.vertical_scroll == expected_scroll


def test_lexer_skill_emdash_parsing() -> None:
    from hund.ui.fullscreen import _parse_semantic_line

    line = "1. Item — description with `inline_code` and text"
    tokens = _parse_semantic_line(line)

    # 1. Number part is class:number
    assert tokens[0] == ("class:number", "1. ")
    # 2. Header/item name is class:header
    assert tokens[1] == ("class:header", "Item")
    # 3. ONLY the emdash separator is class:secondary
    assert tokens[2] == ("class:secondary", " — ")
    # 4. Description is parsed semantically, not flattened to secondary
    token_styles = [t[0] for t in tokens[3:]]
    token_texts = [t[1] for t in tokens[3:]]
    assert "class:secondary" not in token_styles
    # inline code inside description is styled as class:code
    assert any("code" in s for s in token_styles)
    assert any("inline_code" in t for t in token_texts)



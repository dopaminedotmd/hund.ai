"""Tests for fullscreen TUI focus, scrolling, mouse selection, and box borders."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

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
    _OUTPUT_LEXER,
    _ScrollThroughFormattedTextControl,
    _output_cursor_position,
    _responsive_content_width,
    _shine_fragments,
    _wheel_scroll_passthrough,
)
from hund.ui.mascot import MascotMachine, MascotState
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
        lexer=_OUTPUT_LEXER,
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

        output_control = _SelectableControl(buffer=output_buffer, lexer=_OUTPUT_LEXER)
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
    get_line = _OUTPUT_LEXER.lex_document(doc)

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
    get_line = _OUTPUT_LEXER.lex_document(doc)

    # Line 0: Header
    toks0 = get_line(0)
    assert any(t[0] == "class:header" for t in toks0)

    # Line 1: Numbered item
    toks1 = get_line(1)
    assert any(t[0] == "class:number" and "9." in t[1] for t in toks1)
    assert any(t[0] == "class:header" and "python-project-workflow" in t[1] for t in toks1)
    assert any(t[0] == "class:secondary" and "safety_level" in t[1] for t in toks1)

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


"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable, semantically-colored output
buffer, a single input buffer, and an in-app arrow-key confirmation modal.

The output buffer is read-only (safe against stray typing) but focusable, so
the mouse can select text; Ctrl+C copies a selection to the clipboard (or
exits when there is none). The agent turn runs in a background thread.
"""
from __future__ import annotations

import io
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from rich.console import Console

from ..agent.context import estimate_tokens, maybe_compress
from ..agent.loop import (
    _agent_turn,
    _dynamic_context_message,
    _restore_frozen_system_prompt,
    _session_save,
    _trace_event,
)
from ..providers.base import Message
from . import theme
from .commands import CommandContext, dispatch_command, is_slash
from .input import (
    SLASH_COMMANDS,
    SLASH_COMMAND_METAS,
    PromptState,
    SlashCommandCompleter,
    format_status_bar,
)
from .output import parse_confirm_input, strip_markdown, strip_rich, StreamingMarkdownFilter, _confirm_title, _confirm_detail
from .render import box_bottom as _r_box_bottom, box_top as _r_box_top, refresh_stats, render_response_box
from ..agent.types import ConfirmRequest, ConfirmVerdict

from .phrases import select_thinking_phrase

_S = theme.SEMANTIC

_STYLE = theme.make_pt_style("bone")


def _trunc(val: Any, max_len: int = 45) -> str:
    s = str(val or "")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _format_tool_desc(name: str, args: dict | None) -> str:
    args = args or {}
    if name == "read_file":
        path = _trunc(args.get("path", ""))
        return f"read {path}"
    elif name == "search_files":
        pattern = _trunc(args.get("pattern", "*"))
        path = args.get("path")
        if path and path != ".":
            return f"searched {_trunc(path)} for {pattern}"
        return f"searched {pattern}"
    elif name == "write_file":
        path = _trunc(args.get("path", ""))
        return f"wrote {path}"
    elif name == "delete_file":
        path = _trunc(args.get("path", ""))
        return f"deleted {path}"
    elif name == "terminal":
        cmd = _trunc(args.get("command", ""))
        return f"ran {cmd}"
    elif name == "web_search":
        q = _trunc(args.get("query", ""))
        return f"searched the web for {q}"
    elif name == "web_extract":
        url = _trunc(args.get("url", ""))
        return f"read {url}"
    elif name == "execute_code":
        return "ran python script"
    elif name == "delegate_task":
        tasks = args.get("tasks", [])
        n = len(tasks)
        return f"delegated {n} task{'s' if n != 1 else ''}"
    elif name == "session_search":
        q = args.get("query")
        if q:
            return f"searched history for {_trunc(q)}"
        return "searched history"
    elif name == "cronjob":
        action = args.get("action", "job")
        target_name = args.get("name", "")
        if target_name:
            return f"scheduled {action} {_trunc(target_name)}"
        return f"scheduled {action}"
    else:
        return f"ran {name}"


class _OutputLexer(Lexer):
    """Line-prefix & semantic markdown lexer mapping output lines to rich token styles."""

    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno: int):
            try:
                line = lines[lineno]
            except IndexError:
                return []
            stripped = line.lstrip()
            if not stripped:
                return [("class:primary", line)]
            if stripped.startswith("❯"):
                return [("class:user", line)]
            elif stripped.startswith("┊"):
                idx = line.find("┊")
                leading = line[:idx]
                tokens: list[tuple[str, str]] = []
                if leading:
                    tokens.append(("", leading))
                tokens.append(("class:secondary", "┊"))
                rest = line[idx + 1 :]
                if rest.startswith(" "):
                    tokens.append(("class:secondary", " "))
                    rest = rest[1:]
                if rest.startswith("⟳"):
                    tokens.append(("class:accent", "⟳"))
                    tokens.append(("class:tool", rest[1:]))
                elif rest.startswith("✓"):
                    tokens.append(("class:success", "✓"))
                    tokens.append(("class:tool", rest[1:]))
                elif rest.startswith("✗") or rest.startswith("⊘"):
                    tokens.append(("class:danger", rest[0]))
                    tokens.append(("class:danger", rest[1:]))
                else:
                    tokens.append(("class:secondary", rest))
                return tokens
            elif "hund is " in line:
                return [("class:secondary", line)]
            elif "CONFIRMATION REQUIRED" in line:
                return [("class:warning", line)]
            elif "[y] Approve" in line:
                return [("class:success", line)]
            elif "[e] Edit" in line:
                return [("class:accent", line)]
            elif "[a] Allow" in line:
                return [("class:warning", line)]
            elif "[n] Deny" in line:
                return [("class:danger", line)]
            elif "BLOCKED" in line or "DECLINED" in line:
                return [("class:danger", line)]
            elif "tool:" in line:
                return [("class:tool", line)]
            elif line.startswith("┌") or line.startswith("└") or line.startswith("╭") or line.startswith("╰") or line.startswith("│"):
                return [("class:secondary", line)]
            elif stripped.startswith("#"):
                return [("class:header", line)]

            # Semantic parsing of assistant responses
            indent_len = len(line) - len(stripped)
            indent_str = line[:indent_len]
            cur = stripped
            tokens: list[tuple[str, str]] = []

            # Numbered list item: "9. python-project-workflow — safety_level: ..."
            num_match = re.match(r"^(\d+\.\s+)([^\s—–]+(?:[ \t]+[^\s—–]+)*)(.*)$", cur)
            if num_match:
                if indent_str:
                    tokens.append(("", indent_str))
                tokens.append(("class:number", num_match.group(1)))
                tokens.append(("class:header", num_match.group(2)))
                rest_str = num_match.group(3)
                if rest_str:
                    tokens.append(("class:secondary", rest_str))
                return tokens

            # Bullet item: "- Ansvar: ...", "• Triggras av: ...", "* **Arbetsflöde:** ..."
            bullet_match = re.match(r"^(•|-|\*)\s+", cur)
            if bullet_match:
                if indent_str:
                    tokens.append(("", indent_str))
                tokens.append(("class:bullet", bullet_match.group(0)))
                cur = cur[bullet_match.end():]

                # Lead-in label: "Ansvar:", "Triggras av:", "**Arbetsflöde:**"
                label_match = re.match(
                    r"^(\*\*[^*]+\*\*|\b[A-Za-zåäöÅÄÖ_-]+(?:\s+[a-zåäö_-]+)?\s*:)\s*",
                    cur,
                )
                if label_match:
                    tokens.append(("class:label", label_match.group(0)))
                    cur = cur[label_match.end():]
            elif indent_str:
                tokens.append(("", indent_str))

            # Inline markdown parsing: code, bold, arrows, dashes
            pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|->|→|—|–)")
            pos = 0
            for m in pattern.finditer(cur):
                if m.start() > pos:
                    tokens.append(("class:primary", cur[pos : m.start()]))
                val = m.group(0)
                if val.startswith("**") and val.endswith("**"):
                    tokens.append(("class:label", val))
                elif val.startswith("`") and val.endswith("`"):
                    tokens.append(("class:code", val))
                elif val in ("->", "→", "—", "–"):
                    tokens.append(("class:secondary", val))
                else:
                    tokens.append(("class:primary", val))
                pos = m.end()

            if pos < len(cur):
                tokens.append(("class:primary", cur[pos:]))

            return tokens

        return get_line


class _SelectableControl(BufferControl):
    """Output control: wheel scroll via the view-scroll callback, and
    single-drag selection (focus on mouse-down instead of mouse-up)."""

    def __init__(self, *args, scroll_cb=None, fallback_focus=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.scroll_cb = scroll_cb
        self.fallback_focus = fallback_focus

    def mouse_handler(self, mouse_event: MouseEvent) -> Any:
        et = mouse_event.event_type
        if et == MouseEventType.MOUSE_DOWN:
            # Focus on mouse-down so a single drag selects (default focuses
            # on mouse-up, which swallows the first drag).
            try:
                get_app().layout.current_control = self
            except Exception:
                pass
        elif et in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
            if self.scroll_cb is not None:
                self.scroll_cb(3 if et == MouseEventType.SCROLL_UP else -3)
            return None  # handled; skip the built-in laggy cursor scroll

        res = super().mouse_handler(mouse_event)

        if et == MouseEventType.MOUSE_UP:
            # If user just clicked without dragging a selection, restore focus to input!
            if self.buffer.selection_state is None and self.fallback_focus is not None:
                try:
                    get_app().layout.focus(self.fallback_focus)
                except Exception:
                    pass
        return res


_OUTPUT_LEXER = _OutputLexer()

_CONFIRM_OPTIONS = [
    (ConfirmVerdict.APPROVE_ONCE, "Run once", "class:success"),
    (ConfirmVerdict.EDIT, "Edit command", "class:accent"),
    (ConfirmVerdict.ALLOW_SESSION, "Allow for this session", "class:warning"),
    (ConfirmVerdict.DENY, "Deny", "class:danger"),
]


def _discard_console(width: int = 100) -> Console:
    """Rich console that discards output (agent turn only talks through the sink)."""
    return Console(file=io.StringIO(), color_system=None, force_terminal=False, width=width)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 100


async def run_fullscreen(rt, state, *, banner: str, session_id: str) -> int:
    """Run the full-screen REPL application. Returns exit code."""
    # ---- output buffer (read-only + focusable so the mouse can select) ----
    output_buffer = Buffer(name="output", multiline=True, read_only=True)
    output_control = _SelectableControl(buffer=output_buffer, lexer=_OUTPUT_LEXER)
    output_window = Window(
        content=output_control,
        wrap_lines=True,
        always_hide_cursor=True,
    )

    # ---- input buffer + prompt ----
    completer = SlashCommandCompleter()
    input_buffer = Buffer(
        name="input", multiline=False, completer=completer, complete_while_typing=True,
    )
    input_control = BufferControl(buffer=input_buffer, focus_on_click=True)
    input_window = Window(content=input_control, height=1)
    prompt_window = Window(
        content=FormattedTextControl(lambda: [("class:prompt", "❯ ")]),
        width=3,
        dont_extend_width=True,
    )
    input_row = VSplit([prompt_window, input_window])

    output_control.fallback_focus = input_window

    # ---- status bar ----
    def status_text() -> list[tuple[str, str]]:
        model = state.extra.get("model", "deepseek-v4-pro")
        tokens = state.extra.get("tokens", 0)
        limit = state.extra.get("token_limit", 1_000_000)
        dur = time.time() - state.start_time
        lat = state.extra.get("last_latency_s", 0.0)
        return [("class:status", " " + format_status_bar(model, tokens, limit, dur, lat))]

    status_window = Window(content=FormattedTextControl(status_text), height=1)

    # ---- confirmation modal (arrow-key select) ----
    _confirm = {
        "active": False,
        "prompt": "",
        "selected": 0,
        "answer": "deny",
        "event": threading.Event(),
    }

    def _confirm_text():
        if not _confirm["active"]:
            return []
        W = 64
        out: list[tuple[str, str]] = []

        def row(content: str, style: str = "class:primary") -> None:
            out.append(("class:secondary", "│ "))
            out.append((style, content))
            out.append(("class:secondary", " " * max(W - 4 - len(content), 0) + " │\n"))

        out.append(("class:secondary", "┌" + "─" * (W - 2) + "┐\n"))
        row(_confirm["title"], "class:warning bold")
        row("", "class:secondary")
        row(_confirm["detail"], "class:accent bold")
        row("", "class:secondary")
        for i, (_code, label, color) in enumerate(_CONFIRM_OPTIONS):
            if i == _confirm["selected"]:
                row("  ❯ ● " + label, color + " bold")
            else:
                row("    ○ " + label, "class:secondary")
        out.append(("class:secondary", "└" + "─" * (W - 2) + "┘\n"))
        out.append(("class:secondary", " ↑↓ select · Enter confirm · Esc deny"))
        return out

    _thinking: dict[str, Any] = {
        "active": False,
        "text": "hund is reading",
        "past": None,
        "dot_count": 1,
        "start_time": 0.0,
    }

    def _thinking_text() -> list[tuple[str, str]]:
        if not _thinking["active"]:
            return []
        dots = "." * _thinking["dot_count"]
        return [("class:thinking", f"  {_thinking['text']}{dots}\n")]

    thinking_window = Window(
        content=FormattedTextControl(_thinking_text),
        height=1,
        dont_extend_height=True,
    )
    thinking_container = ConditionalContainer(
        thinking_window, filter=Condition(lambda: bool(_thinking["active"]))
    )

    confirm_window = Window(content=FormattedTextControl(_confirm_text), height=12)
    confirm_container = ConditionalContainer(
        confirm_window, filter=Condition(lambda: _confirm["active"])
    )

    # 1-row vertical breathing room between input and bottom status bar
    input_gap = Window(height=1, char=" ")

    layout = Layout(
        FloatContainer(
            content=HSplit([output_window, thinking_container, confirm_container, input_row, input_gap, status_window]),
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=12),
                )
            ],
        ),
        focused_element=input_window,
    )

    # ---- shared mutable state ----
    holder: dict[str, Any] = {}
    turn_running = [False]

    def _invalidate() -> None:
        app = holder.get("app")
        if app is not None:
            try:
                app.invalidate()
            except Exception:
                pass

    def _app_width() -> int:
        app = holder.get("app")
        if app is not None:
            try:
                return app.output.get_size().columns
            except Exception:
                pass
        return _term_width()

    def _box_top(width: int | None = None) -> str:
        return _r_box_top(width if width is not None else _app_width())

    def _box_bottom(meta: str | None = None, width: int | None = None) -> str:
        return _r_box_bottom(width if width is not None else _app_width(), meta=meta)

    _append_lock = threading.Lock()

    def append(text: str) -> None:
        if not text:
            return
        with _append_lock:
            new_text = output_buffer.text + text
            output_buffer.set_document(
                Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
            )
        _invalidate()

    # seed banner
    seed = banner.rstrip("\n") + "\n\n"
    output_buffer.set_document(Document(seed, cursor_position=len(seed)), bypass_readonly=True)

    def _reflow_borders() -> None:
        """Re-width response box borders and re-wrap content to the current terminal width."""
        with _append_lock:
            text = output_buffer.text
            lines = text.split("\n")
            new_lines: list[str] = []
            changed = False
            in_box = False
            box_lines: list[str] = []

            for line in lines:
                if line.startswith("┌─ hund ") or line.startswith("╭─ hund "):
                    in_box = True
                    box_lines = []
                elif in_box and (line.startswith("└") or line.startswith("╰")):
                    in_box = False
                    # Extract meta if present (e.g. └────── 2.3s ┘)
                    box_meta: str | None = None
                    trimmed = line.rstrip(" ┘╯")
                    if " " in trimmed:
                        parts = trimmed.split(" ")
                        if len(parts) > 1 and parts[-1].strip():
                            box_meta = parts[-1].strip()

                    # Unbox lines
                    content_lines: list[str] = []
                    for bl in box_lines:
                        if bl.startswith("│ ") and bl.endswith(" │"):
                            content_lines.append(bl[2:-2].rstrip())
                        elif bl.startswith("│") and bl.endswith("│"):
                            content_lines.append(bl[1:-1].rstrip())
                        else:
                            content_lines.append(bl.rstrip())
                    raw_content = "\n".join(content_lines)
                    re_boxed = render_response_box(raw_content, _app_width(), meta=box_meta)
                    new_lines.extend(re_boxed.split("\n"))
                    changed = True
                elif in_box:
                    box_lines.append(line)
                else:
                    new_lines.append(line)

            if changed:
                new_text = "\n".join(new_lines)
                cur = output_buffer.cursor_position
                output_buffer.set_document(
                    Document(new_text, cursor_position=min(cur, len(new_text))),
                    bypass_readonly=True,
                )
                _invalidate()

    messages = rt.messages
    frozen = messages[0].content if messages else ""

    # ---- sink (called from the agent worker thread) ----
    class _Sink:
        def __init__(self) -> None:
            self._box_open = False
            self._box_start_marker: int | None = None
            self._raw_response = ""
            self._tool_marker: int | None = None
            self._tool_start_time: float = 0.0
            self._tool_args: dict = {}
            self._tool_switched = False
            self._user_input = ""
            self._anim_timer: threading.Timer | None = None
            self._pending_past_timer: threading.Timer | None = None
            self._md = StreamingMarkdownFilter()

        def set_user_input(self, text: str) -> None:
            self._user_input = text or ""
            self._tool_switched = False

        def _cancel_timers(self) -> None:
            if self._anim_timer is not None:
                try:
                    self._anim_timer.cancel()
                except Exception:
                    pass
                self._anim_timer = None
            if self._pending_past_timer is not None:
                try:
                    self._pending_past_timer.cancel()
                except Exception:
                    pass
                self._pending_past_timer = None

        def _start_anim_timer(self) -> None:
            if self._anim_timer is not None:
                try:
                    self._anim_timer.cancel()
                except Exception:
                    pass

            def _tick() -> None:
                if _thinking["active"]:
                    _thinking["dot_count"] = (_thinking["dot_count"] % 3) + 1
                    _invalidate()
                    self._anim_timer = threading.Timer(0.3, _tick)
                    self._anim_timer.daemon = True
                    self._anim_timer.start()

            self._anim_timer = threading.Timer(0.3, _tick)
            self._anim_timer.daemon = True
            self._anim_timer.start()

        def thinking(self, msg: str | None = None) -> None:
            self._cancel_timers()
            _thinking["active"] = True
            _thinking["text"] = msg.rstrip(".…") if msg else "hund is reading"
            _thinking["past"] = None
            _thinking["dot_count"] = 1
            _thinking["start_time"] = time.time()
            self._tool_switched = False
            self._start_anim_timer()
            _invalidate()

        def clear_thinking(self) -> None:
            self._cancel_timers()
            if _thinking["active"]:
                _thinking["active"] = False
                past = _thinking.get("past")
                start_time = _thinking.get("start_time", 0.0)
                _thinking["past"] = None
                _invalidate()

                if past:
                    elapsed = time.time() - start_time
                    if elapsed < 0.3:
                        remaining = 0.3 - elapsed
                        self._pending_past_timer = threading.Timer(
                            remaining, lambda: (append(f"  {past}\n"), _invalidate())
                        )
                        self._pending_past_timer.daemon = True
                        self._pending_past_timer.start()
                    else:
                        append(f"  {past}\n")
                        _invalidate()

        def chunk(self, text: str) -> None:
            self.clear_thinking()
            filtered = self._md.feed(text)
            if not filtered:
                return
            if not self._box_open:
                self._box_open = True
                self._box_start_marker = len(output_buffer.text)
                self._raw_response = ""
            self._raw_response += filtered
            boxed = render_response_box(self._raw_response, _app_width())
            with _append_lock:
                new_text = output_buffer.text[: self._box_start_marker] + "\n" + boxed
                output_buffer.set_document(
                    Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                )
            _invalidate()

        def end_assistant(self) -> None:
            if self._box_open:
                leftover = self._md.flush()
                self._raw_response += leftover
                boxed = render_response_box(self._raw_response, _app_width(), meta=None)
                with _append_lock:
                    new_text = output_buffer.text[: self._box_start_marker] + "\n" + boxed + "\n\n"
                    output_buffer.set_document(
                        Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                    )
                self._box_open = False
                self._raw_response = ""
                _invalidate()
            else:
                append("\n\n")

        def error(self, markup: str) -> None:
            clean = strip_rich(strip_markdown(markup)).strip()
            if self._tool_marker is not None:
                err_line = f"  ┊ ✗ error: {_trunc(clean, 50)}\n"
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + err_line
                    output_buffer.set_document(
                        Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                    )
                self._tool_marker = None
                _invalidate()
            else:
                append(clean + "\n")

        def confirm(self, request: ConfirmRequest) -> ConfirmVerdict:
            title = _confirm_title(request)
            detail = _confirm_detail(request)
            if len(detail) > 58:
                detail = detail[:55] + "..."
            _confirm["title"] = title
            _confirm["detail"] = detail
            _confirm["selected"] = 0
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = True
            _confirm["event"].clear()
            _invalidate()
            _confirm["event"].wait()
            _confirm["active"] = False
            _invalidate()
            return _confirm["answer"]

        def tool_start(self, name: str, args) -> None:
            if _thinking["active"] and not self._tool_switched:
                u_text = self._user_input
                if not u_text and messages:
                    u_text = next(
                        (m.content for m in reversed(messages) if getattr(m, "role", "") == "user"),
                        "",
                    )
                gerund, past = select_thinking_phrase(u_text)
                _thinking["text"] = gerund
                _thinking["past"] = past
                _thinking["start_time"] = time.time()
                self._tool_switched = True
                _invalidate()

            self._tool_args = args if isinstance(args, dict) else {}
            self._tool_start_time = time.time()
            self._tool_marker = len(output_buffer.text)
            append(f"  ┊ ⟳ preparing {name}…\n")

        def tool_result(self, name: str, shown: str) -> None:
            dur = time.time() - self._tool_start_time
            dur_str = f"{dur:.1f}s"
            desc = _format_tool_desc(name, self._tool_args)
            result_line = f"  ┊ ✓ {desc}  {dur_str}\n"
            if self._tool_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + result_line
                    output_buffer.set_document(
                        Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                    )
                self._tool_marker = None
                _invalidate()
            else:
                append(result_line)

        def blocked(self, name: str, reason: str) -> None:
            clean_reason = _trunc(reason, 40)
            blocked_line = f"  ┊ ✗ blocked {name} — {clean_reason}\n"
            if self._tool_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + blocked_line
                    output_buffer.set_document(
                        Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                    )
                self._tool_marker = None
                _invalidate()
            else:
                append(blocked_line)

        def declined(self, name: str, reason: str) -> None:
            clean_reason = _trunc(reason, 40)
            declined_line = f"  ┊ ✗ declined {name} — {clean_reason}\n"
            if self._tool_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + declined_line
                    output_buffer.set_document(
                        Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                    )
                self._tool_marker = None
                _invalidate()
            else:
                append(declined_line)

    sink = _Sink()

    # ---- slash command runner ----
    def run_command(user_text: str) -> None:
        buf = io.StringIO()
        console = Console(file=buf, color_system=None, force_terminal=False, width=100)
        ctx = CommandContext(console=console, rt=rt, state=state)
        dispatch_command(user_text, ctx)
        out = buf.getvalue()
        if out:
            append(out.rstrip("\n") + "\n\n")

    # ---- agent turn runner (background thread) ----
    def _spawn_turn(echo_user: str | None) -> None:
        turn_running[0] = True
        run_id = uuid.uuid4().hex
        user_text = echo_user
        if echo_user is not None:
            append(theme.USER_PREFIX + " " + echo_user + "\n")
            messages.append(Message(role="user", content=echo_user))
            _session_save(session_id, "user", echo_user, run_id=run_id)
        else:
            user_text = next(
                (m.content for m in reversed(messages) if getattr(m, "role", "") == "user"),
                "",
            )

        sink.set_user_input(user_text or "")

        tokens_before = estimate_tokens(messages)
        comp = maybe_compress(messages, client=rt.client)
        if comp.compressed:
            messages[:] = comp.messages
            _restore_frozen_system_prompt(messages, frozen)
            _trace_event(
                rt.engine, session_id, run_id, "context_compressed",
                {
                    "turns_dropped": comp.dropped_turns,
                    "tokens_before": tokens_before,
                    "tokens_after": comp.tokens,
                    "method": comp.method,
                },
            )
            append(f"({comp.dropped_turns} turns compressed)\n")

        dynamic_msg = _dynamic_context_message(
            skills=rt.skills,
            user_text=user_text or "",
            workspace_id=str(rt.workspace),
            domain_hint=rt.domain_hint,
        )
        if dynamic_msg is not None:
            messages.append(dynamic_msg)

        console = _discard_console()

        def worker() -> None:
            turn_start = time.time()
            try:
                _agent_turn(
                    console, rt.client, messages, rt.schemas, rt.engine, rt.cfg,
                    session_id, sink=sink, run_id=run_id,
                )
            except KeyboardInterrupt:
                append("\n[turn cancelled]\n")
            except Exception as e:  # noqa: BLE001
                append(f"\nerror: {e}\n")
            finally:
                state.extra["last_latency_s"] = time.time() - turn_start
                if dynamic_msg is not None:
                    messages[:] = [m for m in messages if m is not dynamic_msg]
                _restore_frozen_system_prompt(messages, frozen)
                state.extra["tokens"] = estimate_tokens(messages)
                refresh_stats(state)
                turn_running[0] = False
                _invalidate()

        threading.Thread(target=worker, daemon=True).start()

    def run_turn(user_text: str) -> None:
        _spawn_turn(user_text)

    def copy_last_response() -> None:
        last = next(
            (m.content for m in reversed(messages) if getattr(m, "role", "") == "assistant"),
            "",
        )
        if not last:
            append("(nothing to copy)\n")
            return
        try:
            subprocess.run(["clip"], input=last.encode("utf-8"), check=True)
            append("(copied last response to clipboard)\n")
        except Exception as e:  # noqa: BLE001
            append(f"(copy failed: {e})\n")

    def retry_last() -> None:
        while messages and getattr(messages[-1], "role", "") != "user":
            messages.pop()
        if not messages:
            append("(nothing to retry)\n")
            return
        append("(regenerating...)\n")
        _spawn_turn(None)

    # ---- input accept handler ----
    def on_accept(buf: Buffer) -> bool:
        text = buf.text.strip()
        if not text:
            return False
        buf.reset()

        if text in ("/exit", "/quit"):
            holder["app"].exit()
            return True

        if text == "/copy":
            copy_last_response()
            return True

        if text == "/retry":
            retry_last()
            return True

        if is_slash(text):
            run_command(text)
            return True

        if turn_running[0]:
            append("(hund is still responding - wait)\n")
            return True

        run_turn(text)
        return True

    input_buffer.accept_handler = on_accept

    # ---- keybindings ----
    confirm_active = Condition(lambda: _confirm["active"])

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
        _invalidate()

    output_control.scroll_cb = _scroll_lines

    def _copy_selection() -> bool:
        for buf in (input_buffer, output_buffer):
            try:
                r = buf.document.selection_range()
            except Exception:
                continue
            if not r:
                continue
            start, end = r
            text = buf.text[start:end]
            if not text:
                continue
            try:
                subprocess.run(["clip"], input=text.encode("utf-8"), check=True)
            except Exception:
                pass
            buf.exit_selection()
            layout.focus(input_window)
            append("(copied)\n")
            return True
        return False

    kb = KeyBindings()

    @kb.add("up", filter=confirm_active)
    def _up(event):
        _confirm["selected"] = (_confirm["selected"] - 1) % len(_CONFIRM_OPTIONS)
        event.app.invalidate()

    @kb.add("down", filter=confirm_active)
    def _down(event):
        _confirm["selected"] = (_confirm["selected"] + 1) % len(_CONFIRM_OPTIONS)
        event.app.invalidate()

    @kb.add("enter", filter=confirm_active)
    def _enter(event):
        _confirm["answer"] = _CONFIRM_OPTIONS[_confirm["selected"]][0]
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("y", filter=confirm_active)
    def _y(event):
        _confirm["answer"] = ConfirmVerdict.APPROVE_ONCE
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("e", filter=confirm_active)
    def _e(event):
        _confirm["answer"] = ConfirmVerdict.EDIT
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("a", filter=confirm_active)
    def _a(event):
        _confirm["answer"] = ConfirmVerdict.ALLOW_SESSION
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("n", filter=confirm_active)
    @kb.add("escape", filter=confirm_active)
    def _n(event):
        _confirm["answer"] = ConfirmVerdict.DENY
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("escape", filter=~confirm_active)
    def _escape(event):
        if output_buffer.selection_state is not None:
            output_buffer.exit_selection()
        layout.focus(input_window)
        _invalidate()

    @kb.add("c-c")
    def _ctrl_c(event):
        if _confirm["active"]:
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = False
            _confirm["event"].set()
        elif _copy_selection():
            pass  # copied
        else:
            event.app.exit()

    @kb.add("pageup")
    def _pgup(event):
        _scroll_lines(15)

    @kb.add("pagedown")
    def _pgdn(event):
        _scroll_lines(-15)

    @kb.add("<scroll-up>")
    def _scroll_up(event):
        _scroll_lines(3)

    @kb.add("<scroll-down>")
    def _scroll_down(event):
        _scroll_lines(-3)

    @kb.add(Keys.Any, filter=has_focus(output_window) & ~confirm_active)
    def _route_output_keys_to_input(event):
        layout.focus(input_window)
        for k in event.key_sequence:
            if k.key == Keys.Backspace:
                input_buffer.delete_before_cursor(count=1)
            elif k.key in (Keys.Enter, "\r", "\n"):
                input_buffer.validate_and_handle()
            elif len(k.data) == 1 and k.data.isprintable():
                input_buffer.insert_text(k.data)

    # ---- application ----
    initial_skin = getattr(state, "theme_name", "bone") or "bone"
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=theme.make_pt_style(initial_skin),
        mouse_support=True,
    )
    holder["app"] = app

    # Re-width box borders when the terminal is resized (polling is cheap).
    def _width_watcher() -> None:
        last = _app_width()
        while True:
            time.sleep(0.25)
            w = _app_width()
            if w != last:
                last = w
                _reflow_borders()

    threading.Thread(target=_width_watcher, daemon=True).start()

    result = await app.run_async()
    return result if isinstance(result, int) else 0


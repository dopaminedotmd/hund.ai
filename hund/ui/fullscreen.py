"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable, semantically-colored output
buffer, a single input buffer, and an in-app arrow-key confirmation modal.

The output buffer is read-only (safe against stray typing) but focusable, so
the mouse can select text; Ctrl+C copies a selection to the clipboard (or
exits when there is none). The agent turn runs in a background thread.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.lexers import Lexer
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
from .input import SLASH_COMMANDS, SLASH_COMMAND_METAS, PromptState, format_status_bar
from .output import parse_confirm_input, strip_markdown
from .render import refresh_stats

_S = theme.SEMANTIC

_STYLE = Style.from_dict(
    {
        "primary": _S["primary"],
        "secondary": _S["secondary"],
        "accent": _S["accent"],
        "success": _S["success"],
        "danger": _S["danger"],
        "warning": _S["warning"],
        "tool": _S["tool"],
        "user": _S["user"],
        "prompt": "bold " + _S["user"],
        "status": _S["secondary"],
    }
)


class _OutputLexer(Lexer):
    """Line-prefix lexer mapping output lines to semantic token styles."""

    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno: int):
            try:
                line = lines[lineno]
            except IndexError:
                return []
            stripped = line.lstrip()
            if stripped.startswith("❯"):
                style = "class:user"
            elif "hund is analyzing" in line:
                style = "class:secondary"
            elif "CONFIRMATION REQUIRED" in line:
                style = "class:warning"
            elif "[y] Approve" in line:
                style = "class:success"
            elif "[e] Edit" in line:
                style = "class:accent"
            elif "[a] Allow" in line:
                style = "class:warning"
            elif "[n] Deny" in line:
                style = "class:danger"
            elif "BLOCKED" in line or "DECLINED" in line:
                style = "class:danger"
            elif "tool:" in line:
                style = "class:tool"
            elif line.startswith("╭") or line.startswith("╰") or line.startswith("│"):
                style = "class:secondary"
            else:
                style = "class:primary"
            return [(style, line)]

        return get_line


_OUTPUT_LEXER = _OutputLexer()

_CONFIRM_OPTIONS = [
    ("approve", "Approve once", "class:success"),
    ("edit", "Edit command", "class:accent"),
    ("session", "Allow for session", "class:warning"),
    ("deny", "Deny (default)", "class:danger"),
]


def _discard_console(width: int = 100) -> Console:
    """Rich console that discards output (agent turn only talks through the sink)."""
    return Console(file=io.StringIO(), color_system=None, force_terminal=False, width=width)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 100


def _box_top() -> str:
    w = _term_width()
    return f"╭─ hund {'─' * max(w - 9, 2)}╮"


def _box_bottom() -> str:
    w = _term_width()
    return f"╰{'─' * max(w - 2, 2)}╯"


async def run_fullscreen(rt, state, *, banner: str, session_id: str) -> int:
    """Run the full-screen REPL application. Returns exit code."""
    # ---- output buffer (read-only + focusable so the mouse can select) ----
    output_buffer = Buffer(name="output", multiline=True, read_only=True)
    output_window = Window(
        content=BufferControl(buffer=output_buffer, lexer=_OUTPUT_LEXER),
        wrap_lines=True,
        always_hide_cursor=True,
    )

    # ---- input buffer + prompt ----
    completer = WordCompleter(
        SLASH_COMMANDS, ignore_case=True, meta_dict=SLASH_COMMAND_METAS, sentence=False,
    )
    input_buffer = Buffer(
        name="input", multiline=False, completer=completer, complete_while_typing=True,
    )
    input_window = Window(content=BufferControl(buffer=input_buffer), height=1)
    prompt_window = Window(
        content=FormattedTextControl(lambda: [("class:prompt", "❯ ")]),
        width=3,
        dont_extend_width=True,
    )
    input_row = VSplit([prompt_window, input_window])

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

        out.append(("class:secondary", "╭" + "─" * (W - 2) + "╮\n"))
        row("CONFIRMATION REQUIRED", "class:warning bold")
        row("", "class:secondary")
        row(_confirm["prompt"], "class:primary")
        row("", "class:secondary")
        for i, (_code, label, color) in enumerate(_CONFIRM_OPTIONS):
            if i == _confirm["selected"]:
                row("  ❯ ● " + label, color + " bold")
            else:
                row("    ○ " + label, "class:secondary")
        out.append(("class:secondary", "╰" + "─" * (W - 2) + "╯\n"))
        out.append(("class:secondary", " ↑↓ select · Enter confirm · Esc deny"))
        return out

    confirm_window = Window(content=FormattedTextControl(_confirm_text), height=12)
    confirm_container = ConditionalContainer(
        confirm_window, filter=Condition(lambda: _confirm["active"])
    )

    layout = Layout(HSplit([output_window, confirm_container, input_row, status_window]))
    layout.focus(input_window)

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
        """Re-width response box borders to the current terminal width."""
        with _append_lock:
            text = output_buffer.text
            lines = text.split("\n")
            new_lines: list[str] = []
            changed = False
            in_box = False
            for line in lines:
                if line.startswith("╭─ hund "):
                    nl = _box_top()
                    in_box = True
                elif in_box and line.startswith("╰"):
                    nl = _box_bottom()
                    in_box = False
                else:
                    nl = line
                if nl != line:
                    changed = True
                new_lines.append(nl)
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
            self._think_marker: int | None = None

        def thinking(self, msg: str | None = None) -> None:
            self._think_marker = len(output_buffer.text)
            append("  " + (msg or "hund is analyzing...") + "\n")

        def clear_thinking(self) -> None:
            if self._think_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._think_marker]
                    output_buffer.set_document(
                        Document(new_text, cursor_position=len(new_text)), bypass_readonly=True
                    )
                self._think_marker = None
                _invalidate()

        def chunk(self, text: str) -> None:
            if not self._box_open:
                self._box_open = True
                append(_box_top() + "\n")
            append(text)

        def end_assistant(self) -> None:
            if self._box_open:
                append("\n" + _box_bottom() + "\n\n")
                self._box_open = False
            else:
                append("\n\n")

        def error(self, markup: str) -> None:
            append(strip_markdown(markup) + "\n")

        def confirm(self, prompt: str) -> bool:
            clean = strip_markdown(prompt).strip().replace("\n", " ")
            if len(clean) > 58:
                clean = clean[:55] + "..."
            _confirm["prompt"] = clean
            _confirm["selected"] = 0
            _confirm["answer"] = "deny"
            _confirm["active"] = True
            _confirm["event"].clear()
            _invalidate()
            _confirm["event"].wait()
            _confirm["active"] = False
            _invalidate()
            return _confirm["answer"] in {"approve", "session"}

        def tool_start(self, name: str, args) -> None:
            append(f"  tool: {name}\n")

        def tool_result(self, name: str, shown: str) -> None:
            append(f"    -> {shown}\n\n")

        def blocked(self, name: str, reason: str) -> None:
            append(f"BLOCKED: {name} - {reason}\n")

        def declined(self, name: str, reason: str) -> None:
            append(f"DECLINED: {name} - {reason}\n")

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
        doc = output_buffer.document
        if count > 0:
            output_buffer.cursor_position += doc.get_cursor_up_position(count)
        else:
            output_buffer.cursor_position += doc.get_cursor_down_position(-count)

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
                return False
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
        _confirm["answer"] = "approve"
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("e", filter=confirm_active)
    def _e(event):
        _confirm["answer"] = "edit"
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("a", filter=confirm_active)
    def _a(event):
        _confirm["answer"] = "session"
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("n", filter=confirm_active)
    @kb.add("escape", filter=confirm_active)
    def _n(event):
        _confirm["answer"] = "deny"
        _confirm["active"] = False
        _confirm["event"].set()

    @kb.add("c-c")
    def _ctrl_c(event):
        if _confirm["active"]:
            _confirm["answer"] = "deny"
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

    # ---- application ----
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=_STYLE,
        mouse_support=True,
    )
    holder["app"] = app

    # Re-width box borders when the terminal is resized (polling is cheap).
    def _width_watcher() -> None:
        last = _term_width()
        while True:
            time.sleep(0.5)
            w = _term_width()
            if w != last:
                last = w
                _reflow_borders()

    threading.Thread(target=_width_watcher, daemon=True).start()

    result = await app.run_async()
    return result if isinstance(result, int) else 0

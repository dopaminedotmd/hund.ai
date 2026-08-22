"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable, semantically-colored output
buffer and a single input buffer. The agent turn runs in a background thread;
streamed tokens are appended to the output buffer and the app repaints on each
invalidate.

The output buffer is plain text; a SimpleLexer maps line prefixes to semantic
token styles (see theme.SEMANTIC). Scrollback is provided by the buffer's own
cursor, moved with Document.cursor_up/down and the mouse wheel.
"""
from __future__ import annotations

import io
import shutil
import threading
import time
import uuid
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
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
            elif line.startswith("╭─") or line.startswith("╰─"):
                style = "class:secondary"
            elif "CONFIRMATION REQUIRED" in line:
                style = "class:warning"
            elif "BLOCKED" in line or "DECLINED" in line:
                style = "class:danger"
            elif "tool:" in line:
                style = "class:tool"
            else:
                style = "class:primary"
            return [(style, line)]

        return get_line


_OUTPUT_LEXER = _OutputLexer()


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
    # ---- output buffer (scrollable, colored via lexer) ----
    output_buffer = Buffer(name="output", multiline=True)
    output_window = Window(
        content=BufferControl(buffer=output_buffer, focusable=False, lexer=_OUTPUT_LEXER),
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

    layout = Layout(HSplit([output_window, input_row, status_window]))

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

    def append(text: str) -> None:
        if not text:
            return
        output_buffer.cursor_position = len(output_buffer.text)
        output_buffer.insert_text(text, fire_event=False)
        _invalidate()

    # seed banner
    output_buffer.text = banner.rstrip("\n") + "\n\n"
    output_buffer.cursor_position = len(output_buffer.text)

    messages = rt.messages
    frozen = messages[0].content if messages else ""

    # ---- sink (called from the agent worker thread) ----
    class _Sink:
        def __init__(self) -> None:
            self.confirm_pending = False
            self.confirm_answer = "deny"
            self.confirm_event = threading.Event()
            self._box_open = False

        def thinking(self, msg: str | None = None) -> None:
            pass  # ponytail: response streams directly, no thinking line

        def clear_thinking(self) -> None:
            pass

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
            append("\nCONFIRMATION REQUIRED\n")
            append(strip_markdown(prompt) + "\n")
            append("  [y] approve once  [e] edit  [a] allow session  [n] deny\n\n")
            self.confirm_answer = "deny"
            self.confirm_pending = True
            self.confirm_event.clear()
            self.confirm_event.wait()  # answered by the main input handler
            self.confirm_pending = False
            return self.confirm_answer in {"approve", "session"}

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
    def run_turn(user_text: str) -> None:
        turn_running[0] = True
        append(theme.USER_PREFIX + " " + user_text + "\n")
        messages.append(Message(role="user", content=user_text))
        run_id = uuid.uuid4().hex
        _session_save(session_id, "user", user_text, run_id=run_id)

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
            user_text=user_text,
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

    # ---- input accept handler ----
    def on_accept(buf: Buffer) -> bool:
        text = buf.text.strip()
        if not text:
            return False
        buf.reset()

        if sink.confirm_pending:
            sink.confirm_answer = parse_confirm_input(text)
            sink.confirm_event.set()
            return True

        if text in ("/exit", "/quit"):
            holder["app"].exit()
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
    def _scroll_lines(count: int) -> None:
        doc = Document(output_buffer.text, output_buffer.cursor_position)
        new_doc = doc.cursor_up(count) if count > 0 else doc.cursor_down(-count)
        output_buffer.cursor_position = new_doc.cursor_position

    kb = KeyBindings()

    @kb.add("c-c")
    def _ctrl_c(event):
        event.app.exit()

    @kb.add("pageup")
    def _pgup(event):
        _scroll_lines(15)

    @kb.add("pagedown")
    def _pgdn(event):
        _scroll_lines(-15)

    @kb.add("scroll-up")
    def _scroll_up(event):
        _scroll_lines(3)

    @kb.add("scroll-down")
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

    result = await app.run_async()
    return result if isinstance(result, int) else 0

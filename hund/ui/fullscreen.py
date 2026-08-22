"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable output buffer and a single input
buffer. The agent turn runs in a background thread; streamed tokens are
appended to the output buffer and the app repaints on each invalidate.

Scrollback is provided by the output buffer's own cursor + the Window that
renders it. The input buffer is the only focusable buffer, so typing always
goes to the prompt.
"""
from __future__ import annotations

import io
import threading
import time
import uuid
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
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

_STYLE = Style.from_dict(
    {
        "status": theme.HUND_DIM,
        "input": "bold " + theme.HUND_GREEN,
        "output": theme.HUND_FG,
        "prompt": "bold " + theme.HUND_GREEN,
    }
)


def _discard_console(width: int = 100) -> Console:
    """Rich console that discards output (agent turn only talks through the sink)."""
    return Console(file=io.StringIO(), color_system=None, force_terminal=False, width=width)


async def run_fullscreen(rt, state, *, banner: str, session_id: str) -> int:
    """Run the full-screen REPL application. Returns exit code."""
    # ---- output buffer (scrollable log) ----
    output_buffer = Buffer(name="output", multiline=True)
    output_window = Window(
        content=BufferControl(buffer=output_buffer, focusable=False),
        wrap_lines=True,
        always_hide_cursor=True,
        style="class:output",
    )

    # ---- input buffer ----
    completer = WordCompleter(
        SLASH_COMMANDS, ignore_case=True, meta_dict=SLASH_COMMAND_METAS, sentence=False,
    )
    input_buffer = Buffer(
        name="input", multiline=False, completer=completer, complete_while_typing=True,
    )
    input_window = Window(content=BufferControl(buffer=input_buffer), height=1)

    # ---- status bar ----
    def status_text() -> list[tuple[str, str]]:
        model = state.extra.get("model", "deepseek-v4-pro")
        tokens = state.extra.get("tokens", 0)
        limit = state.extra.get("token_limit", 1_000_000)
        dur = time.time() - state.start_time
        lat = state.extra.get("last_latency_s", 0.0)
        return [("class:status", " " + format_status_bar(model, tokens, limit, dur, lat))]

    status_window = Window(content=FormattedTextControl(status_text), height=1)

    layout = Layout(HSplit([output_window, input_window, status_window]))

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
        # cursor to end, then insert (BufferControl renders around the cursor)
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

        def thinking(self, msg: str | None = None) -> None:
            pass  # ponytail: response streams directly, no thinking line

        def clear_thinking(self) -> None:
            pass

        def chunk(self, text: str) -> None:
            append(text)

        def end_assistant(self) -> None:
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
    kb = KeyBindings()

    @kb.add("c-c")
    def _ctrl_c(event):
        event.app.exit()

    @kb.add("pageup")
    def _pgup(event):
        output_buffer.cursor_position = max(0, output_buffer.cursor_position - 20)

    @kb.add("pagedown")
    def _pgdn(event):
        output_buffer.cursor_position = min(
            len(output_buffer.text), output_buffer.cursor_position + 20
        )

    @kb.add("c-up")
    def _c_up(event):
        output_buffer.cursor_position = max(0, output_buffer.cursor_position - 1)

    @kb.add("c-down")
    def _c_down(event):
        output_buffer.cursor_position = min(
            len(output_buffer.text), output_buffer.cursor_position + 1
        )

    # ---- application ----
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=_STYLE,
    )
    holder["app"] = app

    result = await app.run_async()
    return result if isinstance(result, int) else 0

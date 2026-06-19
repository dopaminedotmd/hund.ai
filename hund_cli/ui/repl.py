"""Rich Live-baserad REPL med status, konversation och base stats."""
from __future__ import annotations

import threading
from pathlib import Path

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from ..base_stats import compute
from ..providers.base import Message
from ..tools import registry
from .mascot import render as render_mascot
from .notifications import tool_line
from .render import render_baserad, render_status


class LiveSink:
    """Duck-typed sink för agent-loopens streaming- och tool-hooks."""

    def __init__(self, live: Live, layout: Layout, conv_lines: list[Text]):
        self.live = live
        self.layout = layout
        self.conv_lines = conv_lines
        self._assistant_index: int | None = None
        self._thinking_index: int | None = None
        self._tool_index: int | None = None
        self._thinking_stop = threading.Event()
        self._thinking_thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def _refresh(self) -> None:
        content = Group(*self.conv_lines) if self.conv_lines else Text("")
        self.layout["conversation"].update(Panel(content, padding=(0, 1), border_style="dim"))
        self.live.refresh()

    def add_line(self, line: Text | str, *, markup: bool = False) -> int:
        if isinstance(line, Text):
            text = line.copy()
        elif markup:
            text = Text.from_markup(line)
        else:
            text = Text(line)
        with self._lock:
            self.conv_lines.append(text)
            self._refresh()
            return len(self.conv_lines) - 1

    def thinking(self, msg: str = "hund undersöker") -> None:
        self.clear_thinking()
        self._thinking_stop.clear()
        self._thinking_index = self.add_line(Text(f"{msg}.", style="dim"))

        def animate() -> None:
            frame = 0
            while not self._thinking_stop.wait(0.2):
                with self._lock:
                    if self._thinking_index is None:
                        return
                    dots = (".", "..", "...")[frame % 3]
                    self.conv_lines[self._thinking_index] = Text(f"{msg}{dots}", style="dim")
                    self._refresh()
                    frame += 1

        self._thinking_thread = threading.Thread(target=animate, daemon=True)
        self._thinking_thread.start()

    def clear_thinking(self) -> None:
        self._thinking_stop.set()
        thread = self._thinking_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=0.3)
        self._thinking_thread = None
        with self._lock:
            if self._thinking_index is not None:
                if self._thinking_index < len(self.conv_lines):
                    self.conv_lines.pop(self._thinking_index)
                self._thinking_index = None
                self._refresh()

    def chunk(self, text: str) -> None:
        with self._lock:
            if self._assistant_index is None:
                self.conv_lines.append(Text())
                self._assistant_index = len(self.conv_lines) - 1
            self.conv_lines[self._assistant_index].append(text)
            self._refresh()

    def end_assistant(self) -> None:
        self._assistant_index = None
        self.add_line("")

    def error(self, msg: str) -> None:
        self.clear_thinking()
        self.add_line(msg, markup=True)

    def tool_start(self, name: str, args: dict) -> None:
        target = _tool_target(args)
        self._tool_index = self.add_line(tool_line(name, target), markup=True)

    def tool_result(self, name: str, shown: str) -> None:
        _ = name, shown
        self._remove_tool_line()

    def blocked(self, name: str, reason: str) -> None:
        self._remove_tool_line()
        self.add_line(f"[red]BLOCKERAD[/red] {name} — {reason}", markup=True)

    def declined(self, name: str, reason: str) -> None:
        self._remove_tool_line()
        self.add_line(f"[dim]{name} nekad — {reason}[/dim]", markup=True)

    def confirm(self, prompt: str) -> bool:
        answer = self.live.console.input(prompt + " ").strip().lower()
        return answer in {"j", "ja", "y", "yes"}

    def _remove_tool_line(self) -> None:
        with self._lock:
            if self._tool_index is not None and self._tool_index < len(self.conv_lines):
                self.conv_lines.pop(self._tool_index)
            self._tool_index = None
            self._refresh()

    # Namn från fasens publika UI-skiss.
    on_chunk = chunk
    on_thinking = thinking
    on_error = error

    def on_tool(self, name: str, args: dict) -> None:
        self.tool_start(name, args)


def _tool_target(args: dict) -> str:
    for key in ("path", "pattern", "command", "query", "target"):
        value = args.get(key)
        if value:
            return Path(str(value)).name if key == "path" else str(value)
    return ""


def _update_fixed_zones(
    layout: Layout,
    *,
    session_id: str,
    msg_count: int,
    domain: str,
) -> None:
    status = render_status(render_mascot(), session_id, msg_count, domain, locked=True)
    layout["status"].update(Panel(status, height=1, padding=0, border_style="dim"))
    layout["baserad"].update(Panel(render_baserad(compute()), height=1, padding=0, border_style="dim"))


def run_repl_ui() -> int:
    """Starta Hunds Rich Live-REPL."""
    from ..agent import sessions as S
    from ..agent.context import maybe_compress
    from ..agent.loop import (
        _agent_turn,
        _init_runtime,
        _session_save,
        _stats_text,
        assemble_system_prompt,
    )

    rt = _init_runtime()
    if not rt.key:
        from rich.console import Console

        Console().print(
            f"[red]API-nyckel saknas.[/red] Sätt med `hund setup` eller "
            f"`setx {rt.cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    layout = Layout()
    layout.split(
        Layout(name="status", size=1),
        Layout(name="conversation"),
        Layout(name="baserad", size=1),
    )
    conv_lines: list[Text] = []
    layout["conversation"].update(Panel(Text(""), padding=(0, 1), border_style="dim"))
    _update_fixed_zones(
        layout,
        session_id=rt.session_id,
        msg_count=0,
        domain=rt.domain_hint,
    )

    with Live(layout, screen=True, auto_refresh=False) as live:
        sink = LiveSink(live, layout, conv_lines)
        live.refresh()
        while True:
            try:
                user = live.console.input("").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user:
                continue
            if user in {"/exit", "/quit"}:
                break
            if user == "/stats":
                sink.add_line(_stats_text(), markup=True)
                continue
            if user == "/profile":
                sink.add_line(rt.profile.summary())
                continue
            if user == "/tools":
                sink.add_line(
                    ", ".join(f"{tool.name}({tool.base_risk})" for tool in registry.all_tools())
                )
                continue

            line = Text("du> ", style="bold green")
            line.append(user)
            sink.add_line(line)
            rt.messages.append(Message(role="user", content=user))
            _session_save(rt.session_id, "user", user)
            rt.messages[0] = Message(
                role="system",
                content=assemble_system_prompt(
                    rt.persona,
                    rt.profile,
                    knowledge=rt.knowledge,
                    policy_rules=rt.policy_rules,
                    skills=rt.skills,
                    user_text=user,
                    memory_lines=rt.memory_lines,
                ),
            )
            compressed = maybe_compress(rt.messages)
            if compressed.compressed:
                rt.messages[:] = compressed.messages
                sink.add_line(
                    f"[dim]({compressed.dropped_turns} turns komprimerade)[/dim]",
                    markup=True,
                )

            _agent_turn(
                live.console,
                rt.client,
                rt.messages,
                rt.schemas,
                rt.engine,
                rt.cfg,
                rt.session_id,
                sink=sink,
            )
            info = S.info(rt.session_id)
            _update_fixed_zones(
                layout,
                session_id=rt.session_id,
                msg_count=info["message_count"] if info else len(rt.messages) - 1,
                domain=rt.domain_hint,
            )
            live.refresh()

        sink.clear_thinking()
    return 0

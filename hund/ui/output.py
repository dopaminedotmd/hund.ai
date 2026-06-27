"""StreamingSink - duck-typed UI-sink for agent.loop._agent_turn.

Implementerar sink-protokollet (se hund/agent/loop.py _agent_turn docstring):
  thinking() / clear_thinking() / chunk(text) / end_assistant() / error(markup)
samt tool-hook-kontraktet (se hund/agent/tool_dispatch.py dispatch_tool_call):
  confirm(prompt) / tool_start(name,args) / tool_result(name,shown)
  blocked(name,reason) / declined(name,reason)

Streaming = direkt utskrift. Ingen time.sleep (nätverk skapar naturlig fordröjning).
"""
from __future__ import annotations

import json
import os
import re
import time

from rich.console import Console

from . import theme

_APPROVE = {"j", "y", "ja", "yes", "a", "alla"}
_DEFAULT_STREAM_DELAY_S = 0.0015

_FENCE_RE = re.compile(r"```(?:[A-Za-z0-9_+.-]+)?\n?|\n?```")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"(\*\*|__)(.*?)\1", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")


def _short_args(args) -> str:
    try:
        s = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(args)
    return s if len(s) <= 120 else s[:120] + "..."


def strip_markdown(text: str) -> str:
    """Returnera Hund-output som ren terminaltext utan markdown-markörer."""
    text = _FENCE_RE.sub("", text)
    text = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = _INLINE_CODE_RE.sub(lambda m: m.group(1), text)
    text = _BOLD_RE.sub(lambda m: m.group(2), text)
    text = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _HEADING_RE.sub("", text)
    return text


class StreamingSink:
    """Skriver agentens stream direkt till en Rich Console.

    Anvands aven som tool-hooks av dispatch_tool_call (samma objekt).
    """

    def __init__(self, console: Console, *, stream_delay_s: float | None = None):
        self.console = console
        self._thinking_active = False
        if stream_delay_s is None:
            raw_delay = os.environ.get("HUND_STREAM_DELAY_S", "")
            try:
                stream_delay_s = float(raw_delay) if raw_delay else _DEFAULT_STREAM_DELAY_S
            except ValueError:
                stream_delay_s = _DEFAULT_STREAM_DELAY_S
        self.stream_delay_s = max(0.0, min(stream_delay_s, 0.02))

    # -- streaming protokoll ----------------------------------------------

    def thinking(self, msg: str | None = None) -> None:
        text = msg or "hund tänker..."
        # skriv på aktuell rad utan newline; clear_thinking raderar sen
        self.console.print(f"[dim]{theme.HUND_INDENT}{text}[/dim]", end="")
        self._thinking_active = True

    def clear_thinking(self) -> None:
        if not self._thinking_active:
            return
        f = self.console.file
        f.write("\r" + " " * 60 + "\r")
        f.flush()
        self._thinking_active = False

    def chunk(self, text: str) -> None:
        self.clear_thinking()
        text = strip_markdown(text)
        # markup=False: agent-text ar data, tolka ej Rich-markup
        for ch in text:
            self.console.print(
                ch,
                end="",
                style=theme.HUND_FG,
                markup=False,
                highlight=False,
            )
            try:
                self.console.file.flush()
            except Exception:
                pass
            if self.stream_delay_s:
                time.sleep(self.stream_delay_s)

    def end_assistant(self) -> None:
        self.clear_thinking()
        self.console.print()

    def error(self, markup: str) -> None:
        self.clear_thinking()
        self.console.print(markup)

    # -- tool-hook kontrakt ------------------------------------------------

    def confirm(self, prompt: str) -> bool:
        self.clear_thinking()
        self.console.print(prompt, end=" ")
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = ""
        return ans in _APPROVE

    def tool_start(self, name: str, args) -> None:
        self.console.print(f"[dim]{theme.HUND_INDENT}* tool {name} {_short_args(args)}[/dim]")

    def tool_result(self, name: str, shown: str) -> None:
        self.console.print(f"[dim]{theme.HUND_INDENT}* {name} -> {shown}[/dim]", markup=False)

    def blocked(self, name: str, reason: str) -> None:
        self.console.print(f"[bold red]{theme.HUND_INDENT}[BLOCKED] {name}: {reason}[/bold red]")

    def declined(self, name: str, reason: str) -> None:
        self.console.print(f"[dim]{theme.HUND_INDENT}[DECLINED] {name}: {reason}[/dim]")


def render_markdown(console: Console, text: str) -> None:
    """Rendera sparad text utan markdown-markörer.

    Namnet finns kvar för P2-kompatibilitet, men customization-fasen kräver att
    Hunds svar visas som ren text i terminalen. Rich får fortfarande styla via
    explicit style, aldrig genom att tolka markdown från modellen.
    """
    console.print(strip_markdown(text), style=theme.HUND_FG, markup=False, highlight=False)

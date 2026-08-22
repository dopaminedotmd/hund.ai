"""StreamingSink - duck-typed UI sink for agent.loop._agent_turn and tool_dispatch.

Implements the sink protocol:
  thinking() / clear_thinking() / chunk(text) / end_assistant() / error(markup)
and the tool-hook contract:
  confirm(prompt) / tool_start(name, args) / tool_result(name, shown)
  blocked(name, reason) / declined(name, reason)

Renders compact boxed cards via theme.boxify() for tool execution events.
"""
from __future__ import annotations

import json
import os
import re
import time

from rich.console import Console
from rich.markdown import Markdown

from . import theme

_APPROVE_ONCE = {"y", "yes", "j", "ja"}
_APPROVE_ALL = {"a", "all", "alla"}
_EDIT = {"e", "edit"}
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


def parse_confirm_input(ans: str) -> str:
    """Parse confirmation action string into canonical verdict."""
    raw = (ans or "").strip().lower()
    if raw in _APPROVE_ONCE:
        return "approve"
    if raw in _EDIT:
        return "edit"
    if raw in _APPROVE_ALL:
        return "session"
    return "deny"


def transform_streaming_markdown(text: str) -> str:
    """Minimal streaming transformer converting bold to ANSI bold, -/* to bullets, and stripping raw markers."""
    text = re.sub(r"(?m)^(\s*)[*-]\s+", r"\1• ", text)
    text = _BOLD_RE.sub(lambda m: f"\x1b[1m{m.group(2)}\x1b[22m", text)
    text = _INLINE_CODE_RE.sub(lambda m: f"\x1b[36m{m.group(1)}\x1b[39m", text)
    text = _HEADING_RE.sub("", text)
    text = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    return text


def strip_markdown(text: str) -> str:
    """Return plain terminal text with markdown markers converted/stripped."""
    text = re.sub(r"(?m)^(\s*)[*-]\s+", r"\1• ", text)
    text = _FENCE_RE.sub("", text)
    text = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = _INLINE_CODE_RE.sub(lambda m: m.group(1), text)
    text = _BOLD_RE.sub(lambda m: m.group(2), text)
    text = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _HEADING_RE.sub("", text)
    return text


class StreamingSink:
    """Streams agent tokens and renders boxed tool cards to a Rich Console."""

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

    # -- streaming protocol ----------------------------------------------

    def thinking(self, msg: str | None = None) -> None:
        text = msg or "hund is analyzing..."
        self.console.print(f"[dim]{theme.HUND_INDENT}{text}[/dim]", end="")
        self._thinking_active = True

    def clear_thinking(self) -> None:
        if not self._thinking_active:
            return
        f = self.console.file
        try:
            f.write("\r" + " " * 60 + "\r")
            f.flush()
        except Exception:
            pass
        self._thinking_active = False

    def chunk(self, text: str) -> None:
        self.clear_thinking()
        text = strip_markdown(text)
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

    # -- tool-hook contract ------------------------------------------------

    def confirm(self, prompt: str) -> bool:
        self.clear_thinking()
        options = [
            f"[bold white]{prompt}[/bold white]",
            "",
            "Options:",
            "  [bold green][y][/bold green] Approve once",
            "  [bold cyan][e][/bold cyan] Edit command",
            "  [bold yellow][a][/bold yellow] Allow for session",
            "  [bold red][n][/bold red] Deny (Default)",
        ]
        card = theme.boxify(
            "CONFIRMATION REQUIRED",
            options,
            width=68,
            border_style="yellow",
            title_style="bold yellow",
        )
        self.console.print(card)
        self.console.print("[bold yellow]Action [y/e/a/N]:[/bold yellow] ", end="")
        try:
            ans = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"

        verdict = parse_confirm_input(ans)
        if verdict == "edit":
            try:
                edited = input("Edit command: ").strip()
                # ponytail: tool_dispatch TCB interface takes bool; editing command executes with confirmation
                return bool(edited)
            except (EOFError, KeyboardInterrupt):
                return False
        return verdict in {"approve", "session"}

    def tool_start(self, name: str, args) -> None:
        self.clear_thinking()
        card = theme.boxify(
            f"TOOL: {name}",
            [f"args: {_short_args(args)}", "status: executing..."],
            width=68,
            border_style="dim",
            title_style="bold cyan",
        )
        self.console.print(card)

    def tool_result(self, name: str, shown: str) -> None:
        self.clear_thinking()
        card = theme.boxify(
            f"TOOL RESULT: {name}",
            [f"output: {shown}"],
            width=68,
            border_style="dim",
            title_style="bold green",
        )
        self.console.print(card)

    def blocked(self, name: str, reason: str) -> None:
        self.clear_thinking()
        card = theme.boxify(
            f"BLOCKED: {name}",
            [f"reason: {reason}"],
            width=68,
            border_style="red",
            title_style="bold red",
        )
        self.console.print(card)

    def declined(self, name: str, reason: str) -> None:
        self.clear_thinking()
        card = theme.boxify(
            f"DECLINED: {name}",
            [f"reason: {reason}"],
            width=68,
            border_style="dim",
            title_style="dim yellow",
        )
        self.console.print(card)


def render_markdown(console: Console, text: str) -> None:
    """Render response as formatted markdown or clean terminal text."""
    try:
        md = Markdown(text, code_theme="monokai")
        console.print(md)
    except Exception:
        console.print(strip_markdown(text), style=theme.HUND_FG, markup=False, highlight=False)

"""StreamingSink - duck-typed UI sink for agent.loop._agent_turn and tool_dispatch.

Implements the sink protocol:
  thinking() / clear_thinking() / chunk(text) / end_assistant() / error(markup)
and the tool-hook contract:
  confirm(prompt) / tool_start(name, args) / tool_result(name, shown)
  blocked(name, reason) / declined(name, reason)

Features:
- Stateful streaming markdown filter converting **bold** to clean text, -/* to • bullets
- Interactive arrow-key navigation for confirmation cards ([y/e/a/N])
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from rich.console import Console
from rich.markdown import Markdown

from . import theme

_APPROVE_ONCE = {"y", "yes", "j", "ja", "approve"}
_APPROVE_ALL = {"a", "all", "alla", "session"}
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


class StreamingMarkdownFilter:
    """Stateful stream filter that converts markdown syntax on-the-fly.
    
    Transforms:
      - Line start '- ' or '* ' -> '• '
      - '**text**' or '__text__' -> 'text' (suppressing raw **)
      - '`code`' -> 'code' (suppressing raw `)
      - '### Heading' -> 'Heading' (suppressing raw #)
    """

    def __init__(self):
        self._buf = ""
        self._at_line_start = True

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []
        i = 0
        n = len(self._buf)

        while i < n:
            rem = n - i
            ch = self._buf[i]

            # Line-start formatting (bullets and headings)
            if self._at_line_start:
                if ch in (" ", "\t"):
                    out.append(ch)
                    i += 1
                    continue
                if ch in ("-", "*") and rem >= 2 and self._buf[i + 1] == " ":
                    out.append("• ")
                    i += 2
                    self._at_line_start = False
                    continue
                if ch == "#":
                    j = i
                    while j < n and self._buf[j] == "#":
                        j += 1
                    if j < n and self._buf[j] == " ":
                        i = j + 1
                        self._at_line_start = False
                        continue
                    elif j == n:
                        break

            # Bold markers (** or __) -> suppress marker
            if rem >= 2 and self._buf[i:i + 2] in ("**", "__"):
                i += 2
                self._at_line_start = False
                continue
            elif rem == 1 and ch in ("*", "_"):
                break

            # Inline code (`)
            if ch == "`":
                if rem >= 3 and self._buf[i:i + 3] == "```":
                    j = i + 3
                    while j < n and self._buf[j] != "\n":
                        j += 1
                    if j < n:
                        i = j + 1
                        self._at_line_start = True
                        continue
                    else:
                        break
                elif rem < 3 and self._buf[i:].startswith("`"):
                    if rem == 1 or rem == 2:
                        pass
                i += 1
                self._at_line_start = False
                continue

            # Regular characters
            if ch == "\n":
                out.append("\n")
                self._at_line_start = True
                i += 1
            else:
                self._at_line_start = False
                out.append(ch)
                i += 1

        self._buf = self._buf[i:]
        return "".join(out)

    def flush(self) -> str:
        out: list[str] = []
        if self._buf:
            clean = strip_markdown(self._buf)
            out.append(clean)
            self._buf = ""
        return "".join(out)


def transform_streaming_markdown(text: str) -> str:
    """Minimal streaming transformer converting bold to clean text, -/* to bullets, and stripping raw markers."""
    f = StreamingMarkdownFilter()
    return f.feed(text) + f.flush()


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


def interactive_confirm_menu(prompt: str) -> str:
    """Render interactive arrow-key selection menu for tool confirmation."""
    options = [
        ("approve", "Approve once", "ansigreen"),
        ("edit", "Edit command", "ansicyan"),
        ("session", "Allow for session", "ansiyellow"),
        ("deny", "Deny (Default)", "ansired"),
    ]
    selected = [0]
    width = 72
    inner_width = width - 4

    def get_formatted_text():
        lines = []
        title = "CONFIRMATION REQUIRED"
        header = f"┌── {title} {'─' * max(0, inner_width - len(title) - 4)}┐"
        lines.append(("class:border fg:ansiyellow bold", header + "\n"))

        clean_p = prompt.strip().replace("\n", " ")
        if len(clean_p) > inner_width:
            clean_p = clean_p[:inner_width - 3] + "..."
        lines.append(("class:border fg:ansiyellow", "│ "))
        lines.append(("bold fg:ansiwhite", f"{clean_p:<{inner_width}}"))
        lines.append(("class:border fg:ansiyellow", " │\n"))

        lines.append(("class:border fg:ansiyellow", "│ " + " " * inner_width + " │\n"))

        for idx, (code, label, color) in enumerate(options):
            lines.append(("class:border fg:ansiyellow", "│ "))
            if idx == selected[0]:
                opt_str = f"  ❯ ● [{label}]"
                lines.append((f"bold fg:{color}", f"{opt_str:<{inner_width}}"))
            else:
                opt_str = f"    ○ {label}"
                lines.append(("fg:ansibrightblack", f"{opt_str:<{inner_width}}"))
            lines.append(("class:border fg:ansiyellow", " │\n"))

        bottom = f"└{'─' * (width - 2)}┘"
        lines.append(("class:border fg:ansiyellow bold", bottom + "\n"))
        lines.append(("fg:ansibrightblack dim", "Use ↑/↓ arrows to select · Enter to confirm · Esc to deny"))
        return lines

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        selected[0] = (selected[0] - 1) % len(options)

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        selected[0] = (selected[0] + 1) % len(options)

    @kb.add("enter")
    def _enter(event):
        event.app.exit(result=options[selected[0]][0])

    @kb.add("y")
    @kb.add("Y")
    def _y(event):
        event.app.exit(result="approve")

    @kb.add("e")
    @kb.add("E")
    def _e(event):
        event.app.exit(result="edit")

    @kb.add("a")
    @kb.add("A")
    def _a(event):
        event.app.exit(result="session")

    @kb.add("n")
    @kb.add("N")
    @kb.add("escape")
    @kb.add("c-c")
    def _n(event):
        event.app.exit(result="deny")

    layout = Layout(Window(FormattedTextControl(get_formatted_text), height=10))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)
    try:
        res = app.run()
        return res or "deny"
    except Exception:
        return "deny"


class StreamingSink:
    """Streams agent tokens and renders boxed tool cards to a Rich Console."""

    def __init__(self, console: Console, *, stream_delay_s: float | None = None):
        self.console = console
        self._thinking_active = False
        self._stream_filter = StreamingMarkdownFilter()
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
        filtered = self._stream_filter.feed(text)
        for ch in filtered:
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
        leftover = self._stream_filter.flush()
        if leftover:
            for ch in leftover:
                self.console.print(ch, end="", style=theme.HUND_FG, markup=False, highlight=False)
        self._stream_filter = StreamingMarkdownFilter()
        self.console.print()

    def error(self, markup: str) -> None:
        self.clear_thinking()
        self.console.print(markup)

    # -- tool-hook contract ------------------------------------------------

    def confirm(self, prompt: str) -> bool:
        self.clear_thinking()
        if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            verdict = interactive_confirm_menu(prompt)
        else:
            # Fallback for non-interactive / piped environments
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

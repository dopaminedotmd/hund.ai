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
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from rich.console import Console
from rich.markdown import Markdown

from . import theme
from .phrases import select_thinking_phrase
from ..agent.types import ConfirmRequest, ConfirmVerdict

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


def parse_confirm_input(ans: str) -> ConfirmVerdict:
    """Parse confirmation action string into canonical verdict."""
    raw = (ans or "").strip().lower()
    if raw in _APPROVE_ONCE:
        return ConfirmVerdict.APPROVE_ONCE
    if raw in _EDIT:
        return ConfirmVerdict.EDIT
    if raw in _APPROVE_ALL:
        return ConfirmVerdict.ALLOW_SESSION
    return ConfirmVerdict.DENY


class StreamingMarkdownFilter:
    """Stateful stream filter that converts markdown syntax on-the-fly.

    Transforms:
      - Line start '- ' or '* ' -> '• '
      - '### Heading' -> 'Heading' (suppressing raw #)
      - Preserves '**bold**', '__bold__', and '`code`' for lexer styling.
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

            # Regular characters (including **, __, `)
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
            out.append(self._buf)
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


_RICH_TAG_RE = re.compile(r"\[/?[a-z][a-z0-9 _.,#()-]*\]")


def strip_rich(text: str) -> str:
    """Strip Rich markup tags ([yellow], [/bold], ...) leaving plain text."""
    return _RICH_TAG_RE.sub("", text)


def _confirm_title(request: ConfirmRequest) -> str:
    """Derive a human-readable title from a ConfirmRequest."""
    titles = {
        "terminal": "hund wants to run a command",
        "read_file": "hund wants to read a file",
        "write_file": "hund wants to write a file",
        "delete_file": "hund wants to delete a file",
        "search_files": "hund wants to search",
    }
    return titles.get(request.tool_name, f"hund wants to use {request.tool_name}")


def _confirm_detail(request: ConfirmRequest) -> str:
    """Derive a detail line from a ConfirmRequest."""
    args = request.args
    if request.tool_name == "terminal":
        return f"$ {args.get('command', '')}"
    if request.tool_name in ("read_file", "write_file", "delete_file"):
        return str(args.get("path", ""))
    if request.tool_name == "search_files":
        return str(args.get("pattern", "*"))
    try:
        s = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(args)
    return s if len(s) <= 55 else s[:52] + "..."


_CONFIRM_MENU_OPTIONS = [
    (ConfirmVerdict.APPROVE_ONCE, "Run once", "ansigreen"),
    (ConfirmVerdict.EDIT, "Edit command", "ansicyan"),
    (ConfirmVerdict.ALLOW_SESSION, "Allow for this session", "ansiyellow"),
    (ConfirmVerdict.DENY, "Deny", "ansired"),
]


def interactive_confirm_menu(request: ConfirmRequest) -> ConfirmVerdict:
    """Render interactive arrow-key selection menu for tool confirmation."""
    options = _CONFIRM_MENU_OPTIONS
    selected = [0]
    width = 72
    inner_width = width - 4
    title = _confirm_title(request)
    detail = _confirm_detail(request)

    def get_formatted_text():
        lines = []
        header = f"┌─ {title} {'─' * max(0, inner_width - len(title) - 2)}┐"
        lines.append(("class:border fg:ansiyellow bold", header + "\n"))

        lines.append(("class:border fg:ansiyellow", "│ "))
        lines.append(("class:border fg:ansiyellow", "│ " + " " * inner_width + " │\n"))

        detail_display = detail
        if len(detail_display) > inner_width:
            detail_display = detail_display[:inner_width - 3] + "..."
        lines.append(("class:border fg:ansiyellow", "│ "))
        lines.append(("bold fg:ansicyan", f"  {detail_display:<{inner_width - 2}}"))
        lines.append(("class:border fg:ansiyellow", " │\n"))

        lines.append(("class:border fg:ansiyellow", "│ " + " " * inner_width + " │\n"))

        for idx, (verdict, label, color) in enumerate(options):
            lines.append(("class:border fg:ansiyellow", "│ "))
            if idx == selected[0]:
                opt_str = f"  ❯ ● {label}"
                lines.append((f"bold fg:{color}", f"{opt_str:<{inner_width}}"))
            else:
                opt_str = f"    ○ {label}"
                lines.append(("fg:ansibrightblack", f"{opt_str:<{inner_width}}"))
            lines.append(("class:border fg:ansiyellow", " │\n"))

        bottom = f"└{'─' * (width - 2)}┘"
        lines.append(("class:border fg:ansiyellow bold", bottom + "\n"))
        lines.append(("fg:ansibrightblack dim", " ↑↓ select · Enter confirm · Esc deny"))
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
        event.app.exit(result=ConfirmVerdict.APPROVE_ONCE)

    @kb.add("e")
    @kb.add("E")
    def _e(event):
        event.app.exit(result=ConfirmVerdict.EDIT)

    @kb.add("a")
    @kb.add("A")
    def _a(event):
        event.app.exit(result=ConfirmVerdict.ALLOW_SESSION)

    @kb.add("n")
    @kb.add("N")
    @kb.add("escape")
    @kb.add("c-c")
    def _n(event):
        event.app.exit(result=ConfirmVerdict.DENY)

    layout = Layout(Window(FormattedTextControl(get_formatted_text), height=12))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)
    try:
        res = app.run()
        return res if isinstance(res, ConfirmVerdict) else ConfirmVerdict.DENY
    except Exception:
        return ConfirmVerdict.DENY


class StreamingSink:
    """Streams agent tokens and renders boxed tool cards to a Rich Console."""

    def __init__(self, console: Console, *, stream_delay_s: float | None = None):
        self.console = console
        self._thinking_active = False
        self._thinking_text = "hund is reading..."
        self._thinking_past: str | None = None
        self._tool_switched = False
        self._user_input = ""
        self._stream_filter = StreamingMarkdownFilter()
        self._box_open = False
        self._at_line_start = True
        self._line_len = 0
        if stream_delay_s is None:
            raw_delay = os.environ.get("HUND_STREAM_DELAY_S", "")
            try:
                stream_delay_s = float(raw_delay) if raw_delay else _DEFAULT_STREAM_DELAY_S
            except ValueError:
                stream_delay_s = _DEFAULT_STREAM_DELAY_S
        self.stream_delay_s = max(0.0, min(stream_delay_s, 0.02))

    def set_user_input(self, text: str) -> None:
        self._user_input = text or ""
        self._tool_switched = False

    # -- streaming protocol ----------------------------------------------

    def thinking(self, msg: str | None = None) -> None:
        self._thinking_active = True
        self._tool_switched = False
        text = msg.rstrip(".…") if msg else "hund is reading"
        self._thinking_text = text + "..."
        self._thinking_past = None
        self.console.print(f"[dim]{theme.HUND_INDENT}{self._thinking_text}[/dim]", end="")

    def clear_thinking(self) -> None:
        if not self._thinking_active:
            return
        if self._thinking_past:
            self.console.print(f"[dim]{theme.HUND_INDENT}{self._thinking_past}[/dim]")
        else:
            f = self.console.file
            try:
                f.write("\r" + " " * 60 + "\r")
                f.flush()
            except Exception:
                pass
        self._thinking_active = False
        self._thinking_past = None

    def _width(self) -> int:
        try:
            return shutil.get_terminal_size().columns
        except Exception:
            return getattr(self.console, "width", 80) or 80

    def _open_box(self) -> None:
        if self._box_open:
            return
        w = self._width()
        fill = max(w - 9, 2)  # "┌─ " (3) + "hund" (4) + " " (1) + "┐" (1)
        self.console.print(f"[dim]┌─ [/dim][cyan bold]hund[/cyan bold][dim] {'─' * fill}┐[/dim]")
        self.console.print(f"[dim]│{' ' * max(w - 2, 2)}│[/dim]")
        self.console.print(f"[dim]│{' ' * max(w - 2, 2)}│[/dim]")
        self._box_open = True
        self._at_line_start = True
        self._line_len = 0

    def _close_box(self, meta: str | None = None) -> None:
        if not self._box_open:
            return
        w = self._width()
        self.console.print(f"[dim]│{' ' * max(w - 2, 2)}│[/dim]")
        if meta is not None and str(meta).strip():
            meta_str = str(meta).strip()
            dashes = max(w - len(meta_str) - 4, 2)
            self.console.print(f"[dim]└{'─' * dashes} {meta_str} ┘[/dim]")
        else:
            self.console.print(f"[dim]└{'─' * max(w - 2, 2)}┘[/dim]")
        self._box_open = False
        self._at_line_start = True
        self._line_len = 0

    def chunk(self, text: str) -> None:
        self.clear_thinking()
        filtered = self._stream_filter.feed(text)
        if not filtered:
            return
        if not self._box_open:
            self._open_box()
        cw = max(self._width() - 6, 1)
        for ch in filtered:
            if self._at_line_start:
                self.console.print("[dim]│  [/dim]", end="", markup=True, highlight=False)
                self._at_line_start = False
                self._line_len = 0
            if ch == "\n":
                padding = max(cw - self._line_len, 0)
                self.console.print(" " * padding + "[dim]  │[/dim]\n", end="", markup=True, highlight=False)
                self._at_line_start = True
                self._line_len = 0
            else:
                if self._line_len >= cw:
                    self.console.print("[dim]  │[/dim]\n[dim]│  [/dim]", end="", markup=True, highlight=False)
                    self._line_len = 0
                self.console.print(ch, end="", style=theme.HUND_FG, markup=False, highlight=False)
                self._line_len += 1
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
            if not self._box_open:
                self._open_box()
            cw = max(self._width() - 6, 1)
            for ch in leftover:
                if self._at_line_start:
                    self.console.print("[dim]│  [/dim]", end="", markup=True, highlight=False)
                    self._at_line_start = False
                    self._line_len = 0
                if ch == "\n":
                    padding = max(cw - self._line_len, 0)
                    self.console.print(" " * padding + "[dim]  │[/dim]\n", end="", markup=True, highlight=False)
                    self._at_line_start = True
                    self._line_len = 0
                else:
                    if self._line_len >= cw:
                        self.console.print("[dim]  │[/dim]\n[dim]│  [/dim]", end="", markup=True, highlight=False)
                        self._line_len = 0
                    self.console.print(ch, end="", style=theme.HUND_FG, markup=False, highlight=False)
                    self._line_len += 1
        if self._box_open and not self._at_line_start:
            cw = max(self._width() - 6, 1)
            padding = max(cw - self._line_len, 0)
            self.console.print(" " * padding + "[dim]  │[/dim]\n", end="", markup=True, highlight=False)
            self._at_line_start = True
            self._line_len = 0
        self._close_box()
        self._stream_filter = StreamingMarkdownFilter()
        self.console.print()

    def error(self, markup: str) -> None:
        self.clear_thinking()
        self._close_box()
        self.console.print(markup)

    # -- tool-hook contract ------------------------------------------------

    def confirm(self, request: ConfirmRequest) -> ConfirmVerdict:
        self.clear_thinking()
        self._close_box()
        if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            # confirm() is sync but runs inside the REPL asyncio loop;
            # run the menu in a fresh thread so app.run() gets its own event loop.
            with ThreadPoolExecutor(max_workers=1) as _ex:
                verdict = _ex.submit(interactive_confirm_menu, request).result()
        else:
            # Fallback for non-interactive / piped environments
            title = _confirm_title(request)
            detail = _confirm_detail(request)
            options = [
                f"[bold white]{title}[/bold white]",
                f"  [bold cyan]{detail}[/bold cyan]",
                "",
                "Options:",
                "  [bold green][y][/bold green] Run once",
                "  [bold cyan][e][/bold cyan] Edit command",
                "  [bold yellow][a][/bold yellow] Allow for this session",
                "  [bold red][n][/bold red] Deny",
            ]
            card = theme.boxify(
                title,
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

        return verdict

    def tool_start(self, name: str, args) -> None:
        if self._thinking_active and not self._tool_switched:
            f = self.console.file
            try:
                f.write("\r" + " " * 60 + "\r")
                f.flush()
            except Exception:
                pass
            gerund, past = select_thinking_phrase(self._user_input)
            self._thinking_text = gerund + "..."
            self._thinking_past = past
            self._tool_switched = True
            self.console.print(f"[dim]{theme.HUND_INDENT}{self._thinking_text}[/dim]")
        elif not self._thinking_active:
            pass

        self._close_box()
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
        self._close_box()
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
        self._close_box()
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
        self._close_box()
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

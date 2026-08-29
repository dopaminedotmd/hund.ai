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

from dataclasses import dataclass, field
from enum import Enum
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
from .activity import describe_tool
from .render import box_bottom, box_top, response_padding
from ..agent.types import ConfirmRequest, ConfirmVerdict
from .confirmation import confirmation_options, prompt_edits

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


class SegmentType(str, Enum):
    PROSE = "prose"
    CODE = "code"
    DIFF = "diff"


@dataclass
class SemanticSegment:
    type: SegmentType
    language: str = ""
    filename: str = ""
    lines: list[str] = field(default_factory=list)
    is_open: bool = False
    closed_by_eof: bool = False

    def freeze(self) -> FrozenSemanticSegment:
        return FrozenSemanticSegment(
            type=self.type,
            language=self.language,
            filename=self.filename,
            lines=tuple(self.lines),
            is_open=self.is_open,
            closed_by_eof=self.closed_by_eof,
        )


@dataclass(frozen=True)
class FrozenSemanticSegment:
    type: SegmentType
    language: str = ""
    filename: str = ""
    lines: tuple[str, ...] = field(default_factory=tuple)
    is_open: bool = False
    closed_by_eof: bool = False


class StreamingMarkdownFilter:
    """Persistent, O(n) incremental streaming markdown filter and segment parser.

    Maintains state across delta chunks without reparsing finalized segments
    and preserves original canonical chunks verbatim.
    """

    def __init__(self, content_width: int = 74):
        self.content_width = content_width
        self._canonical_chunks: list[str] = []
        self._segments: list[FrozenSemanticSegment] = []
        self._active_segment = SemanticSegment(type=SegmentType.PROSE, is_open=True)
        self._chars: list[str] = []
        self._cursor: int = 0
        self._pending_cr: bool = False
        self._at_line_start = True
        self._in_fence = False
        self._fence_info = ""
        self._fence_lines: list[str] = []
        self._prose_line: list[str] = []
        self._emitted_len = 0
        self._parse_calls_count = 0  # Instrumentation counter for O(n) verification

    @property
    def canonical_source(self) -> str:
        """Join canonical chunks on demand without modifying raw code points."""
        return "".join(self._canonical_chunks)

    @property
    def segments(self) -> list[FrozenSemanticSegment]:
        return self.get_segments()

    def get_segments(self) -> list[FrozenSemanticSegment]:
        res = list(self._segments)
        active_lines = list(self._active_segment.lines)
        if self._prose_line and not self._in_fence:
            active_lines.append("".join(self._prose_line))
        if active_lines or (self._in_fence and self._active_segment.is_open):
            seg = SemanticSegment(
                type=self._active_segment.type,
                language=self._active_segment.language,
                filename=self._active_segment.filename,
                lines=active_lines,
                is_open=self._active_segment.is_open,
                closed_by_eof=self._active_segment.closed_by_eof,
            )
            res.append(seg.freeze())
        return res

    def _render_fence(self, is_open: bool = False) -> str:
        from .render import format_code_block, format_diff_block

        code_text = "\n".join(self._fence_lines)
        info = self._fence_info.strip()
        tokens = info.split()
        lang = tokens[0].lower() if tokens else ""
        filename = tokens[1] if len(tokens) > 1 else ""

        # Extension-gated filename detection from first line comment if not provided
        if not filename and self._fence_lines:
            first_line = self._fence_lines[0].strip()
            fn_match = re.match(r"^(?:#|//|/\*|--)\s*([\w\-./\\]+\.[a-zA-Z0-9]+)(?:\s*\*/)?$", first_line)
            if fn_match:
                filename = fn_match.group(1).split("/")[-1].split("\\")[-1]
                self._fence_lines = self._fence_lines[1:]
                code_text = "\n".join(self._fence_lines)

        is_diff = lang in ("diff", "patch")
        if is_diff:
            fn = filename if filename else (tokens[0] if (tokens and "." in tokens[0] and lang != "diff") else "")
            return "\n" + format_diff_block(code_text, filename=fn, width=self.content_width, is_open=is_open) + "\n"
        else:
            fn = filename if filename else (tokens[0] if (tokens and "." in tokens[0]) else "")
            language = lang if not ("." in lang) else ""
            return "\n" + format_code_block(code_text, language=language, filename=fn, width=self.content_width, is_open=is_open) + "\n"

    def feed(self, text: str) -> str:
        if not text:
            return ""

        self._parse_calls_count += 1
        # Store verbatim canonical code points
        self._canonical_chunks.append(text)

        # Normalize line endings for presentation state
        for ch in text:
            if self._pending_cr:
                self._pending_cr = False
                if ch == "\n":
                    self._chars.append("\n")
                    continue
                else:
                    self._chars.append("\n")
            if ch == "\r":
                self._pending_cr = True
            else:
                self._chars.append(ch)

        out: list[str] = []
        i = self._cursor
        n = len(self._chars)

        while i < n:
            rem = n - i
            ch = self._chars[i]

            if self._in_fence:
                if self._at_line_start:
                    # Look ahead for closing fence
                    if ch == "`":
                        if rem < 3:
                            # Incomplete fence prefix - wait for more chars
                            break
                        if self._chars[i : i + 3] == ["`", "`", "`"]:
                            # Find newline
                            nl_pos = -1
                            for idx in range(i + 3, n):
                                if self._chars[idx] == "\n":
                                    nl_pos = idx
                                    break
                            if nl_pos == -1:
                                # Wait for full closing line
                                break
                            self._in_fence = False
                            self._active_segment.is_open = False
                            self._segments.append(self._active_segment.freeze())
                            self._active_segment = SemanticSegment(type=SegmentType.PROSE, is_open=True)
                            out.append(self._render_fence(is_open=False))
                            self._fence_lines = []
                            self._fence_info = ""
                            self._at_line_start = True
                            i = nl_pos + 1
                            continue

                # Code line accumulation
                nl_pos = -1
                for idx in range(i, n):
                    if self._chars[idx] == "\n":
                        nl_pos = idx
                        break
                if nl_pos == -1:
                    break
                line = "".join(self._chars[i:nl_pos])
                self._fence_lines.append(line)
                self._active_segment.lines.append(line)
                self._at_line_start = True
                i = nl_pos + 1
                continue

            # Outside fence (prose)
            if self._at_line_start:
                if ch == "`":
                    if rem < 3:
                        # Incomplete opening fence prefix - wait for more chars
                        break
                    if self._chars[i : i + 3] == ["`", "`", "`"]:
                        nl_pos = -1
                        for idx in range(i + 3, n):
                            if self._chars[idx] == "\n":
                                nl_pos = idx
                                break
                        if nl_pos == -1:
                            break
                        fence_header = "".join(self._chars[i + 3 : nl_pos]).strip()
                        if self._prose_line:
                            self._active_segment.lines.append("".join(self._prose_line))
                            self._prose_line = []
                        if self._active_segment.lines:
                            self._active_segment.is_open = False
                            self._segments.append(self._active_segment.freeze())

                        info_tokens = fence_header.split()
                        lang = info_tokens[0].lower() if info_tokens else ""
                        filename = info_tokens[1] if len(info_tokens) > 1 else ""
                        is_diff = lang in ("diff", "patch")

                        self._in_fence = True
                        self._fence_info = fence_header
                        self._fence_lines = []
                        self._active_segment = SemanticSegment(
                            type=SegmentType.DIFF if is_diff else SegmentType.CODE,
                            language=lang,
                            filename=filename,
                            is_open=True,
                        )
                        self._at_line_start = True
                        i = nl_pos + 1
                        continue

                if ch in (" ", "\t"):
                    out.append(ch)
                    self._prose_line.append(ch)
                    i += 1
                    continue
                if ch in ("-", "*") and rem >= 2 and self._chars[i + 1] == " ":
                    out.append("• ")
                    self._prose_line.append("• ")
                    i += 2
                    self._at_line_start = False
                    continue
                if ch == "#":
                    j = i
                    while j < n and self._chars[j] == "#":
                        j += 1
                    if j < n and self._chars[j] == " ":
                        i = j + 1
                        self._at_line_start = False
                        continue
                    elif j == n:
                        break

            if ch == "\n":
                out.append("\n")
                if self._prose_line:
                    self._active_segment.lines.append("".join(self._prose_line))
                    self._prose_line = []
                else:
                    self._active_segment.lines.append("")
                self._at_line_start = True
                i += 1
            else:
                self._at_line_start = False
                out.append(ch)
                self._prose_line.append(ch)
                i += 1

        self._cursor = i
        if self._cursor > 1024:
            self._chars = self._chars[self._cursor:]
            self._cursor = 0

        emitted = "".join(out)
        self._emitted_len += len(emitted)
        return emitted

    def flush(self) -> str:
        if self._pending_cr:
            self._chars.append("\n")
            self._pending_cr = False

        out: list[str] = []
        rem_chars = self._chars[self._cursor:]
        self._chars.clear()
        self._cursor = 0
        rem_str = "".join(rem_chars)

        if self._in_fence:
            if rem_str:
                if rem_str.strip() == "```":
                    self._active_segment.is_open = False
                else:
                    line = rem_str.rstrip("\n")
                    self._fence_lines.append(line)
                    self._active_segment.lines.append(line)
                    self._active_segment.is_open = False
                    self._active_segment.closed_by_eof = True
            else:
                self._active_segment.is_open = False
                self._active_segment.closed_by_eof = True

            self._segments.append(self._active_segment.freeze())
            self._active_segment = SemanticSegment(type=SegmentType.PROSE, is_open=False)
            self._in_fence = False
            out.append(self._render_fence(is_open=False))
            self._fence_lines = []
            self._fence_info = ""
        else:
            if self._prose_line:
                self._active_segment.lines.append("".join(self._prose_line))
                self._prose_line = []
            elif rem_str:
                self._active_segment.lines.append(rem_str)
                out.append(rem_str)

            if self._active_segment.lines:
                self._active_segment.is_open = False
                self._segments.append(self._active_segment.freeze())
                self._active_segment = SemanticSegment(type=SegmentType.PROSE, is_open=False)
        return "".join(out)


def parse_semantic_segments(text: str, content_width: int = 74) -> list[FrozenSemanticSegment]:
    """Parse raw Markdown into immutable typed semantic segments."""
    parser = StreamingMarkdownFilter(content_width=content_width)
    parser.feed(text)
    parser.flush()
    return parser.get_segments()


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


_CONFIRM_COLORS = {
    ConfirmVerdict.APPROVE_ONCE: "ansigreen",
    ConfirmVerdict.EDIT: "ansicyan",
    ConfirmVerdict.ALLOW_SESSION: "ansiyellow",
    ConfirmVerdict.DENY: "ansired",
}


def tool_thinking_phrase(name: str, args: dict | None = None) -> tuple[str, str]:
    """Map observed tool starts to live/past status text."""
    if name in {"read_file"}:
        return "hund is reading", "hund read the relevant files."
    if name in {"search_files"}:
        return "hund is inspecting", "hund inspected the workspace."
    if name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
        return "hund is editing", "hund edited the workspace."
    if name in {"web_search", "web_open", "web_extract", "fetch_web_page", "read_url_content"}:
        return "hund is researching", "hund researched external sources."
    if name == "terminal":
        try:
            from ..agent.verification import VerificationKind, classify_verification

            if classify_verification(str((args or {}).get("command", ""))) is not VerificationKind.NONE:
                return "hund is verifying", "hund verified the result."
        except Exception:
            pass
        return "hund is executing", "hund executed the command."
    return "hund is working", f"hund used {name}."


def interactive_confirm_menu(request: ConfirmRequest) -> ConfirmVerdict:
    """Render interactive arrow-key selection menu for tool confirmation."""
    options = [(v, label, _CONFIRM_COLORS[v]) for v, label in confirmation_options(request.tool_name)]
    selected = [0]
    width = 72
    inner_width = width - 4
    title = _confirm_title(request)
    detail = _confirm_detail(request)

    def get_formatted_text():
        lines = []
        header = f"╭─ {title} {'─' * max(0, inner_width - len(title) - 2)}╮"
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

        bottom = f"╰{'─' * (width - 2)}╯"
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
        verdicts = {item[0] for item in options}
        event.app.exit(
            result=ConfirmVerdict.EDIT if ConfirmVerdict.EDIT in verdicts else ConfirmVerdict.DENY
        )

    @kb.add("a")
    @kb.add("A")
    def _a(event):
        verdicts = {item[0] for item in options}
        event.app.exit(
            result=(
                ConfirmVerdict.ALLOW_SESSION
                if ConfirmVerdict.ALLOW_SESSION in verdicts
                else ConfirmVerdict.DENY
            )
        )

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
        self._turn_start_time = 0.0
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
        self._turn_start_time = time.time()

    # -- streaming protocol ----------------------------------------------

    def thinking(self, msg: str | None = None) -> None:
        if not self._turn_start_time:
            self._turn_start_time = time.time()
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
        top = box_top(w)
        self.console.print(
            f"[dim]{top[:3]}[/dim][cyan bold]hund[/cyan bold][dim]{top[7:]}[/dim]"
        )
        # 1 top padding row per TUI_FACIT.md §2 and §15
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
            self.console.print(f"[dim]{box_bottom(w, str(meta).strip())}[/dim]")
        else:
            self.console.print(f"[dim]{box_bottom(w)}[/dim]")
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
        inset = response_padding(self._width())
        cw = max(self._width() - 2 - 2 * inset, 1)
        for ch in filtered:
            if self._at_line_start:
                self.console.print(f"[dim]│{' ' * inset}[/dim]", end="", markup=True, highlight=False)
                self._at_line_start = False
                self._line_len = 0
            if ch == "\n":
                padding = max(cw - self._line_len, 0)
                self.console.print(" " * padding + f"[dim]{' ' * inset}│[/dim]\n", end="", markup=True, highlight=False)
                self._at_line_start = True
                self._line_len = 0
            else:
                if self._line_len >= cw:
                    self.console.print(f"[dim]{' ' * inset}│[/dim]\n[dim]│{' ' * inset}[/dim]", end="", markup=True, highlight=False)
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
            inset = response_padding(self._width())
            cw = max(self._width() - 2 - 2 * inset, 1)
            for ch in leftover:
                if self._at_line_start:
                    self.console.print(f"[dim]│{' ' * inset}[/dim]", end="", markup=True, highlight=False)
                    self._at_line_start = False
                    self._line_len = 0
                if ch == "\n":
                    padding = max(cw - self._line_len, 0)
                    self.console.print(" " * padding + f"[dim]{' ' * inset}│[/dim]\n", end="", markup=True, highlight=False)
                    self._at_line_start = True
                    self._line_len = 0
                else:
                    if self._line_len >= cw:
                        self.console.print(f"[dim]{' ' * inset}│[/dim]\n[dim]│{' ' * inset}[/dim]", end="", markup=True, highlight=False)
                        self._line_len = 0
                    self.console.print(ch, end="", style=theme.HUND_FG, markup=False, highlight=False)
                    self._line_len += 1
        if self._box_open and not self._at_line_start:
            inset = response_padding(self._width())
            cw = max(self._width() - 2 - 2 * inset, 1)
            padding = max(cw - self._line_len, 0)
            self.console.print(" " * padding + f"[dim]{' ' * inset}│[/dim]\n", end="", markup=True, highlight=False)
            self._at_line_start = True
            self._line_len = 0
        duration = time.time() - self._turn_start_time if self._turn_start_time else 0.0
        self._close_box(f"{duration:.1f}s" if duration > 0 else None)
        self._turn_start_time = 0.0
        self._stream_filter = StreamingMarkdownFilter()
        self.console.print()

    def learning_pending(self, job_id: str) -> None:
        self.console.print("[dim]  · evaluating evidence...[/dim]")

    def learning_receipt(self, receipt) -> None:
        from hund.learning.runtime import format_receipt_bundle

        if receipt.kind == "no_change":
            return
        for line in format_receipt_bundle(receipt):
            self.console.print(f"[dim]{line}[/dim]")

    def error(self, markup: str) -> None:
        self.clear_thinking()
        self._close_box()
        self.console.print(markup)

    # -- tool-hook contract ------------------------------------------------

    def edit(self, request: ConfirmRequest) -> dict | None:
        return prompt_edits(request)

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
            policy_options = confirmation_options(request.tool_name)
            shortcut = {
                ConfirmVerdict.APPROVE_ONCE: "y",
                ConfirmVerdict.EDIT: "e",
                ConfirmVerdict.ALLOW_SESSION: "a",
                ConfirmVerdict.DENY: "n",
            }
            option_lines = [
                f"  [{_CONFIRM_COLORS[verdict]}][{shortcut[verdict]}][/{_CONFIRM_COLORS[verdict]}] {label}"
                for verdict, label in policy_options
            ]
            options = [
                f"[bold white]{title}[/bold white]",
                f"  [bold cyan]{detail}[/bold cyan]",
                "",
                "Options:",
                *option_lines,
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
            if verdict not in {item[0] for item in policy_options}:
                verdict = ConfirmVerdict.DENY

        return verdict

    def tool_start(self, name: str, args) -> None:
        if self._thinking_active and not self._tool_switched:
            f = self.console.file
            try:
                f.write("\r" + " " * 60 + "\r")
                f.flush()
            except Exception:
                pass
            gerund, past = tool_thinking_phrase(name, args if isinstance(args, dict) else None)
            self._thinking_text = gerund + "..."
            self._thinking_past = past
            self._tool_switched = True
            self.console.print(f"[dim]{theme.HUND_INDENT}{past}[/dim]")
            self._thinking_active = False
            self._thinking_past = None
        elif not self._thinking_active:
            pass

        self._close_box()
        self._tool_started_at = time.time()
        self._tool_description = describe_tool(name, args if isinstance(args, dict) else None)
        self.console.print(f"[dim]  ┊ [/dim][cyan]⟳[/cyan] [magenta]{self._tool_description}[/magenta]", end="")

    def tool_result(self, name: str, shown: str) -> None:
        duration = time.time() - getattr(self, "_tool_started_at", time.time())
        desc = getattr(self, "_tool_description", describe_tool(name))
        self.console.print(
            f"\r{' ' * min(self._width(), 160)}\r[dim]  ┊ [/dim][green]✓[/green] "
            f"[magenta]{desc}[/magenta] [dim]{duration:.1f}s[/dim]"
        )

    def blocked(self, name: str, reason: str) -> None:
        desc = getattr(self, "_tool_description", describe_tool(name))
        self.console.print(
            f"\r{' ' * min(self._width(), 160)}\r[dim]  ┊ [/dim][red]✗ {desc} — {reason}[/red]"
        )

    def declined(self, name: str, reason: str) -> None:
        desc = getattr(self, "_tool_description", describe_tool(name))
        self.console.print(
            f"\r{' ' * min(self._width(), 160)}\r[dim]  ┊ [/dim][yellow]✗ {desc} — {reason}[/yellow]"
        )


def render_markdown(console: Console, text: str) -> None:
    """Render response as formatted markdown or clean terminal text."""
    try:
        md = Markdown(text, code_theme="monokai")
        console.print(md)
    except Exception:
        console.print(strip_markdown(text), style=theme.HUND_FG, markup=False, highlight=False)

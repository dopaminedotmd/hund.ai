"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable, semantically-colored output
buffer, a single input buffer, and an in-app arrow-key confirmation modal.

The output buffer is read-only (safe against stray typing) but focusable, so
the mouse can select text; Ctrl+C copies a selection to the clipboard (or
exits when there is none). The agent turn runs in a background thread.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import threading
import time
import uuid
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_completions, has_focus, is_done
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.output.color_depth import ColorDepth
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
from .activity import ActivityStatus, ActivityTimeline, activity_group
from .commands import CommandContext, dispatch_command, is_slash
from .input import (
    SLASH_COMMANDS,
    SLASH_COMMAND_METAS,
    PromptState,
    SlashCommandCompleter,
    MAX_VISIBLE_COMPLETIONS,
    format_duration,
    format_status_bar,
    format_tokens_ratio,
)
from .output import parse_confirm_input, strip_markdown, strip_rich, StreamingMarkdownFilter, _confirm_title, _confirm_detail, tool_thinking_phrase
from .render import box_bottom as _r_box_bottom, box_top as _r_box_top, refresh_stats, render_response_box
from ..agent.types import ConfirmRequest, ConfirmVerdict
from .confirmation import confirmation_options, prompt_edits
from .mascot import MascotMachine
from .screen_state import DestinationView, OverlayView, ScreenController
from .screen_render import (
    fullscreen_frame,
    render_model_custom_modal,
    render_model_key_modal,
    render_model_modal,
    render_skills,
    render_stats,
    render_theme_modal,
    render_tools,
    render_usage,
)
from .snapshots import collect_skills, collect_stats, collect_tools, collect_usage

from .phrases import select_thinking_phrase

_S = theme.SEMANTIC

_STYLE = theme.make_pt_style("marshmallow")


def _output_cursor_position(text: str, *, follow_tail: bool) -> int:
    """Keep startup at the top while streamed history follows its tail."""
    if not follow_tail:
        return 0
    return len(text)


def _responsive_content_width(columns: int) -> int:
    """Reserve the terminal's unsafe final column for every framed component."""
    return max(int(columns) - 1, 24)


class _StableCompletionsMenuControl(CompletionsMenuControl):
    """Completion rows with a stable slash-command column and full-width meta."""

    _SLASH_COLUMN_WIDTH = max(len(command) for command in SLASH_COMMANDS) + 3

    def _get_menu_width(self, max_width, complete_state):
        dynamic = super()._get_menu_width(max_width, complete_state)
        return min(max_width, max(self._SLASH_COLUMN_WIDTH, dynamic))

    def _get_menu_meta_width(self, max_width, complete_state):
        return max_width if self._show_meta(complete_state) else 0


class _FullWidthCompletionsMenu(ConditionalContainer):
    """A terminal-wide completion list without Prompt Toolkit's shrink-to-fit."""

    def __init__(self, max_height: int) -> None:
        super().__init__(
            content=Window(
                content=_StableCompletionsMenuControl(),
                width=Dimension(weight=1),
                height=Dimension(min=1, max=max_height),
                dont_extend_width=False,
                style="class:completion-menu",
                z_index=10**8,
            ),
            filter=has_completions & ~is_done,
        )


def _wheel_scroll_passthrough(mouse_event: MouseEvent, scroll_cb) -> Any:
    """Let the mascot strip scroll the transcript underneath it."""
    if mouse_event.event_type in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
        if scroll_cb is not None:
            scroll_cb(3 if mouse_event.event_type == MouseEventType.SCROLL_UP else -3)
        return None
    return NotImplemented


def _shine_fragments(text: str, base_hex: str, phase: int) -> list[tuple[str, str]]:
    """Render a restrained left-to-right highlight without changing text width."""
    try:
        raw = base_hex.lstrip("#")
        base = tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
        if len(raw) != 6:
            raise ValueError
    except (TypeError, ValueError):
        return [(f"fg:{base_hex}", text)]

    center = phase % (len(text) + 5) - 2
    fragments: list[tuple[str, str]] = []
    for index, char in enumerate(text):
        distance = abs(index - center)
        strength = 0.62 if distance == 0 else 0.30 if distance == 1 else 0.0
        rgb = tuple(round(channel + (255 - channel) * strength) for channel in base)
        color = "#" + "".join(f"{channel:02X}" for channel in rgb)
        fragments.append((f"fg:{color}", char))
    return fragments


class _ScrollThroughFormattedTextControl(FormattedTextControl):
    """Static/animated text control whose wheel events scroll another view."""

    def __init__(self, *args, scroll_cb_getter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._scroll_cb_getter = scroll_cb_getter

    def mouse_handler(self, mouse_event: MouseEvent) -> Any:
        callback = self._scroll_cb_getter() if self._scroll_cb_getter is not None else None
        return _wheel_scroll_passthrough(mouse_event, callback)


def _trunc(val: Any, max_len: int = 45) -> str:
    s = str(val or "")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _format_tool_desc(name: str, args: dict | None) -> str:
    args = args or {}
    if name == "read_file":
        path = _trunc(args.get("path", "file"))
        return f"read {path}"
    elif name == "search_files":
        pattern = _trunc(args.get("pattern", "*"))
        path = args.get("path")
        if path and path != ".":
            return f"searched {_trunc(path)} for {pattern}"
        return f"searched {pattern}"
    elif name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
        path = _trunc(args.get("path") or args.get("file_path") or args.get("target_file") or "workspace")
        return f"modified {path}" if name != "write_file" else f"wrote {path}"
    elif name == "delete_file":
        path = _trunc(args.get("path", "file"))
        return f"deleted {path}"
    elif name == "terminal":
        cmd = _trunc(args.get("command", ""))
        try:
            from ..agent.verification import VerificationKind, classify_verification
            if classify_verification(str(args.get("command", ""))) is not VerificationKind.NONE:
                return "ran targeted tests"
        except Exception:
            pass
        return f"ran {cmd}" if cmd else "ran command"
    elif name == "web_search":
        q = _trunc(args.get("query", ""))
        return f"searched the web for {q}" if q else "searched official sources"
    elif name in {"web_extract", "web_open"}:
        url = _trunc(args.get("url", ""))
        return f"read {url}" if url else "read relevant pages"
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


def _parse_semantic_line(text: str, indent_str: str = "") -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    if indent_str:
        tokens.append(("", indent_str))
    cur = text

    # Code / diff block headers and footers
    if cur.startswith("──"):
        if not cur.strip("─ "):
            return tokens + [("class:secondary", cur)]
        m_diff = re.match(r"^(──\s+)(.*?)(\s+·\s+changed\s+)(─+)$", cur)
        if m_diff:
            return tokens + [
                ("class:secondary", m_diff.group(1)),
                ("class:accent bold", m_diff.group(2)),
                ("class:secondary", m_diff.group(3) + m_diff.group(4)),
            ]
        m_code = re.match(r"^(──\s+)(.*?)(\s+─+)$", cur)
        if m_code:
            return tokens + [
                ("class:secondary", m_code.group(1)),
                ("class:accent bold", m_code.group(2)),
                ("class:secondary", m_code.group(3)),
            ]
        return tokens + [("class:secondary", cur)]

    # Numbered skill/item list with emdash: "9. python-project-workflow — safety_level: ..."
    skill_num_match = re.match(r"^(\d+\.\s+)([^\s—–]+(?:[ \t]+[^\s—–]+)*)(\s+[—–]\s+.*)$", cur)
    if skill_num_match:
        tokens.append(("class:number", skill_num_match.group(1)))
        tokens.append(("class:header", skill_num_match.group(2)))
        tokens.append(("class:secondary", skill_num_match.group(3)))
        return tokens

    # Numbered list item with optional bullet: "1. Trigger: ...", "- 1. Trigger: ..."
    num_match = re.match(r"^((?:•|-|\*)\s+)?(\d+\.\s+)(.*?)$", cur)
    if num_match:
        bullet_part = num_match.group(1)
        num_part = num_match.group(2)
        rest_str = num_match.group(3)
        if bullet_part:
            tokens.append(("class:bullet", bullet_part))
        tokens.append(("class:number", num_part))
        cur = rest_str
    else:
        # Diff lines with line numbers: "+ 3   text", "- 3   text"
        diff_num_add = re.match(r"^(\+\s*)(\d+\s+)(.*)$", cur)
        diff_num_del = re.match(r"^(-+\s*)(\d+\s+)(.*)$", cur)
        if diff_num_add:
            tokens.append(("class:add", diff_num_add.group(1)))
            tokens.append(("class:secondary", diff_num_add.group(2)))
            tokens.append(("class:add", diff_num_add.group(3)))
            return tokens
        elif diff_num_del:
            tokens.append(("class:del", diff_num_del.group(1)))
            tokens.append(("class:secondary", diff_num_del.group(2)))
            tokens.append(("class:del", diff_num_del.group(3)))
            return tokens

        if cur.startswith("+ "):
            tokens.append(("class:add", "+ "))
            cur = cur[2:]
            tokens.append(("class:add", cur))
            return tokens
        elif cur.startswith("- ") and (
            re.match(r"^-\s+(?:[a-zA-Z0-9_]+\s*=|return\s|const\s|let\s|var\s|import\s|def\s|function\s|class\s|if\s|else\s|for\s|while\s|self\.)", cur)
            or re.match(r"^-\s+[a-zA-Z0-9_]+\s*\(", cur)
        ):
            tokens.append(("class:del", "- "))
            cur = cur[2:]
            tokens.append(("class:del", cur))
            return tokens
        elif cur.startswith("• ") or cur.startswith("* ") or cur.startswith("- "):
            bullet_match = re.match(r"^(•|\*|-)\s+", cur)
            if bullet_match:
                tokens.append(("class:bullet", bullet_match.group(0)))
                cur = cur[bullet_match.end():]

    # Lead-in label before colon: "Trigger:", "Hur hund går tillväga:", "Ansvar:", "**Arbetsflöde:**"
    # Guard: not URL, not Python def/class, not timestamp (10:30)
    if not cur.startswith("http:") and not cur.startswith("https:") and not cur.startswith("def ") and not re.match(r"^\d{1,2}:\d{2}", cur):
        label_match = re.match(
            r"^(\*\*[^*]+\*\*|\b[A-Za-zåäöÅÄÖ0-9_-]+(?:\s+[A-Za-zåäöÅÄÖ0-9_-]+){0,3}\s*:)\s*",
            cur,
        )
        if label_match:
            raw_label = label_match.group(1)
            display_label = raw_label[2:-2] if (raw_label.startswith("**") and raw_label.endswith("**")) else raw_label
            tokens.append(("class:label", display_label))
            cur = cur[len(raw_label):]
            if cur.startswith(" "):
                tokens.append(("class:primary", " "))
                cur = cur[1:]

    # Inline markdown parsing: code, bold, arrows, dashes
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|->|→|—|–)")
    pos = 0
    for m in pattern.finditer(cur):
        if m.start() > pos:
            tokens.append(("class:primary", cur[pos : m.start()]))
        val = m.group(0)
        if val.startswith("**") and val.endswith("**"):
            tokens.append(("class:label", val[2:-2]))
        elif val.startswith("`") and val.endswith("`"):
            tokens.append(("class:code", val[1:-1]))
        elif val in ("->", "→", "—", "–"):
            tokens.append(("class:secondary", val))
        else:
            tokens.append(("class:primary", val))
        pos = m.end()

    if pos < len(cur):
        tokens.append(("class:primary", cur[pos:]))

    return tokens


_MODAL_ACTIVE: list[bool] = [False]


def _lex_pygments_code(cur: str, indent_str: str, lang: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    if indent_str:
        tokens.append(("", indent_str))
    try:
        from pygments.lexers import get_lexer_by_name, TextLexer
        lexer = get_lexer_by_name(lang)
    except Exception:
        from pygments.lexers import TextLexer
        lexer = TextLexer()

    try:
        import pygments
        from prompt_toolkit.styles.pygments import pygments_token_to_classname

        for tok_type, val in pygments.lex(cur, lexer):
            if val.endswith("\n") and not cur.endswith("\n"):
                val = val[:-1]
            if not val:
                continue
            cls = "class:pygments." + pygments_token_to_classname(tok_type)
            tokens.append((cls, val))
        return tokens
    except Exception:
        return [("", indent_str), ("class:primary", cur)] if indent_str else [("class:primary", cur)]


def _lex_stat_or_skill_part(part: str) -> list[tuple[str, str]]:
    # Style semantic spans independently. A narrow resize may truncate the
    # percentage or part of the bar; complete-row regexes would then recolor
    # the entire line. Independent spans keep the same colours at every width.
    spans: list[tuple[int, int, str]] = []
    stat = re.search(r"\b(CLR|PRC|EFF|END|MAS)\b", part)
    if stat:
        spans.append((stat.start(), stat.end(), "class:accent bold"))
    bar = re.search(r"[█░]+", part)
    if bar:
        spans.append((bar.start(), bar.end(), "class:learning"))
    percent = re.search(r"\d+%", part)
    if percent:
        spans.append((percent.start(), percent.end(), "class:secondary"))
    if not spans:
        return [("class:primary", part)]

    tokens: list[tuple[str, str]] = []
    cursor = 0
    for start, end, style in sorted(spans):
        if start > cursor:
            tokens.append(("class:primary", part[cursor:start]))
        tokens.append((style, part[start:end]))
        cursor = end
    if cursor < len(part):
        tokens.append(("class:primary", part[cursor:]))
    return tokens


_SCREEN_TOKEN_RE = re.compile(
    r"(?P<section>──[^│]+?─{2,})|"
    r"(?P<stat>\b(?:CLR|PRC|EFF|END|MAS)\b)|"
    r"(?P<filled>█+|[▒▓]+)|(?P<empty>░+|□+)|"
    r"(?P<percent>\b\d+%)|(?P<select>❯)|"
    r"(?P<good>\[(?:Key OK|Ready)\])|"
    r"(?P<bad>\[(?:Key missing|Unavailable)\])|"
    r"(?P<label>\b(?:Domain|Lifecycle|XP|Safety level|Triggers|Tools|Provenance|"
    r"Category|Context mode|Dispatch|Prompt|Output|Requests|Active):)|"
    r"(?P<meta_label>\b(?:OS|HOST|CPU|RAM|GPU|MODEL)\b)"
)


def _semantic_screen_fragments(text: str) -> list[tuple[str, str]]:
    """Style generated screen text without letting styles own its geometry."""
    fragments: list[tuple[str, str]] = []
    lines = text.splitlines(keepends=True)
    for raw in lines:
        newline = "\n" if raw.endswith("\n") else ""
        line = raw[:-1] if newline else raw
        if line and line[0] in "╔╚╭╰+-" and line[-1:] in "╗╝╮╯+":
            fragments.append(("class:accent", line))
        else:
            left = line[:1] if line[:1] in "║│|" else ""
            right = line[-1:] if line[-1:] in "║│|" else ""
            content = line[len(left): len(line) - len(right) if right else None]
            if left:
                fragments.append(("class:accent", left))
            if content.lstrip().startswith(("[Esc]", "↑", "Less  ")):
                fragments.append(("class:secondary", content))
            elif "[■ ■ ■ ■ ■]" in content and any(
                name in content for name in theme.theme_names()
            ):
                start = content.index("[")
                end = content.index("]", start) + 1
                name = next(name for name in theme.theme_names() if name in content)
                tokens = theme.get_skin(name)["tokens"]
                fragments.append(("class:primary", content[:start] + "["))
                colors = ("primary", "accent", "user", "learning", "tool")
                for index, color in enumerate(colors):
                    if index:
                        fragments.append(("class:primary", " "))
                    fragments.append((f"fg:{tokens[color]}", "■"))
                fragments.append(("class:primary", "]" + content[end:]))
            else:
                cursor = 0
                for match in _SCREEN_TOKEN_RE.finditer(content):
                    if match.start() > cursor:
                        fragments.append(("class:primary", content[cursor:match.start()]))
                    group = match.lastgroup
                    style = {
                        "section": "class:header",
                        "stat": "class:accent bold",
                        "filled": "class:learning",
                        "empty": "class:secondary",
                        "percent": "class:secondary",
                        "select": "class:user bold",
                        "good": "class:success",
                        "bad": "class:danger",
                        "label": "class:meta_accent",
                        "meta_label": "class:meta_accent",
                    }[group]
                    fragments.append((style, match.group(0)))
                    cursor = match.end()
                if cursor < len(content):
                    fragments.append(("class:primary", content[cursor:]))
            if right:
                fragments.append(("class:accent", right))
        if newline:
            fragments.append(("", newline))
    return fragments


def _lex_banner_line(line: str) -> list[tuple[str, str]]:
    if line.startswith("╔") and line.endswith("╗"):
        if "▄▄" in line:
            idx_start = line.find("▄▄")
            idx_end = line.rfind("▄▄") + 2
            return [
                ("class:accent", line[:idx_start]),
                ("class:logo", line[idx_start:idx_end]),
                ("class:accent", line[idx_end:]),
            ]
        return [("class:accent", line)]
    if line.startswith("╚") and line.endswith("╝"):
        return [("class:accent", line)]
    if not (line.startswith("║") and line.endswith("║")):
        return [("class:primary", line)]

    content = line[1:-1]
    tokens: list[tuple[str, str]] = [("class:accent", "║")]

    if any(
        c in content
        for c in (
            "▄▄",
            "██                   ██",
            "████▄",
            "██ ██ ██ ██",
            "▀██▀█",
            "▀████",
        )
    ):
        tokens.append(("class:logo", content))
    elif "commands:" in content:
        tokens.append(("class:secondary", content))
    elif "HUND AI" in content:
        idx = content.find("HUND AI")
        leading = content[:idx]
        if leading:
            tokens.append(("", leading))
        tokens.append(("class:accent bold", "HUND AI"))
        tokens.append(("class:secondary", content[idx + 7 :]))
    elif re.match(r"^\s*(OS|HOST|CPU|RAM|GPU|MODEL)\s+", content):
        m = re.match(r"^(\s*)(OS|HOST|CPU|RAM|GPU|MODEL)(\s+)(.*)$", content)
        if m:
            if m.group(1):
                tokens.append(("", m.group(1)))
            tokens.append(("class:meta_accent", m.group(2)))
            if m.group(3):
                tokens.append(("", m.group(3)))
            if m.group(4):
                tokens.append(("class:primary", m.group(4)))
    elif any(k in content for k in ("── BASE STATS", "── BASE ATTRIBUTES", "── SPECIALIZATIONS", "── SKILLS")):
        if "│" in content:
            left, right = content.split("│", 1)
            tokens.append(("class:header", left))
            tokens.append(("class:secondary", "│"))
            tokens.append(("class:header", right))
        else:
            tokens.append(("class:header", content))
    elif "│" in content:
        left, right = content.split("│", 1)
        tokens.extend(_lex_stat_or_skill_part(left))
        tokens.append(("class:secondary", "│"))
        tokens.extend(_lex_stat_or_skill_part(right))
    else:
        # Compact (stacked) banner rows still carry the same semantic colours
        # as their two-column counterparts.
        tokens.extend(_lex_stat_or_skill_part(content))

    tokens.append(("class:accent", "║"))
    return tokens


class _OutputLexer(Lexer):
    """Line-prefix & semantic markdown lexer mapping output lines to rich token styles."""

    def invalidation_hash(self) -> bool:
        return _MODAL_ACTIVE[0]

    def lex_document(self, document):
        lines = document.lines

        if _MODAL_ACTIVE[0]:
            def get_dim_line(lineno: int):
                try:
                    line = lines[lineno]
                except IndexError:
                    return []
                return [("class:backdrop", line)]

            return get_dim_line

        # Pre-scan for code blocks, their languages, and multiline user messages
        code_langs: dict[int, str] = {}
        user_lines: set[int] = set()
        in_code = False
        in_user = False
        cur_lang = "python"
        for i, raw_line in enumerate(lines):
            line_content = raw_line
            stripped_l = line_content.strip()
            if stripped_l.startswith("❯"):
                in_user = True
                user_lines.add(i)
            elif in_user:
                if (
                    not stripped_l
                    or stripped_l.startswith("┊")
                    or stripped_l.startswith("·")
                    or stripped_l.startswith("┌─ hund")
                    or stripped_l.startswith("╭─ hund")
                    or stripped_l.startswith("╔")
                ):
                    in_user = False
                else:
                    user_lines.add(i)

            if line_content.startswith("── ") and not line_content.endswith("· changed ──"):
                parts = line_content.strip("─ ").split()
                if parts:
                    fn_or_lang = parts[0]
                    if "." in fn_or_lang:
                        ext = fn_or_lang.rsplit(".", 1)[-1].lower()
                        lang_map = {
                            "py": "python", "ts": "typescript", "js": "javascript",
                            "json": "json", "rs": "rust", "go": "go", "md": "markdown",
                            "sh": "bash", "html": "html", "css": "css", "yaml": "yaml",
                            "yml": "yaml", "toml": "toml", "sql": "sql",
                        }
                        cur_lang = lang_map.get(ext, "python")
                    else:
                        cur_lang = fn_or_lang.lower()
                in_code = True
            elif in_code and (not line_content.strip("─ ") or line_content.startswith("──")):
                in_code = False
            elif in_code:
                code_langs[i] = cur_lang

        def get_line(lineno: int):
            try:
                line = lines[lineno]
            except IndexError:
                return []
            if line.startswith("╔") or line.startswith("║") or line.startswith("╚"):
                return _lex_banner_line(line)
            if lineno in user_lines:
                return [("class:user", line)]
            stripped = line.lstrip()
            if not stripped:
                return [("class:primary", line)]
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
                    tokens.append(("class:tool", "⟳"))
                    rest = rest[1:]
                elif rest.startswith("✓"):
                    tokens.append(("class:success", "✓"))
                    rest = rest[1:]
                elif rest.startswith("✗") or rest.startswith("⊘"):
                    tokens.append(("class:danger", rest[0]))
                    rest = rest[1:]
                
                # Split metadata suffix (e.g. " · 0.6s", "  0.3s", " 4 files · 0.6s")
                if " · " in rest:
                    main_part, meta_part = rest.rsplit(" · ", 1)
                    tokens.append(("class:primary", main_part))
                    tokens.append(("class:secondary", " · " + meta_part))
                else:
                    tokens.append(("class:primary", rest))
                return tokens
            elif line.startswith("  ╰─ ") or (line.startswith("╰─ ") and not line.endswith("╯")):
                idx = line.find("╰─")
                leading = line[:idx]
                tokens = [("", leading)] if leading else []
                tokens.append(("class:secondary", "╰─"))
                rest = line[idx + 2 :]
                style = "class:danger" if "stopped" in rest else "class:success"
                if " · " in rest:
                    main_part, meta_part = rest.rsplit(" · ", 1)
                    tokens.append((style, main_part))
                    tokens.append(("class:secondary", " · " + meta_part))
                else:
                    tokens.append((style, rest))
                return tokens
            elif line.startswith("  · ") or stripped.startswith("· "):
                rest = line[4:] if line.startswith("  · ") else stripped[2:]
                tokens: list[tuple[str, str]] = [("class:secondary", "  "), ("class:learning", "· ")]
                if "⟶ level up!" in rest:
                    before, after = rest.split("⟶ level up!", 1)
                    if before:
                        tokens.append(("class:learning", before))
                    tokens.append(("class:accent bold", "⟶ level up!"))
                    if after:
                        tokens.append(("class:accent", after))
                    return tokens
                bar_match = re.search(r"^(.*?)([█░]+)(\s+\+\d+\s+XP|\s*\+\d+\s+XP)?(.*)$", rest)
                if bar_match:
                    prefix_text, bar_text, xp_text, suffix_text = bar_match.groups()
                    if prefix_text:
                        tokens.append(("class:learning", prefix_text))
                    tokens.append(("class:learning", bar_text))
                    if xp_text:
                        tokens.append(("class:learning bold", xp_text))
                    if suffix_text:
                        tokens.append(("class:learning", suffix_text))
                    return tokens
                tokens.append(("class:learning", rest))
                return tokens
            elif (
                stripped.startswith("hund is ")
                or stripped.startswith("hund was ")
                or (stripped.startswith("hund ") and (stripped.endswith("…") or stripped.endswith("...")))
            ):
                return [("class:thinking", line)]
            elif stripped.startswith("hund ") and stripped.endswith("."):
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
            elif line.startswith("┌─ hund ") or line.startswith("╭─ hund "):
                idx = line.find("hund")
                return [
                    ("class:secondary", line[:idx]),
                    ("class:accent bold", "hund"),
                    ("class:secondary", line[idx + 4 :]),
                ]
            elif line.startswith("└") or line.startswith("╰"):
                meta_match = re.search(
                    r"^(.*?─\s+)([0-9.]+(?:s|ms|m|h)?|\w+)(\s+─+[┘╯]|─+[┘╯]|[┘╯])$",
                    line,
                )
                if meta_match:
                    return [
                        ("class:secondary", meta_match.group(1)),
                        ("class:accent bold", meta_match.group(2)),
                        ("class:secondary", meta_match.group(3)),
                    ]
                return [("class:secondary", line)]
            elif line.startswith("│") and line.endswith("│") and not line.strip("│ "):
                return [("class:secondary", line)]
            elif line.startswith("│  ") and line.endswith("  │") and len(line) >= 6:
                content = line[3:-3]
                indent_len = len(content) - len(content.lstrip())
                indent_str = content[:indent_len]
                cur = content.lstrip()
                if lineno in code_langs and not (
                    cur.startswith("──")
                    or cur.startswith("+ ")
                    or cur.startswith("- ")
                    or re.match(r"^[+-]\s*\d+\s+", cur)
                ):
                    parsed = _lex_pygments_code(cur, indent_str, code_langs[lineno])
                else:
                    parsed = _parse_semantic_line(cur, indent_str)
                diff = len(content) - sum(len(t[1]) for t in parsed)
                fill = [("class:primary", " " * diff)] if diff > 0 else []
                return [("class:secondary", "│  ")] + parsed + fill + [("class:secondary", "  │")]
            elif line.startswith("│ ") and line.endswith(" │") and len(line) >= 4:
                content = line[2:-2]
                indent_len = len(content) - len(content.lstrip())
                indent_str = content[:indent_len]
                cur = content.lstrip()
                if lineno in code_langs and not (
                    cur.startswith("──")
                    or cur.startswith("+ ")
                    or cur.startswith("- ")
                    or re.match(r"^[+-]\s*\d+\s+", cur)
                ):
                    parsed = _lex_pygments_code(cur, indent_str, code_langs[lineno])
                else:
                    parsed = _parse_semantic_line(cur, indent_str)
                diff = len(content) - sum(len(t[1]) for t in parsed)
                fill = [("class:primary", " " * diff)] if diff > 0 else []
                return [("class:secondary", "│ ")] + parsed + fill + [("class:secondary", " │")]
            elif line.startswith("│") and line.endswith("│") and len(line) >= 2:
                content = line[1:-1]
                indent_len = len(content) - len(content.lstrip())
                indent_str = content[:indent_len]
                cur = content.lstrip()
                parsed = _parse_semantic_line(cur, indent_str)
                diff = len(content) - sum(len(t[1]) for t in parsed)
                fill = [("class:primary", " " * diff)] if diff > 0 else []
                return [("class:secondary", "│")] + parsed + fill + [("class:secondary", "│")]
            elif stripped.startswith("#"):
                return [("class:header", line)]

            indent_len = len(line) - len(stripped)
            indent_str = line[:indent_len]
            return _parse_semantic_line(stripped, indent_str)

        return get_line


class _SelectableControl(BufferControl):
    """Output control: wheel scroll via the view-scroll callback, and
    single-drag selection (focus on mouse-down instead of mouse-up)."""

    def __init__(self, *args, scroll_cb=None, fallback_focus=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.scroll_cb = scroll_cb
        self.fallback_focus = fallback_focus

    def create_content(self, width: int, height: int | None) -> Any:
        content = super().create_content(width, height)
        # Prevent horizontal scrolling off-screen by pinning cursor x=0 when not actively selecting
        if self.buffer.selection_state is None:
            orig_cursor = content.cursor_position
            if orig_cursor is not None:
                content.cursor_position = Point(x=0, y=orig_cursor.y)
        return content

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

_CONFIRM_COLORS = {
    ConfirmVerdict.APPROVE_ONCE: "class:success",
    ConfirmVerdict.EDIT: "class:accent",
    ConfirmVerdict.ALLOW_SESSION: "class:warning",
    ConfirmVerdict.DENY: "class:danger",
}


def _confirm_options(tool_name: str):
    return [(v, label, _CONFIRM_COLORS[v]) for v, label in confirmation_options(tool_name)]


def _discard_console(width: int = 100) -> Console:
    """Rich console that discards output (agent turn only talks through the sink)."""
    return Console(file=io.StringIO(), color_system=None, force_terminal=False, width=width)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


async def run_fullscreen(rt, state, *, banner: str, session_id: str) -> int:
    """Run the full-screen REPL application. Returns exit code."""
    screens = ScreenController()
    screen_snapshots: dict[str, Any] = {}
    modal_input = [""]
    model_options: list[Any] = []

    # ---- output buffer (read-only + focusable so the mouse can select) ----
    output_buffer = Buffer(name="output", multiline=True, read_only=True)
    output_control = _SelectableControl(buffer=output_buffer, lexer=_OUTPUT_LEXER)
    output_window = Window(
        content=output_control,
        wrap_lines=False,
        always_hide_cursor=True,
        dont_extend_height=False,
        height=Dimension(weight=1),
    )

    # ---- input buffer + prompt ----
    completer = SlashCommandCompleter(rt.workspace)
    input_buffer = Buffer(
        name="input", multiline=True, completer=completer, complete_while_typing=True,
    )

    def _input_height() -> int:
        text = input_buffer.text
        if not text:
            return 1
        # Usable width for text inside input row (terminal width minus prompt width '❯ ')
        w = max(_app_width() - 4, 15)
        lines = text.split("\n")
        total_rows = 0
        for l in lines:
            if not l:
                total_rows += 1
            else:
                total_rows += max(1, (len(l) + w - 1) // w)
        return min(max(total_rows, 1), 10)

    input_control = BufferControl(buffer=input_buffer, focus_on_click=True)
    input_window = Window(
        content=input_control,
        height=_input_height,
        dont_extend_height=False,
        wrap_lines=True,
    )
    prompt_window = Window(
        content=FormattedTextControl(lambda: [("class:prompt", "  ❯ ")]),
        width=4,
        dont_extend_width=True,
        height=_input_height,
        dont_extend_height=False,
    )
    input_row = VSplit([prompt_window, input_window])
    completion_container = _FullWidthCompletionsMenu(
        max_height=MAX_VISIBLE_COMPLETIONS
    )

    output_control.fallback_focus = input_window

    # ---- status bar ----
    turn_running = [False]

    def status_text() -> list[tuple[str, str]]:
        model = state.extra.get("model", "deepseek-v4-pro")
        tokens = state.extra.get("tokens", 0)
        limit = state.extra.get("token_limit", 1_000_000)
        dur = time.time() - state.start_time
        lat = state.extra.get("last_latency_s", 0.0) if turn_running[0] else None

        cleaned_model = model
        if "(" in model and ")" in model:
            cleaned_model = model.split("(")[-1].split(")")[0].strip()
        if not cleaned_model:
            cleaned_model = "deepseek-v4-pro"

        token_str = format_tokens_ratio(tokens, limit)
        duration_str = format_duration(dur)

        segments: list[tuple[str, str]] = [
            ("class:header", "  " + cleaned_model),
            ("class:status", f" │ {token_str} │ {duration_str}"),
        ]
        if lat is not None and lat > 0:
            segments.append(("class:status", f" │ {lat:.1f}s"))
        return segments

    status_window = Window(content=FormattedTextControl(status_text), height=1)

    mascot_machine = MascotMachine()

    def _mascot_text() -> list[tuple[str, str]]:
        tint, art = mascot_machine.frame(getattr(state, "theme_name", "marshmallow"))
        # Sprite sheets contain a shared blank top row. Dropping only that row
        # reduces the chat/mascot boundary while preserving the feet baseline.
        lines = [f"  {ln}" if ln else "" for ln in art.removeprefix("\n").splitlines()]
        return [(f"class:mascot fg:{tint}", "\n".join(lines))]

    mascot_window = Window(
        content=_ScrollThroughFormattedTextControl(
            _mascot_text, scroll_cb_getter=lambda: output_control.scroll_cb
        ),
        width=18,
        height=7,
        dont_extend_width=True,
        dont_extend_height=True,
        wrap_lines=False,
    )

    def _mascot_status_text() -> list[tuple[str, str]]:
        if not turn_running[0]:
            return []
        skin = theme.get_skin(getattr(state, "theme_name", "marshmallow"))
        color = skin["tokens"].get("mascot_status", skin["tokens"]["secondary"])
        dot_count = (
            3 if getattr(rt.cfg, "reduced_motion", False)
            else int(time.monotonic() / 0.32) % 3 + 1
        )
        dots = ("." * dot_count).ljust(3)
        phase = int(time.monotonic() / 0.10)
        return [("", "\n" * 6)] + _shine_fragments(f" running{dots}", color, phase)

    mascot_status_window = Window(
        content=_ScrollThroughFormattedTextControl(
            _mascot_status_text, scroll_cb_getter=lambda: output_control.scroll_cb
        ),
        height=7,
        dont_extend_height=True,
    )
    mascot_row = VSplit([mascot_window, mascot_status_window], height=7)
    mascot_container = ConditionalContainer(
        mascot_row,
        filter=Condition(lambda: _app_height() >= 27),
    )

    # ---- confirmation modal (arrow-key select) ----
    _confirm = {
        "active": False,
        "title": "hund wants to run a command",
        "detail": "",
        "selected": 0,
        "answer": ConfirmVerdict.DENY,
        "options": _confirm_options("terminal"),
        "event": threading.Event(),
    }

    def _confirm_text():
        if not _confirm["active"]:
            return []
        W = min(68, max(_content_width() - 4, 36))
        out: list[tuple[str, str]] = []

        def row(content: str, style: str = "class:primary") -> None:
            out.append(("class:secondary", "│ "))
            out.append((style, content))
            out.append(("class:secondary", " " * max(W - 4 - len(content), 0) + " │\n"))

        title = _confirm.get("title", "hund wants to run a command")
        title_dashes = max(W - len(title) - 5, 2)
        out.append(("class:secondary", "╭─ "))
        out.append(("class:warning bold", title))
        out.append(("class:secondary", " " + "─" * title_dashes + "╮\n"))

        row("", "class:secondary")
        detail = _confirm.get("detail", "")
        row(f"  {detail}", "class:accent")
        row("", "class:secondary")
        for i, (_code, label, color) in enumerate(_confirm["options"]):
            if i == _confirm["selected"]:
                row("  ❯ ● " + label, color + " bold")
            else:
                row("    ○ " + label, "class:secondary")
        row("", "class:secondary")
        out.append(("class:secondary", "╰" + "─" * (W - 2) + "╯\n"))
        out.append(("class:secondary", "   ↑↓ select · Enter confirm · Esc deny"))
        return out

    _thinking: dict[str, Any] = {
        "active": False,
        "text": "hund is reading",
        "past": None,
        "start_time": 0.0,
    }

    confirm_window = Window(content=FormattedTextControl(_confirm_text), height=12)
    confirm_container = ConditionalContainer(
        confirm_window, filter=Condition(lambda: _confirm["active"])
    )

    from ..providers.catalog import MODEL_OPTIONS, active_option

    model_options.extend(MODEL_OPTIONS)
    try:
        configured_option = active_option(rt.cfg)
        if not any(
            item.model_id == configured_option.model_id
            and item.base_url == configured_option.base_url
            for item in model_options
        ):
            model_options.insert(0, configured_option)
    except Exception:
        pass

    def _screen_text() -> str:
        destination = screens.destination
        width, height = _app_width(), _app_height()
        key = destination.value
        snapshot = screen_snapshots.get(key)
        if snapshot is None:
            message = "Loading..." if key in screens.loading else (
                screens.status or f"Could not load {key}."
            )
            return fullscreen_frame(
                destination.value.upper(), ["", message],
                width=width, height=height, scroll=0,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if destination is DestinationView.STATS:
            return render_stats(
                snapshot, width=width, height=height,
                scroll=screens.scroll.get(key, 0),
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if destination is DestinationView.SKILLS:
            return render_skills(
                snapshot, width=width, height=height,
                selected=screens.selected.get(key, 0),
                scroll=screens.scroll.get(key, 0),
                detail_name=screens.detail.get(key),
                status=screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if destination is DestinationView.TOOLS:
            return render_tools(
                snapshot, width=width, height=height,
                selected=screens.selected.get(key, 0),
                scroll=screens.scroll.get(key, 0),
                detail_name=screens.detail.get(key),
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if destination is DestinationView.USAGE:
            return render_usage(
                snapshot, width=width, height=height,
                scroll=screens.scroll.get(key, 0),
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        return ""

    def _overlay_text() -> str:
        overlay = screens.overlay
        width = _app_width()
        if overlay is OverlayView.THEME:
            return render_theme_modal(
                getattr(state, "theme_name", "marshmallow"),
                screens.selected.get("theme", 0),
                width,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.MODEL:
            local_engine = getattr(getattr(rt, "client", None), "_engine", None)
            local_ready = bool(
                local_engine is not None
                and local_engine.model_path is not None
                and local_engine.is_running
            )
            return render_model_modal(
                model_options,
                rt.cfg.provider.model,
                screens.selected.get("model", 0),
                width,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
                local_ready=local_ready,
            )
        if overlay is OverlayView.MODEL_CUSTOM:
            return render_model_custom_modal(
                modal_input[0], width, screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.MODEL_KEY:
            selected = screens.selected.get("model", 0)
            option = model_options[selected] if model_options else active_option(rt.cfg)
            return render_model_key_modal(
                option.provider_name, "•" * len(modal_input[0]), width, screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        return ""

    screen_window = Window(
        content=FormattedTextControl(lambda: _semantic_screen_fragments(_screen_text())),
        wrap_lines=False,
    )
    screen_container = ConditionalContainer(
        screen_window,
        filter=Condition(lambda: screens.destination is not DestinationView.CHAT),
    )
    overlay_window = Window(
        content=FormattedTextControl(lambda: _semantic_screen_fragments(_overlay_text())),
        wrap_lines=False,
    )
    overlay_container = ConditionalContainer(
        overlay_window,
        filter=Condition(
            lambda: screens.overlay
            in {
                OverlayView.THEME,
                OverlayView.MODEL,
                OverlayView.MODEL_CUSTOM,
                OverlayView.MODEL_KEY,
            }
        ),
    )

    # 1-row border lines above and below input per TUI_FACIT.md §5.1
    input_border_top = Window(
        content=FormattedTextControl(lambda: [("class:secondary", "─" * _app_width())]),
        height=1,
        dont_extend_height=True,
        wrap_lines=False,
    )
    input_border_bottom = Window(
        content=FormattedTextControl(lambda: [("class:secondary", "─" * _app_width())]),
        height=1,
        dont_extend_height=True,
        wrap_lines=False,
    )

    layout = Layout(
        FloatContainer(
            content=HSplit([
                output_window,
                mascot_container,
                input_border_top,
                input_row,
                completion_container,
                input_border_bottom,
                status_window,
            ]),
            floats=[
                Float(content=screen_container, left=0, right=0, top=0, bottom=0),
                Float(content=overlay_container),
                Float(
                    content=confirm_container,
                ),
            ],
        ),
        focused_element=input_window,
    )

    # ---- shared mutable state ----
    holder: dict[str, Any] = {}

    def _invalidate() -> None:
        _MODAL_ACTIVE[0] = bool(_confirm.get("active")) or (
            screens.overlay is not OverlayView.NONE
        )
        app = holder.get("app")
        if app is not None:
            try:
                # Always reset horizontal scroll so the left border (│) is never
                # clipped off-screen – it can drift > 0 after text selection in a
                # long message and prompt_toolkit won't auto-reset it.
                output_window.horizontal_scroll = 0
                app.invalidate()
            except Exception:
                pass

    def _app_width() -> int:
        app = holder.get("app")
        if app is not None:
            try:
                cols = app.output.get_size().columns
                if cols > 0:
                    return cols
            except Exception:
                pass
        return _term_width()

    def _content_width() -> int:
        return _responsive_content_width(_app_width())

    def _app_height() -> int:
        app = holder.get("app")
        if app is not None:
            try:
                rows = app.output.get_size().rows
                if rows > 0:
                    return rows
            except Exception:
                pass
        try:
            return shutil.get_terminal_size((80, 24)).lines
        except Exception:
            return 24

    def _box_top(width: int | None = None) -> str:
        return _r_box_top(width if width is not None else _content_width())

    def _box_bottom(meta: str | None = None, width: int | None = None) -> str:
        return _r_box_bottom(width if width is not None else _content_width(), meta=meta)

    _append_lock = threading.Lock()
    tail_following = [False]
    response_payloads: list[tuple[str, str | None]] = []
    active_response: list[tuple[str, str | None] | None] = [None]

    def _set_output(new_text: str, *, follow_tail: bool = True) -> None:
        """Set output text with deterministic top or tail viewport anchoring."""
        tail_following[0] = follow_tail
        cur_pos = _output_cursor_position(new_text, follow_tail=follow_tail)
        try:
            output_window.horizontal_scroll = 0
        except Exception:
            pass
        output_buffer.set_document(
            Document(new_text, cursor_position=cur_pos), bypass_readonly=True
        )

    def append(text: str) -> None:
        if not text:
            return
        with _append_lock:
            new_text = output_buffer.text + text
            _set_output(new_text)
        _invalidate()

    # seed banner
    from .render import build_startup_banner
    def _banner_width() -> int:
        return _content_width()

    actual_width = _banner_width()
    rendered_banner = build_startup_banner(rt, width=actual_width)
    seed = rendered_banner.rstrip("\n") + "\n\n"
    _set_output(seed, follow_tail=False)

    def _reflow_borders() -> None:
        """Re-width response box borders and re-wrap content to the current terminal width."""
        with _append_lock:
            text = output_buffer.text
            lines = text.split("\n")
            new_lines: list[str] = []
            changed = False
            in_box = False
            in_panel = False
            box_lines: list[str] = []
            panel_lines: list[str] = []
            response_index = 0

            for line in lines:
                if line.startswith("╔") and line.endswith("╗"):
                    in_panel = True
                    panel_lines = [line]
                elif in_panel and (line.startswith("╚") and line.endswith("╝")):
                    in_panel = False
                    panel_lines.append(line)
                    panel_text = "\n".join(panel_lines)
                    app_w = _banner_width()

                    if "── MOTOR SKILLS" in panel_text or "── DOMAIN SKILLS" in panel_text:
                        from .skills_view import render_skills_panel
                        new_panel = render_skills_panel(rt, width=app_w)
                        new_lines.extend(new_panel.split("\n"))
                        changed = True
                    elif "SKILL DETAIL:" in panel_text:
                        from .skills_view import render_skill_detail
                        # Extract skill name from detail line
                        sk_name = ""
                        for pl in panel_lines:
                            if "SKILL DETAIL:" in pl:
                                sk_name = pl.split("SKILL DETAIL:")[-1].strip(" ║│═").strip()
                                break
                        if sk_name:
                            new_panel = render_skill_detail(sk_name, rt, width=app_w)
                            new_lines.extend(new_panel.split("\n"))
                            changed = True
                        else:
                            new_lines.extend(panel_lines)
                    elif "OS      " in panel_text or "── BASE ATTRIBUTES ──" in panel_text or "HUND AI" in panel_text:
                        new_banner = build_startup_banner(rt, width=app_w)
                        new_lines.extend(new_banner.split("\n"))
                        changed = True
                    else:
                        new_lines.extend(panel_lines)
                elif in_panel:
                    panel_lines.append(line)
                elif line.startswith("┌─ hund ") or line.startswith("╭─ hund "):
                    in_box = True
                    box_lines = []
                elif in_box and (line.startswith("└") or line.startswith("╰")):
                    in_box = False
                    # Extract meta if present (e.g. └────── 2.3s ───┘ or └────── 2.3s ┘)
                    box_meta: str | None = None
                    trimmed = line.lstrip("└╰─ ").rstrip(" ┘╯─")
                    if trimmed:
                        box_meta = trimmed.strip()

                    # Padding is structural: render_response_box() always emits
                    # exactly one row before and after the payload. Blank rows
                    # inside the payload are semantic content.
                    content_lines: list[str] = []
                    payload_lines = box_lines[1:-1] if len(box_lines) >= 2 else box_lines
                    for bl in payload_lines:
                        if bl.startswith("│  ") and bl.endswith("  │"):
                            content_lines.append(bl[3:-3].rstrip())
                        elif bl.startswith("│ ") and bl.endswith(" │"):
                            content_lines.append(bl[2:-2].rstrip())
                        elif bl.startswith("│") and bl.endswith("│"):
                            content_lines.append(bl[1:-1].rstrip())
                        else:
                            content_lines.append(bl.rstrip())
                    saved = (
                        response_payloads[response_index]
                        if response_index < len(response_payloads)
                        else active_response[0]
                    )
                    raw_content = saved[0] if saved is not None else "\n".join(content_lines)
                    if saved is not None and saved[1] is not None:
                        box_meta = saved[1]
                    re_boxed = render_response_box(raw_content, _content_width(), meta=box_meta)
                    new_lines.extend(re_boxed.split("\n"))
                    response_index += 1
                    changed = True
                elif in_box:
                    box_lines.append(line)
                else:
                    new_lines.append(line)

            if changed:
                new_text = "\n".join(new_lines)
                _set_output(new_text, follow_tail=tail_following[0])
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
            self._activity = ActivityTimeline()
            self._activity_marker: int | None = None
            self._activity_prefix = ""
            self._active_tool_event_id: int | None = None
            self._tool_switched = False
            self._user_input = ""
            self._turn_start_time: float = 0.0
            self._pending_past_timer: threading.Timer | None = None
            self._md = StreamingMarkdownFilter()
            self._snapshot = None
            self._learning_markers: dict[str, int] = {}

        def set_user_input(self, text: str) -> None:
            self._user_input = text or ""
            self._tool_switched = False
            self._turn_start_time = time.time()
            self._activity.clear()
            self._activity_marker = None
            self._activity_prefix = ""
            self._active_tool_event_id = None

        def set_turn_snapshot(self, snapshot) -> None:
            self._snapshot = snapshot

        def _cancel_timers(self) -> None:
            if self._pending_past_timer is not None:
                try:
                    self._pending_past_timer.cancel()
                except Exception:
                    pass
                self._pending_past_timer = None

        def thinking(self, msg: str | None = None) -> None:
            if not self._turn_start_time:
                self._turn_start_time = time.time()
            self._cancel_timers()
            _thinking["active"] = True
            _thinking["text"] = msg.rstrip(".…") if msg else "hund is reading"
            _thinking["past"] = None
            _thinking["start_time"] = time.time()
            self._tool_switched = False
            _invalidate()

        def clear_thinking(self) -> None:
            self._cancel_timers()
            if _thinking["active"]:
                _thinking["active"] = False
                past = _thinking.get("past")
                start_time = _thinking.get("start_time", 0.0)
                _thinking["past"] = None
                _invalidate()

                if past and self._activity_marker is not None:
                    self._activity_prefix = f"  {past}\n"
                    self._render_activity()
                elif past:
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

        def _render_activity(self) -> None:
            """Replace the current turn's observed activity block in-place."""
            if self._activity_marker is None:
                return
            block = self._activity_prefix + self._activity.render()
            with _append_lock:
                current = output_buffer.text
                _set_output(current[: self._activity_marker] + block)
            _invalidate()

        def chunk(self, text: str) -> None:
            if not self._turn_start_time:
                self._turn_start_time = time.time()
            self.clear_thinking()
            filtered = self._md.feed(text)
            if not filtered:
                return
            if not self._box_open:
                self._box_open = True
                # Ensure a blank line separates preceding content from the box.
                with _append_lock:
                    cur = output_buffer.text
                    if cur and not cur.endswith("\n\n"):
                        extra = "\n" if cur.endswith("\n") else "\n\n"
                        _set_output(cur + extra)
                self._box_start_marker = len(output_buffer.text)
                self._raw_response = ""
            self._raw_response += filtered
            active_response[0] = (self._raw_response, None)
            boxed = render_response_box(self._raw_response, _content_width())
            with _append_lock:
                prefix = output_buffer.text[: self._box_start_marker]
                new_text = prefix + boxed
                _set_output(new_text)
            _invalidate()

        def end_assistant(self) -> None:
            dur = (time.time() - self._turn_start_time) if self._turn_start_time else state.extra.get("last_latency_s", 0.0)
            meta = f"{dur:.1f}s" if dur and dur > 0 else None
            if self._box_open:
                leftover = self._md.flush()
                self._raw_response += leftover
                boxed = render_response_box(self._raw_response, _content_width(), meta=meta)
                active_response[0] = (self._raw_response, meta)

                reflection_lines: list[str] = []
                if getattr(self, "_snapshot", None) is not None:
                    try:
                        from hund.learning.reflection import compute_reflections
                        reflection_lines = compute_reflections(self._snapshot)
                    except Exception:
                        pass
                    self._snapshot = None

                refl_text = ""
                if reflection_lines:
                    refl_text = "\n" + "\n".join(reflection_lines)

                with _append_lock:
                    prefix = output_buffer.text[: self._box_start_marker]
                    new_text = prefix + boxed + refl_text + "\n\n"
                    _set_output(new_text)

                if (
                    reflection_lines
                    and not input_buffer.text.strip()
                    and not getattr(rt.cfg, "reduced_motion", False)
                ):
                    has_bar = any("XP" in ln and ("█" in ln or "░" in ln) for ln in reflection_lines)
                    if has_bar:
                        def _animate_glint(base_prefix: str, base_boxed: str, final_refl: list[str]) -> None:
                            try:
                                for glint_char in ("▒", "█"):
                                    if input_buffer.text.strip():
                                        break
                                    time.sleep(0.06)
                                    shimmered = [
                                        ln.replace("█", glint_char, 3) if "XP" in ln else ln
                                        for ln in final_refl
                                    ]
                                    with _append_lock:
                                        _set_output(base_prefix + base_boxed + "\n" + "\n".join(shimmered) + "\n\n")
                                    _invalidate()
                                time.sleep(0.04)
                                with _append_lock:
                                    _set_output(base_prefix + base_boxed + "\n" + "\n".join(final_refl) + "\n\n")
                                _invalidate()
                            except Exception:
                                pass

                        threading.Thread(
                            target=_animate_glint,
                            args=(prefix, boxed, reflection_lines),
                            daemon=True,
                        ).start()

                self._box_open = False
                response_payloads.append((self._raw_response, meta))
                active_response[0] = None
                self._raw_response = ""
                self._turn_start_time = 0.0
                _invalidate()
            else:
                append("\n\n")
                self._turn_start_time = 0.0

        def learning_pending(self, job_id: str) -> None:
            line = "  · evaluating evidence...\n"
            with _append_lock:
                base = output_buffer.text.rstrip("\n") + "\n"
                self._learning_markers[job_id] = len(base)
                _set_output(base + line)
            _invalidate()

        def learning_receipt(self, receipt) -> None:
            from hund.learning.runtime import format_receipt_bundle

            marker = self._learning_markers.pop(receipt.job_id, None)
            pending = "  · evaluating evidence...\n"
            replacement = (
                "" if receipt.kind == "no_change"
                else "\n".join(format_receipt_bundle(receipt)) + "\n"
            )
            with _append_lock:
                current = output_buffer.text
                if marker is not None and current[marker:marker + len(pending)] == pending:
                    current = current[:marker] + replacement + current[marker + len(pending):]
                else:
                    current += replacement
                _set_output(current)
            _invalidate()

        def error(self, markup: str) -> None:
            clean = strip_rich(strip_markdown(markup)).strip()
            if self._active_tool_event_id is not None:
                self._activity.finish(
                    self._active_tool_event_id,
                    ActivityStatus.ERROR,
                    duration_s=time.time() - self._tool_start_time,
                    detail=_trunc(clean, 50),
                )
                self._active_tool_event_id = None
                self._render_activity()
            else:
                append(clean + "\n")

        def edit(self, request: ConfirmRequest) -> dict | None:
            return prompt_edits(request)

        def confirm(self, request: ConfirmRequest) -> ConfirmVerdict:
            title = _confirm_title(request)
            detail = _confirm_detail(request)
            if len(detail) > 58:
                detail = detail[:55] + "..."
            _confirm["title"] = title
            _confirm["options"] = _confirm_options(request.tool_name)
            _confirm["detail"] = detail
            _confirm["selected"] = 0
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = True
            screens.overlay = OverlayView.CONFIRM
            _MODAL_ACTIVE[0] = True
            with _append_lock:
                _set_output(output_buffer.text)
            _confirm["event"].clear()
            _invalidate()
            _confirm["event"].wait()
            _confirm["active"] = False
            screens.overlay = OverlayView.NONE
            _MODAL_ACTIVE[0] = False
            with _append_lock:
                _set_output(output_buffer.text)
            _invalidate()
            return _confirm["answer"]

        def tool_start(self, name: str, args) -> None:
            screen_reader = getattr(rt.cfg, "screen_reader", False)
            if screen_reader:
                append(f"Tool started: {name}.\n")
            gerund, past = tool_thinking_phrase(
                name, args if isinstance(args, dict) else None
            )
            _thinking["text"] = gerund
            _thinking["past"] = past
            _thinking["start_time"] = time.time()
            _thinking["active"] = True
            self._tool_switched = True
            _invalidate()

            if self._box_open:
                self._box_open = False
                self._box_start_marker = None
                self._raw_response = ""

            self._tool_args = args if isinstance(args, dict) else {}
            self._tool_start_time = time.time()
            desc = _format_tool_desc(name, self._tool_args)
            if self._activity_marker is None:
                self._activity_marker = len(output_buffer.text)
            verification = False
            if name == "terminal":
                try:
                    from ..agent.verification import VerificationKind, classify_verification

                    verification = (
                        classify_verification(str(self._tool_args.get("command", "")))
                        is not VerificationKind.NONE
                    )
                except Exception:
                    verification = False
            if not screen_reader:
                self._active_tool_event_id = self._activity.start(
                    name,
                    desc,
                    group=activity_group(name, verification=verification),
                )
                self._render_activity()

        def tool_result(self, name: str, shown: str) -> None:
            dur = time.time() - self._tool_start_time
            if self._active_tool_event_id is not None:
                self._activity.finish(
                    self._active_tool_event_id,
                    ActivityStatus.COMPLETE,
                    duration_s=dur,
                )
                self._active_tool_event_id = None
                self._render_activity()
            if getattr(rt.cfg, "screen_reader", False):
                append(f"Tool completed: {name}.\n")

        def blocked(self, name: str, reason: str) -> None:
            clean_reason = _trunc(reason, 40)
            if getattr(rt.cfg, "screen_reader", False):
                append(f"Tool blocked: {name}. {clean_reason}\n")
                return
            if self._active_tool_event_id is not None:
                self._activity.finish(
                    self._active_tool_event_id,
                    ActivityStatus.BLOCKED,
                    duration_s=time.time() - self._tool_start_time,
                    detail=clean_reason,
                )
                self._active_tool_event_id = None
                self._render_activity()
            else:
                append(f"  ┊ ✗ blocked {name} — {clean_reason}\n")

        def declined(self, name: str, reason: str) -> None:
            clean_reason = _trunc(reason, 40)
            if getattr(rt.cfg, "screen_reader", False):
                append(f"Tool declined: {name}. {clean_reason}\n")
                return
            if self._active_tool_event_id is not None:
                self._activity.finish(
                    self._active_tool_event_id,
                    ActivityStatus.DECLINED,
                    duration_s=time.time() - self._tool_start_time,
                    detail=clean_reason,
                )
                self._active_tool_event_id = None
                self._render_activity()
            else:
                append(f"  ┊ ✗ declined {name} — {clean_reason}\n")

    sink = _Sink()

    def _load_destination(destination: DestinationView) -> None:
        key = destination.value
        if key in screens.loading:
            return
        screens.loading.add(key)
        screen_snapshots.pop(key, None)
        _invalidate()

        def loader() -> None:
            try:
                if destination is DestinationView.STATS:
                    snapshot = collect_stats()
                elif destination is DestinationView.SKILLS:
                    snapshot = collect_skills()
                elif destination is DestinationView.TOOLS:
                    snapshot = collect_tools()
                elif destination is DestinationView.USAGE:
                    snapshot = collect_usage(session_id=session_id)
                else:
                    return
                screen_snapshots[key] = snapshot
            except Exception as exc:
                screens.status = f"Could not load {key}: {type(exc).__name__}"
                screen_snapshots[key] = None
            finally:
                screens.loading.discard(key)
                _invalidate()

        threading.Thread(target=loader, daemon=True).start()

    def _open_destination(destination: DestinationView) -> None:
        if _confirm["active"]:
            return
        screens.chat_cursor = output_buffer.cursor_position
        screens.input_text = input_buffer.text
        if screens.open_destination(destination):
            _load_destination(destination)
            _invalidate()

    def _close_destination() -> None:
        screens.destination = DestinationView.CHAT
        if input_buffer.text != screens.input_text:
            input_buffer.text = screens.input_text
        output_buffer.cursor_position = min(screens.chat_cursor, len(output_buffer.text))
        layout.focus(input_window)
        _invalidate()

    def _open_overlay(overlay: OverlayView) -> None:
        if _confirm["active"] or turn_running[0]:
            screens.status = "Wait for the active turn to finish."
            return
        if overlay is OverlayView.THEME:
            names = theme.theme_names()
            current = getattr(state, "theme_name", "marshmallow")
            if current in names:
                screens.selected["theme"] = names.index(current)
        elif overlay is OverlayView.MODEL:
            current_model = getattr(rt.cfg.provider, "model", "")
            for idx, opt in enumerate(model_options):
                if opt.model_id == current_model:
                    screens.selected["model"] = idx
                    break
        screens.open_overlay(overlay)
        modal_input[0] = ""
        _invalidate()

    # ---- slash command runner ----
    def run_command(user_text: str) -> None:
        buf = io.StringIO()
        app_w = _content_width()
        console = Console(file=buf, color_system=None, force_terminal=False, width=app_w)
        ctx = CommandContext(console=console, rt=rt, state=state)
        dispatch_command(user_text, ctx)
        out = buf.getvalue()
        if out:
            append(out.rstrip("\n") + "\n\n")
        refresh_stats(state)
        _reflow_borders()
        _invalidate()

    # ---- agent turn runner (background thread) ----
    def _spawn_turn(echo_user: str | None) -> None:
        turn_running[0] = True
        mascot_machine.start_turn()
        run_id = uuid.uuid4().hex
        user_text = echo_user
        if echo_user is not None:
            w = max(_content_width() - 4, 20)
            wrapped_lines: list[str] = []
            for raw_line in echo_user.splitlines():
                if not raw_line.strip():
                    wrapped_lines.append("")
                else:
                    wrapped_lines.extend(
                        textwrap.wrap(
                            raw_line,
                            width=w,
                            break_long_words=True,
                            break_on_hyphens=False,
                        )
                        or [""]
                    )
            if not wrapped_lines:
                wrapped_lines = [echo_user]

            formatted_echo = theme.USER_PREFIX + " " + wrapped_lines[0]
            if len(wrapped_lines) > 1:
                formatted_echo += "\n" + "\n".join(f"  {ln}" if ln else "" for ln in wrapped_lines[1:])
            append(formatted_echo + "\n\n")
            from ..agent.user_context import expand_user_context
            expanded_context = expand_user_context(echo_user, rt.workspace)
            messages.append(Message(role="user", content=expanded_context.prompt))
            if expanded_context.warns_about_size:
                append(
                    f"(context warning: about {expanded_context.estimated_tokens} tokens)\n"
                )
            _session_save(session_id, "user", echo_user, run_id=run_id)
        else:
            user_text = next(
                (m.content for m in reversed(messages) if getattr(m, "role", "") == "user"),
                "",
            )

        sink.set_user_input(user_text or "")
        try:
            from hund.learning.reflection import take_snapshot
            sink.set_turn_snapshot(take_snapshot())
        except Exception:
            pass

        console = _discard_console()

        def worker() -> None:
            turn_start = time.time()
            dynamic_msg = None
            try:
                tokens_before = estimate_tokens(messages)
                # Deterministic compression is local and bounded. It still belongs
                # off the Prompt Toolkit thread so submitting a prompt never freezes
                # the terminal when a long session crosses the token threshold.
                comp = maybe_compress(messages)
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
                mascot_machine.finish_turn()
                if dynamic_msg is not None:
                    messages[:] = [m for m in messages if m is not dynamic_msg]
                messages[:] = [
                    m for m in messages
                    if not (getattr(m, "content", "") or "").startswith(
                        "[FÖROBSERVATIONER"
                    )
                ]
                _restore_frozen_system_prompt(messages, frozen)
                state.extra["tokens"] = estimate_tokens(messages)
                refresh_stats(state)
                _reflow_borders()
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

        destination_commands = {
            "/stats": DestinationView.STATS,
            "/skills": DestinationView.SKILLS,
            "/tools": DestinationView.TOOLS,
            "/usage": DestinationView.USAGE,
        }
        if text in destination_commands:
            _open_destination(destination_commands[text])
            return True

        if text == "/theme":
            _open_overlay(OverlayView.THEME)
            return True

        if text == "/model":
            _open_overlay(OverlayView.MODEL)
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
    confirm_active = Condition(lambda: bool(_confirm.get("active")))
    overlay_active = Condition(
        lambda: screens.overlay
        in {
            OverlayView.THEME,
            OverlayView.MODEL,
            OverlayView.MODEL_CUSTOM,
            OverlayView.MODEL_KEY,
        }
    )
    modal_active = Condition(
        lambda: bool(_confirm.get("active"))
        or screens.overlay
        in {
            OverlayView.THEME,
            OverlayView.MODEL,
            OverlayView.MODEL_CUSTOM,
            OverlayView.MODEL_KEY,
        }
    )
    destination_active = Condition(
        lambda: screens.destination is not DestinationView.CHAT
        and not _confirm.get("active")
        and screens.overlay is OverlayView.NONE
    )
    chat_active = Condition(
        lambda: screens.destination is DestinationView.CHAT
        and not _confirm.get("active")
        and screens.overlay is OverlayView.NONE
    )

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
        _confirm["selected"] = (_confirm["selected"] - 1) % len(_confirm["options"])
        event.app.invalidate()

    @kb.add("down", filter=confirm_active)
    def _down(event):
        _confirm["selected"] = (_confirm["selected"] + 1) % len(_confirm["options"])
        event.app.invalidate()

    @kb.add("enter", filter=confirm_active)
    def _enter(event):
        _confirm["answer"] = _confirm["options"][_confirm["selected"]][0]
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("y", filter=confirm_active)
    def _y(event):
        _confirm["answer"] = ConfirmVerdict.APPROVE_ONCE
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("e", filter=confirm_active)
    def _e(event):
        verdicts = {item[0] for item in _confirm["options"]}
        _confirm["answer"] = (
            ConfirmVerdict.EDIT if ConfirmVerdict.EDIT in verdicts else ConfirmVerdict.DENY
        )
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("a", filter=confirm_active)
    def _a(event):
        verdicts = {item[0] for item in _confirm["options"]}
        _confirm["answer"] = (
            ConfirmVerdict.ALLOW_SESSION
            if ConfirmVerdict.ALLOW_SESSION in verdicts
            else ConfirmVerdict.DENY
        )
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("n", filter=confirm_active)
    @kb.add("escape", filter=confirm_active)
    def _n(event):
        _confirm["answer"] = ConfirmVerdict.DENY
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("escape", filter=~confirm_active)
    def _escape(event):
        result = screens.close_escape()
        if result == "destination":
            _close_destination()
            return
        if result in {"nested", "overlay", "detail"}:
            modal_input[0] = ""
            screens.status = ""
            _invalidate()
            return
        if output_buffer.selection_state is not None:
            output_buffer.exit_selection()
        layout.focus(input_window)
        _invalidate()

    @kb.add("up", filter=overlay_active & ~confirm_active)
    def _overlay_up(event):
        if screens.overlay is OverlayView.THEME:
            screens.move("theme", -1, len(theme.theme_names()))
        elif screens.overlay is OverlayView.MODEL:
            screens.move("model", -1, len(model_options))
        _invalidate()

    @kb.add("down", filter=overlay_active & ~confirm_active)
    def _overlay_down(event):
        if screens.overlay is OverlayView.THEME:
            screens.move("theme", 1, len(theme.theme_names()))
        elif screens.overlay is OverlayView.MODEL:
            screens.move("model", 1, len(model_options))
        _invalidate()

    @kb.add("up", filter=destination_active & ~modal_active)
    def _screen_up(event):
        key = screens.destination.value
        snapshot = screen_snapshots.get(key)
        if screens.destination is DestinationView.SKILLS and snapshot is not None:
            screens.move(key, -1, len(snapshot.equipped) + len(snapshot.parked))
            screens.scroll_by(key, -1, 10_000)
        elif screens.destination is DestinationView.TOOLS and snapshot is not None:
            screens.move(key, -1, len(snapshot.tools))
            screens.scroll_by(key, -1, 10_000)
        else:
            screens.scroll_by(key, -1, 10_000)
        _invalidate()

    @kb.add("down", filter=destination_active & ~modal_active)
    def _screen_down(event):
        key = screens.destination.value
        snapshot = screen_snapshots.get(key)
        if screens.destination is DestinationView.SKILLS and snapshot is not None:
            screens.move(key, 1, len(snapshot.equipped) + len(snapshot.parked))
            screens.scroll_by(key, 1, 10_000)
        elif screens.destination is DestinationView.TOOLS and snapshot is not None:
            screens.move(key, 1, len(snapshot.tools))
            screens.scroll_by(key, 1, 10_000)
        else:
            screens.scroll_by(key, 1, 10_000)
        _invalidate()

    @kb.add("enter", filter=overlay_active & ~confirm_active)
    def _overlay_enter(event):
        if screens.overlay is OverlayView.THEME:
            names = theme.theme_names()
            selected = names[screens.selected.get("theme", 0) % len(names)]
            old_theme = getattr(state, "theme_name", "marshmallow")
            state.theme_name = selected
            rt.cfg.theme = selected
            try:
                rt.cfg.save()
            except Exception:
                state.theme_name = old_theme
                rt.cfg.theme = old_theme
                screens.status = "Could not save the selected theme."
                return
            event.app.style = theme.make_pt_style(selected)
            screens.overlay = OverlayView.NONE
            screens.status = ""
        elif screens.overlay is OverlayView.MODEL:
            from ..providers.catalog import activate_model

            option = model_options[screens.selected.get("model", 0) % len(model_options)]
            ok, message = activate_model(rt, option)
            screens.status = message
            if ok:
                state.extra["model"] = option.model_id
                state.extra["token_limit"] = option.context_window
                screens.overlay = OverlayView.NONE
        elif screens.overlay is OverlayView.MODEL_CUSTOM:
            from ..providers.catalog import activate_model, custom_model

            try:
                provider, base_url, model, context = [
                    part.strip() for part in modal_input[0].split("|", 3)
                ]
                option = custom_model(provider, base_url, model, int(context))
                ok, message = activate_model(rt, option)
                screens.status = message
                if ok:
                    model_options.insert(0, option)
                    state.extra["model"] = option.model_id
                    state.extra["token_limit"] = option.context_window
                    screens.overlay = OverlayView.NONE
            except Exception:
                screens.status = "Use: provider | base URL | model ID | context window"
        elif screens.overlay is OverlayView.MODEL_KEY:
            from ..secrets import save_api_key

            option = model_options[screens.selected.get("model", 0) % len(model_options)]
            secret = modal_input[0]
            modal_input[0] = ""
            if save_api_key(secret, option.credential_id):
                screens.overlay = OverlayView.MODEL
                screens.status = "Credential stored in Windows Credential Manager."
            else:
                screens.status = (
                    f"Credential vault unavailable. Set {option.env_name or 'HUND_API_KEY'}."
                )
        _invalidate()

    @kb.add("enter", filter=destination_active & ~modal_active)
    def _screen_enter(event):
        key = screens.destination.value
        snapshot = screen_snapshots.get(key)
        if snapshot is None:
            return
        index = screens.selected.get(key, 0)
        if screens.destination is DestinationView.SKILLS:
            items = snapshot.equipped + snapshot.parked
            if items:
                screens.detail[key] = items[index % len(items)].name
        elif screens.destination is DestinationView.TOOLS and snapshot.tools:
            screens.detail[key] = snapshot.tools[index % len(snapshot.tools)].name
        _invalidate()

    @kb.add("e", filter=destination_active & ~modal_active)
    def _equip_skill(event):
        if screens.destination is not DestinationView.SKILLS:
            return
        snapshot = screen_snapshots.get("skills")
        if snapshot is None:
            return
        items = snapshot.equipped + snapshot.parked
        if not items:
            return
        selected = items[screens.selected.get("skills", 0) % len(items)]
        from ..skills.loader import load_builtins
        from ..skills.vault import SkillVault

        ok, message = SkillVault().equip(selected.name)
        screens.status = message
        if ok:
            vault = SkillVault()
            rt.skills = load_builtins() + vault.get_active_skills()
            _load_destination(DestinationView.SKILLS)
        _invalidate()

    @kb.add("p", filter=destination_active & ~modal_active)
    def _park_skill(event):
        if screens.destination is not DestinationView.SKILLS:
            return
        snapshot = screen_snapshots.get("skills")
        if snapshot is None:
            return
        items = snapshot.equipped + snapshot.parked
        if not items:
            return
        selected = items[screens.selected.get("skills", 0) % len(items)]
        from ..skills.loader import load_builtins
        from ..skills.vault import SkillVault

        ok, message = SkillVault().park(selected.name)
        screens.status = message
        if ok:
            vault = SkillVault()
            rt.skills = load_builtins() + vault.get_active_skills()
            _load_destination(DestinationView.SKILLS)
        _invalidate()

    @kb.add("e", filter=Condition(lambda: screens.overlay is OverlayView.MODEL and not _confirm.get("active")))
    def _custom_model(event):
        modal_input[0] = ""
        screens.open_overlay(OverlayView.MODEL_CUSTOM)
        _invalidate()

    @kb.add("k", filter=Condition(lambda: screens.overlay is OverlayView.MODEL and not _confirm.get("active")))
    def _model_key(event):
        modal_input[0] = ""
        screens.open_overlay(OverlayView.MODEL_KEY)
        _invalidate()

    @kb.add("backspace", filter=Condition(
        lambda: screens.overlay in {OverlayView.MODEL_CUSTOM, OverlayView.MODEL_KEY} and not _confirm.get("active")
    ))
    def _modal_backspace(event):
        modal_input[0] = modal_input[0][:-1]
        _invalidate()

    @kb.add(Keys.Any, filter=Condition(
        lambda: screens.overlay in {OverlayView.MODEL_CUSTOM, OverlayView.MODEL_KEY} and not _confirm.get("active")
    ))
    def _modal_type(event):
        for key in event.key_sequence:
            if len(key.data) == 1 and key.data.isprintable():
                modal_input[0] += key.data
        _invalidate()

    @kb.add("c-c")
    def _ctrl_c(event):
        if _confirm["active"]:
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = False
            _confirm["event"].set()
            _invalidate()
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
        if screens.destination is not DestinationView.CHAT:
            screens.scroll_by(screens.destination.value, -3, 10_000)
            _invalidate()
        else:
            _scroll_lines(3)

    @kb.add("<scroll-down>")
    def _scroll_down(event):
        if screens.destination is not DestinationView.CHAT:
            screens.scroll_by(screens.destination.value, 3, 10_000)
            _invalidate()
        else:
            _scroll_lines(-3)

    @kb.add("enter", filter=has_focus(input_window) & chat_active)
    def _enter_submit(event):
        input_buffer.validate_and_handle()

    @kb.add("c-j", filter=has_focus(input_window) & chat_active)
    def _newline_input(event):
        input_buffer.insert_text("\n")

    @kb.add(Keys.Any, filter=has_focus(output_window) & chat_active)
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
    initial_skin = getattr(state, "theme_name", "marshmallow") or "marshmallow"
    depth = ColorDepth.DEPTH_24_BIT if theme.supports_truecolor() else ColorDepth.DEPTH_4_BIT
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=theme.make_pt_style(initial_skin),
        color_depth=depth,
        mouse_support=True,
    )
    app.timeoutlen = 0.05
    holder["app"] = app

    # Resize observations are debounced, then all Prompt Toolkit mutations are
    # scheduled on its asyncio thread. This avoids flicker, partial layouts and
    # repeated full-history reflows while the user is dragging the window.
    watchers_stop = threading.Event()
    ui_loop = asyncio.get_running_loop()

    def _width_watcher() -> None:
        rendered = _app_width()
        candidate = rendered
        changed_at = time.monotonic()
        while not watchers_stop.wait(0.05):
            w = _app_width()
            if w != candidate:
                candidate = w
                changed_at = time.monotonic()
            elif candidate != rendered and time.monotonic() - changed_at >= 0.15:
                rendered = candidate
                ui_loop.call_soon_threadsafe(_reflow_borders)
                ui_loop.call_soon_threadsafe(_invalidate)

    threading.Thread(target=_width_watcher, daemon=True).start()

    def _mascot_watcher() -> None:
        if getattr(rt.cfg, "reduced_motion", False):
            return
        while not watchers_stop.wait(0.12):
            _invalidate()

    threading.Thread(target=_mascot_watcher, daemon=True).start()

    try:
        result = await app.run_async()
    finally:
        watchers_stop.set()
    return result if isinstance(result, int) else 0

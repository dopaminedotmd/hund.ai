"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable, semantically-colored output
buffer, a single input buffer, and an in-app arrow-key confirmation modal.

The output buffer is read-only (safe against stray typing) but focusable, so
the mouse can select text; Ctrl+C copies a selection or controls the active
chat state. The agent turn runs in a background thread.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import textwrap
import threading
import time
import uuid
from typing import Any, Callable

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_completions, has_focus, has_selection, is_done
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer, WindowRenderInfo
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIContent
from prompt_toolkit.layout.margins import Margin, ScrollbarMargin
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.selection import SelectionType
from prompt_toolkit.layout.screen import Char, Screen, WritePosition
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth
from rich.console import Console

from ..agent.context import estimate_tokens, maybe_compress
from ..agent.loop import (
    _agent_turn,
    _dynamic_context_message,
    _restore_frozen_system_prompt,
    _run_authoring_runtime,
    _safe_skills,
    _session_save,
    _trace_event,
)
from ..paths import hund_home
from ..providers.base import Message
from . import clipboard, theme
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
    normalize_terminal_input,
    resolve_slash_command,
)
from .output import (
    StreamingMarkdownFilter,
    _confirm_detail,
    _confirm_reason,
    _confirm_title,
    parse_confirm_input,
    parse_semantic_segments,
    strip_markdown,
    strip_rich,
    tool_thinking_phrase,
)
from .render import (
    box_bottom as _r_box_bottom,
    box_top as _r_box_top,
    normalize_language_alias,
    refresh_stats,
    render_intermediate_capsule,
    render_response_box,
    render_response_box_from_segments,
    response_content_width,
)
from ..agent.types import ConfirmRequest, ConfirmVerdict
from .confirmation import confirmation_options, prompt_edits
from .mascot import MascotMachine, mirror_art
from .screen_state import DestinationView, OverlayView, ScreenController
from .screen_render import (
    fullscreen_frame,
    render_auth_add_modal,
    render_auth_custom_wizard_modal,
    render_auth_forget_modal,
    render_auth_manage_modal,
    render_auth_modal,
    render_model_custom_modal,
    render_model_key_modal,
    render_model_modal,
    render_skills,
    render_stats,
    render_theme_modal,
    render_tools,
    render_usage,
    render_system,
    render_doctor,
)
from .snapshots import collect_skills, collect_stats, collect_tools, collect_usage
from ..config import CustomEndpoint
from ..providers.catalog import (
    MODEL_OPTIONS,
    PROVIDER_PRESETS,
    ProviderPreset,
    activate_model,
    active_option,
    custom_model,
    get_options,
)
from ..secrets import delete_api_key, get_credential_status, save_api_key
from .modal_editor import ModalTextEditor

from .phrases import select_thinking_phrase

_S = theme.SEMANTIC

_STYLE = theme.make_pt_style("marshmallow")
_MODAL_ACTIVE = [False]


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


def _format_runtime_error(e: Exception | str, max_width: int = 70) -> str:
    err_str = str(e)
    err_lower = err_str.lower()
    status_match = re.search(r"\b(?:provider\s+)?http(?:\s+status)?\s+(\d{3})\b", err_lower)
    status = int(status_match.group(1)) if status_match else None
    detail = f" Provider detail: {err_str[:160]}"

    if status == 401:
        title = "API Authentication Error (HTTP 401)"
        body = "Invalid or missing API key. Run /setup to configure your key, or /model to switch provider." + detail
    elif status == 402 or "insufficient balance" in err_lower:
        title = "API Quota / Balance Error (HTTP 402)"
        body = "Account has insufficient balance or quota exceeded. Switch models with /model or check your provider billing account." + detail
    elif status == 429:
        title = "API Rate Limit Error (HTTP 429)"
        body = "Provider rate limit reached. Please wait a moment before retrying, or use /retry to resend." + detail
    elif status is not None and 500 <= status < 600:
        title = f"Provider Server Error (HTTP {status})"
        body = "Provider request failed. Retry shortly or check provider status." + detail
    elif status is not None:
        title = "Provider Connection Error"
        body = "HTTP request failed. Check your network connection or verify provider status." + detail
    else:
        title = "Execution Error"
        body = err_str[:160]

    return f"\n{title}: {body}\n"


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


class _TransparentSpriteWindow(Window):
    """A window that draws only non-space characters into screen.data_buffer,
    allowing underlying transcript content to remain visible beneath spaces."""

    def __init__(
        self,
        get_text_fragments: Any,
        scroll_cb_getter: Any = None,
        width: int = 16,
        height: int = 7,
    ) -> None:
        self._get_text_fragments = get_text_fragments
        self._scroll_cb_getter = scroll_cb_getter
        control = _ScrollThroughFormattedTextControl(
            get_text_fragments, scroll_cb_getter=scroll_cb_getter
        )
        super().__init__(
            content=control,
            width=width,
            height=height,
            dont_extend_width=True,
            dont_extend_height=True,
            wrap_lines=False,
            char=None,
        )

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: Any,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        if write_position.height <= 0 or write_position.width <= 0:
            return

        fragments = self._get_text_fragments()
        if not fragments:
            return

        lines: list[list[tuple[str, str]]] = [[]]
        for style, text in fragments:
            parts = text.split("\n")
            for idx, part in enumerate(parts):
                if idx > 0:
                    lines.append([])
                for ch in part:
                    lines[-1].append((style, ch))

        for row_idx, line in enumerate(lines[: write_position.height]):
            y = write_position.ypos + row_idx
            x = write_position.xpos
            for style, ch in line:
                cw = get_cwidth(ch)
                if ch not in (" ", "\t", "\r", "\n", "\u200b") and cw > 0:
                    combined_style = (parent_style + " " + style).strip()
                    screen.data_buffer[y][x] = Char(ch, combined_style)
                x += cw
                if x >= write_position.xpos + write_position.width:
                    break


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


def _parse_semantic_line(text: str, indent_str: str = "", bold_open: bool = False) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    if indent_str:
        tokens.append(("", indent_str))
    cur = text

    if bold_open:
        if "**" in cur:
            bold_part, _, rest = cur.partition("**")
            if bold_part:
                tokens.append(("class:strong", bold_part))
            cur = rest
        else:
            tokens.append(("class:strong", cur))
            return tokens

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
    skill_num_match = re.match(r"^(\d+\.\s+)([^\s—–]+(?:[ \t]+[^\s—–]+)*)(\s+[—–]\s+)(.*)$", cur)
    if skill_num_match:
        tokens.append(("class:number", skill_num_match.group(1)))
        tokens.append(("class:header", skill_num_match.group(2)))
        tokens.append(("class:secondary", skill_num_match.group(3)))
        rest_desc = skill_num_match.group(4)
        if rest_desc:
            tokens.extend(_parse_semantic_line(rest_desc))
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
        # Prefix char → add_fg/del_fg (green/red), lineno → diff_lineno (grey), code → add/del bg.
        diff_num_add = re.match(r"^([+])(\s*\d+\s+)(.*)$", cur)
        diff_num_del = re.match(r"^([-])(\s*\d+\s+)(.*)$", cur)
        if diff_num_add:
            tokens.append(("class:add_fg", diff_num_add.group(1)))
            tokens.append(("class:diff_lineno", diff_num_add.group(2)))
            tokens.append(("class:add", diff_num_add.group(3)))
            return tokens
        elif diff_num_del:
            tokens.append(("class:del_fg", diff_num_del.group(1)))
            tokens.append(("class:diff_lineno", diff_num_del.group(2)))
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
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|->|→|—|–|\*\*)")
    pos = 0
    for m in pattern.finditer(cur):
        if m.start() > pos:
            tokens.append(("class:primary", cur[pos : m.start()]))
        val = m.group(0)
        if val.startswith("**") and val.endswith("**") and len(val) >= 4:
            tokens.append(("class:strong", val[2:-2]))
        elif val == "**":
            remainder = cur[m.end():]
            if remainder:
                tokens.append(("class:strong", remainder))
            pos = len(cur)
            break
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


@dataclass(frozen=True)
class ResponseBlockRecord:
    block_id: int
    start_line: int
    line_count: int
    line_metadata: dict[int, tuple[str, str]]  # relative_line_idx -> (segment_type, language)


@dataclass
class ResponsePayloadRecord:
    block_id: int
    canonical_chunks: list[str]
    segments: list[Any]  # FrozenSemanticSegment list
    meta: str | None = None
    canonical_source_cached: str | None = None

    @property
    def canonical_source(self) -> str:
        if self.canonical_source_cached is None:
            self.canonical_source_cached = "".join(self.canonical_chunks)
        return self.canonical_source_cached


class ResponseBlockRegistry:
    """App-local registry storing rendered response block offsets and line styles."""

    def __init__(self) -> None:
        self._blocks: dict[int, ResponseBlockRecord] = {}

    def records(self) -> tuple[ResponseBlockRecord, ...]:
        """Return all registered block records sorted by ascending start_line."""
        return tuple(sorted(self._blocks.values(), key=lambda r: r.start_line))

    def get(self, block_id: int) -> ResponseBlockRecord | None:
        """Get a registered block record by its stable block_id."""
        return self._blocks.get(block_id)

    def remove(self, block_id: int) -> None:
        """Remove a block by its stable block_id."""
        self._blocks.pop(block_id, None)

    def register_or_update(
        self,
        block_id: int,
        start_line: int,
        line_count: int,
        line_metadata: dict[int, tuple[str, str]],
    ) -> None:
        self._blocks[block_id] = ResponseBlockRecord(
            block_id=block_id,
            start_line=start_line,
            line_count=line_count,
            line_metadata=dict(line_metadata),
        )

    def shift_after(self, line_idx: int, delta_lines: int) -> None:
        """Shift start_line of all blocks located at or after line_idx by delta_lines."""
        if delta_lines == 0:
            return
        new_blocks: dict[int, ResponseBlockRecord] = {}
        for b_id, rec in self._blocks.items():
            if rec.start_line >= line_idx:
                new_blocks[b_id] = ResponseBlockRecord(
                    block_id=rec.block_id,
                    start_line=max(0, rec.start_line + delta_lines),
                    line_count=rec.line_count,
                    line_metadata=rec.line_metadata,
                )
            else:
                new_blocks[b_id] = rec
        self._blocks = new_blocks

    def replace_from(self, other: ResponseBlockRegistry) -> None:
        self._blocks = dict(other._blocks)

    def clear(self) -> None:
        self._blocks.clear()

    def get_line_style(self, abs_line_idx: int) -> tuple[str, str] | None:
        for record in self._blocks.values():
            if record.start_line <= abs_line_idx < record.start_line + record.line_count:
                rel_idx = abs_line_idx - record.start_line
                return record.line_metadata.get(rel_idx)
        return None


def _lex_pygments_code(
    cur: str, indent_str: str, lang: str, row_style: str = "", muted: bool = False
) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    is_del = (row_style == "class:del")
    is_muted = is_del or muted
    if indent_str:
        tokens.append(((row_style if row_style else ""), indent_str))
    canon_lang = normalize_language_alias(lang) if lang else "python"
    if canon_lang in ("diff", "patch", ""):
        canon_lang = "html" if ("<" in cur and ">" in cur) else "python"
    try:
        import pygments
        from pygments.lexers import get_lexer_by_name
        from pygments.token import (
            Comment,
            Error,
            Keyword,
            Literal,
            Name,
            Number,
            Operator,
            Punctuation,
            String,
            Text,
            Whitespace,
        )

        lexer = get_lexer_by_name(canon_lang)
        if canon_lang == "html" and not ("<" in cur or ">" in cur) and (":" in cur or ";" in cur or "{" in cur or "}" in cur):
            try:
                css_lexer = get_lexer_by_name("css")
                css_toks = list(pygments.lex(cur, css_lexer))
                if any(t[0] not in (Text, Error, Whitespace) for t in css_toks):
                    lexer = css_lexer
            except Exception:
                pass
    except Exception:
        try:
            from pygments.lexers import TextLexer
            lexer = TextLexer()
        except Exception:
            fb_style = f"{row_style} {('class:del_fg' if is_del else ('class:add_fg' if muted else 'class:primary'))}".strip() if row_style else ("class:del_fg" if is_del else "class:primary")
            return [((row_style or ""), indent_str), (fb_style, cur)] if indent_str else [(fb_style, cur)]

    try:
        for tok_type, val in pygments.lex(cur, lexer):
            if val.endswith("\n") and not cur.endswith("\n"):
                val = val[:-1]
            if not val:
                continue

            if tok_type in Whitespace or (tok_type is Text and not val.strip()):
                cls = ""
            elif is_del:
                if tok_type in Keyword or tok_type in (Name.Tag, Name.Attribute):
                    cls = "class:syntax_del_keyword"
                elif tok_type in String:
                    cls = "class:syntax_del_string"
                elif tok_type in Number:
                    cls = "class:syntax_del_number"
                elif tok_type in Comment:
                    cls = "class:syntax_del_comment"
                elif tok_type in (Name.Function, Name.Class, Name.Builtin, Name.Builtin.Pseudo, Name.Exception):
                    cls = "class:syntax_del_function"
                elif tok_type in Operator or tok_type in Punctuation:
                    cls = "class:syntax_del_operator"
                elif tok_type in Error:
                    cls = "class:del_fg"
                else:
                    cls = "class:syntax_del_variable"
            elif muted:
                if tok_type in Name.Tag:
                    cls = "class:syntax_diff_tag"
                elif tok_type in Name.Attribute:
                    cls = "class:syntax_diff_attr"
                elif tok_type in Keyword:
                    cls = "class:syntax_diff_keyword"
                elif tok_type in String:
                    cls = "class:syntax_diff_string"
                elif tok_type in Number:
                    cls = "class:syntax_diff_number"
                elif tok_type in Comment:
                    cls = "class:syntax_diff_comment"
                elif tok_type in (Name.Function, Name.Class, Name.Builtin, Name.Builtin.Pseudo, Name.Exception):
                    cls = "class:syntax_diff_function"
                elif tok_type in Operator or tok_type in Punctuation:
                    cls = "class:syntax_diff_operator"
                elif tok_type in Error:
                    cls = "class:add_fg"
                elif tok_type is Text:
                    cls = "class:syntax_diff_text"
                else:
                    cls = "class:syntax_diff_variable"
            else:
                if tok_type in Keyword or tok_type in (Name.Tag, Name.Attribute):
                    cls = "class:syntax_keyword"
                elif tok_type in String:
                    cls = "class:syntax_string"
                elif tok_type in Number:
                    cls = "class:syntax_number"
                elif tok_type in Comment:
                    cls = "class:syntax_comment"
                elif tok_type in (Name.Function, Name.Class, Name.Builtin, Name.Builtin.Pseudo, Name.Exception):
                    cls = "class:syntax_function"
                elif tok_type in Operator or tok_type in Punctuation:
                    cls = "class:syntax_operator"
                elif tok_type in Error:
                    cls = "class:primary"
                else:
                    cls = "class:syntax_variable"

            style = f"{row_style} {cls}".strip() if row_style else (cls or "class:primary")
            tokens.append((style, val))
        return tokens
    except Exception:
        fb_style = f"{row_style} {('class:del_fg' if is_del else ('class:add_fg' if muted else 'class:primary'))}".strip() if row_style else ("class:del_fg" if is_del else "class:primary")
        return [((row_style or ""), indent_str), (fb_style, cur)] if indent_str else [(fb_style, cur)]


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
    r"(?P<good>\[(?:Key OK|Ready|safe|equipped|Novice|Apprentice|Adept|Expert|Master)\])|"
    r"(?P<warning>\[(?:moderate|prompt|read_only|parked|LCK)\])|"
    r"(?P<bad>\[(?:Key missing|Unavailable|dangerous|blocked|declined)\])|"
    r"(?P<label>\b(?:Domain|Lifecycle|XP|Safety level|Triggers|Tools|Provenance|"
    r"Category|Context mode|Dispatch|Parameter schema|Activity / Day|Base Stat Deltas|Prompt|Output|Requests|Active|Lv\.\d+):?)|"
    r"(?P<meta_label>\b(?:OS|HOST|CPU|RAM|GPU|MODEL|TOOL|CATEGORY|SAFETY LEVEL|DISPATCH)\b)"
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
            if not left and not right and line:
                fragments.append(("class:modal_footer", content))
            elif content.lstrip().startswith(("[Esc", "↑", "Less  ", "[Backspace]", "[←]", "<-", "commands:")):
                fragments.append(("class:modal_footer", content))
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
                        "warning": "class:warning",
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

    def __init__(self, block_registry: ResponseBlockRegistry | None = None) -> None:
        self.block_registry = block_registry or ResponseBlockRegistry()

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

        # Pre-scan for multiline user messages and multiline bold
        user_lines: set[int] = set()
        skill_seed_lines: set[int] = set()
        skill_seed_name_lines: set[int] = set()
        authoring_lines: set[int] = set()
        authoring_title_lines: set[int] = set()
        bold_open_lines: set[int] = set()
        is_bold_open = False
        # agyC/0: bold-state återställs vid varje response-blockgräns (REV3.3) —
        # ett obalanserat ** i ett tidigare block får inte färga senare block.
        try:
            block_starts = {r.start_line for r in self.block_registry.records()}
        except Exception:
            block_starts = set()
        in_user = False
        in_skill_seed = False
        in_authoring = False
        in_authoring_title = False
        expect_authoring_title = False
        expect_skill_seed_name = False
        for i, raw_line in enumerate(lines):
            if i in block_starts:
                is_bold_open = False
            if is_bold_open:
                bold_open_lines.add(i)

            chk = raw_line
            if "│" in chk:
                parts = chk.split("│")
                if len(parts) >= 3:
                    chk = parts[1]
            if not (chk.startswith("```") or chk.startswith("──") or chk.startswith("╔") or chk.startswith("╚") or chk.startswith("║")):
                cnt = chk.count("**")
                if cnt % 2 == 1:
                    is_bold_open = not is_bold_open

            line_content = raw_line
            stripped_l = line_content.strip()
            if stripped_l in {"◆  SKILL SEED", "◆ SKILL SEED", "+  SKILL SEED", "+ SKILL SEED"}:
                in_skill_seed = True
                expect_skill_seed_name = True
                skill_seed_lines.add(i)
            elif in_skill_seed:
                skill_seed_lines.add(i)
                if expect_skill_seed_name and stripped_l.startswith(("│", "|")):
                    skill_seed_name_lines.add(i)
                    expect_skill_seed_name = False
                if "[a] Accept" in stripped_l:
                    in_skill_seed = False
            if (
                "SKILL AUTHORING" in stripped_l
                or "SKILL READY" in stripped_l
                or "SKILL CREATED" in stripped_l
                or "SKILL UPDATED" in stripped_l
            ):
                in_authoring = True
                expect_authoring_title = "AUTHORING" in stripped_l
                in_authoring_title = False
                authoring_lines.add(i)
            elif in_authoring:
                authoring_lines.add(i)
                body = stripped_l[1:].strip() if stripped_l.startswith(("│", "|")) else ""
                if expect_authoring_title and body:
                    authoring_title_lines.add(i)
                    expect_authoring_title = False
                    in_authoring_title = True
                elif in_authoring_title and body:
                    authoring_title_lines.add(i)
                elif in_authoring_title and not body:
                    in_authoring_title = False

                if stripped_l.startswith(("└", "`")):
                    in_authoring = False
            if stripped_l.startswith("❯"):
                in_user = True
                user_lines.add(i)
            elif in_user:
                if (
                    stripped_l.startswith("┊")
                    or stripped_l.startswith("·")
                    or stripped_l.startswith("┌─ hund")
                    or stripped_l.startswith("╭─ hund")
                    or stripped_l.startswith("╔")
                    or i in authoring_lines
                    or stripped_l.startswith("hund ")
                ):
                    in_user = False
                else:
                    user_lines.add(i)

        registry = self.block_registry

        def get_line(lineno: int):
            try:
                line = lines[lineno]
            except IndexError:
                return []

            if line.startswith("╔") or line.startswith("║") or line.startswith("╚"):
                return _lex_banner_line(line)

            if lineno in authoring_lines:
                stripped_authoring = line.lstrip()
                leading = line[: len(line) - len(stripped_authoring)]
                if "SKILL AUTHORING" in stripped_authoring or "SKILL READY" in stripped_authoring or "SKILL CREATED" in stripped_authoring or "SKILL UPDATED" in stripped_authoring:
                    return [("", leading), ("class:growth_gold bold", stripped_authoring)]
                if stripped_authoring.startswith(("│", "|")):
                    rail = stripped_authoring[:1]
                    body = stripped_authoring[1:]
                    body_style = "class:growth_cream"
                    if lineno in authoring_title_lines or body.lstrip().startswith(("› ", "> ")):
                        body_style = "class:growth_gold bold"
                    elif body.startswith("    "):
                        body_style = "class:secondary"
                    return [
                        ("", leading),
                        ("class:growth_gold", rail),
                        (body_style, body),
                    ]
                if stripped_authoring.startswith(("└", "`")):
                    return [
                        ("", leading),
                        ("class:growth_gold", stripped_authoring[:1]),
                        ("class:growth_gold", stripped_authoring[1:]),
                    ]
                return [("", leading), ("class:growth_cream", stripped_authoring)]

            line_style = registry.get_line_style(lineno)
            is_box = line.startswith("│") and line.endswith("│")
            if not is_box:
                indent_len = len(line) - len(line.lstrip())
                indent_str = line[:indent_len]
                cur = line[indent_len:]
                cur_r = cur.rstrip()
                trailing_spaces = cur[len(cur_r):]

                if cur_r.startswith("└ "):
                    m_header = re.match(r"^└\s+(.*?)(?:\s+\(\+(\d+)\s+-(\d+)\))?$", cur_r)
                    if m_header:
                        fn = m_header.group(1)
                        adds = m_header.group(2)
                        dels = m_header.group(3)
                        toks = [("", indent_str), ("class:secondary", "└ "), ("class:secondary", fn)]
                        if adds is not None and dels is not None:
                            toks.extend([
                                ("class:secondary", "  ("),
                                ("class:diff_stat_add", f"+{adds}"),
                                ("class:secondary", " "),
                                ("class:diff_stat_del", f"-{dels}"),
                                ("class:secondary", ")"),
                            ])
                        if trailing_spaces:
                            toks.append(("", trailing_spaces))
                        return toks
                    toks = [
                        ("", indent_str),
                        ("class:secondary", "└ "),
                        ("class:secondary", cur_r[2:]),
                    ]
                    if trailing_spaces:
                        toks.append(("", trailing_spaces))
                    return toks
                if m_wrap := re.match(r"^\s*(\(\+(\d+)\s+-(\d+)\))$", cur_r):
                    adds = m_wrap.group(2)
                    dels = m_wrap.group(3)
                    toks = [
                        ("", indent_str),
                        ("class:secondary", "  ("),
                        ("class:diff_stat_add", f"+{adds}"),
                        ("class:secondary", " "),
                        ("class:diff_stat_del", f"-{dels}"),
                        ("class:secondary", ")"),
                    ]
                    if trailing_spaces:
                        toks.append(("", trailing_spaces))
                    return toks
                if cur_r == "… Diff preview limited.":
                    toks = [("", indent_str), ("class:secondary", cur_r)]
                    if trailing_spaces:
                        toks.append(("", trailing_spaces))
                    return toks
                
                pm2 = re.match(r"^([+-])(\s*\d+\s+)(.*)$", cur_r)
                marker = re.match(r"^([+-]\s*(?:\d+\s+)?)(.*)$", cur_r)
                if pm2 and (line_style is not None or re.match(r"^[+-]\s*\d+\s+", cur_r)):
                    is_add = pm2.group(1) == "+"
                    fg_cls = "class:add_fg" if is_add else "class:del_fg"
                    row_style = "class:add" if is_add else "class:del"
                    target_lang = (line_style[1] if line_style is not None else "") or "python"
                    if target_lang in ("diff", "patch", ""):
                        target_lang = "html" if ("<" in cur_r and ">" in cur_r) else "python"
                    prefix_style = f"{row_style} {fg_cls}"
                    gutter_style = f"{row_style} class:diff_lineno"
                    code_toks = _lex_pygments_code(
                        pm2.group(3), "", target_lang, row_style, muted=is_add
                    )
                    if trailing_spaces:
                        code_toks.append((row_style, trailing_spaces))
                    return [("", indent_str), (prefix_style, pm2.group(1)), (gutter_style, pm2.group(2))] + code_toks
                if marker and (line_style is not None or re.match(r"^[+-]\s*\d+\s+", cur_r)):
                    is_add = marker.group(1).startswith("+")
                    style = "class:add" if is_add else "class:del"
                    fg_cls = "class:add_fg" if is_add else "class:del_fg"
                    target_lang = (line_style[1] if line_style is not None else "") or "python"
                    if target_lang in ("diff", "patch", ""):
                        target_lang = "html" if ("<" in cur_r and ">" in cur_r) else "python"
                    code_toks = _lex_pygments_code(
                        marker.group(2), "", target_lang, style, muted=is_add
                    )
                    if trailing_spaces:
                        code_toks.append((style, trailing_spaces))
                    return [("" , indent_str), (f"{style} {fg_cls}", marker.group(1)[:1]), (style, marker.group(1)[1:])] + code_toks

                context = re.match(r"^(\s*\d{1,6}\s+)(.*)$", cur_r)
                if context and (line_style is not None or re.match(r"^\s*\d{1,6}\s+[<{\[a-zA-Z_/]", cur_r)):
                    target_lang = (line_style[1] if line_style is not None else "") or "python"
                    if target_lang in ("diff", "patch", ""):
                        target_lang = "html" if ("<" in cur_r and ">" in cur_r) else "python"
                    code_toks = _lex_pygments_code(
                        context.group(2), "", target_lang, muted=True
                    )
                    if trailing_spaces:
                        code_toks.append(("", trailing_spaces))
                    return [("", indent_str), ("class:diff_lineno", context.group(1))] + code_toks

                if line_style is not None:
                    stype, slang = line_style
                    if stype == "diff":
                        return _parse_semantic_line(cur, indent_str, bold_open=(lineno in bold_open_lines))
            if lineno in skill_seed_lines:
                stripped_seed = line.lstrip()
                leading = line[: len(line) - len(stripped_seed)]
                if "SKILL SEED" in stripped_seed:
                    return [("", leading), ("class:skill_seed bold", stripped_seed)]
                symbol = stripped_seed[:1]
                body = stripped_seed[1:].lstrip()
                space = stripped_seed[1 : len(stripped_seed) - len(body)]
                return [
                    ("", leading),
                    ("class:skill_seed_rail", symbol),
                    ("", space),
                    ("class:skill_seed_rail", body),
                ]
            if lineno in user_lines:
                return [("class:user", line)]
            stripped = line.lstrip()
            if not stripped:
                return [("class:primary", line)]
            elif (line.startswith("  ╭─ hund ") or line.startswith("  +- hund ")) and not line.endswith("╮") and not line.endswith("+"):
                sym = "╭─" if "╭─" in line else "+-"
                idx = line.find(sym)
                leading = line[:idx]
                return [
                    ("", leading),
                    ("class:secondary", sym),
                    ("class:secondary", " hund "),
                    ("class:secondary", line[idx + len(sym) + len(" hund ") :]),
                ]
            elif (line.startswith("  │ ") or line.startswith("  | ")) and not is_box:
                sym = "│" if "│" in line else "|"
                idx = line.find(sym)
                leading = line[:idx]
                text_content = line[idx + len(sym) + 1 :]
                return [
                    ("", leading),
                    ("class:secondary", sym),
                    ("", " "),
                    ("class:primary", text_content),
                ]
            elif stripped.startswith("┊") or stripped.startswith("|"):
                sym = "┊" if "┊" in stripped else "|"
                idx = line.find(sym)
                leading = line[:idx]
                tokens: list[tuple[str, str]] = []
                if leading:
                    tokens.append(("", leading))
                tokens.append(("class:secondary", sym))
                rest = line[idx + len(sym) :]
                if not rest.strip():
                    if rest:
                        tokens.append(("", rest))
                    return tokens
                if rest.startswith(" "):
                    tokens.append(("class:secondary", " "))
                    rest = rest[1:]
                symbol_style = "class:primary"
                if rest.startswith("⟳") or rest.startswith("*"):
                    tokens.append(("class:tool", rest[0]))
                    rest = rest[1:]
                    symbol_style = "class:tool"
                elif rest.startswith("✓") or rest.startswith("+"):
                    tokens.append(("class:success", rest[0]))
                    rest = rest[1:]
                    symbol_style = "class:primary"
                elif rest.startswith("✗") or rest.startswith("x") or rest.startswith("⊘"):
                    tokens.append(("class:danger", rest[0]))
                    rest = rest[1:]
                    symbol_style = "class:danger"

                # Split metadata suffix (e.g. " · 0.6s")
                meta_part = ""
                if " · " in rest:
                    main_part, meta_part = rest.rsplit(" · ", 1)
                else:
                    main_part = rest

                # Detail error/blocked reason (e.g. " — blocked / denied")
                detail_part = ""
                if " — " in main_part:
                    main_part, detail_part = main_part.split(" — ", 1)

                # Parse verb vs target/path/command in main_part
                if main_part.startswith(" "):
                    tokens.append(("class:secondary", " "))
                    main_part = main_part[1:]

                parts = main_part.split(" ", 1)
                if len(parts) == 2:
                    verb, target = parts
                    tokens.append(("class:secondary", verb))
                    tokens.append(("class:secondary", " "))
                    tokens.append(("class:secondary", target))
                else:
                    tokens.append(("class:secondary", main_part))

                if detail_part:
                    tokens.append(("class:secondary", " — "))
                    tokens.append(("class:danger", detail_part))

                if meta_part:
                    tokens.append(("class:secondary", " · " + meta_part))

                return tokens
            elif line.startswith("  ╰─ ") or (line.startswith("╰─ ") and not line.endswith("╯")) or line.startswith("  +- ") or (line.startswith("+- ") and not line.endswith("+")):
                sym = "╰─" if "╰─" in line else "+-"
                idx = line.find(sym)
                leading = line[:idx]
                tokens = [("", leading)] if leading else []
                tokens.append(("class:secondary", sym))
                rest = line[idx + len(sym) :]
                style = "class:danger" if "stopped" in rest else "class:secondary"
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
                border_cls = "class:interim_border" if line_style and line_style[0] == "interim" else "class:secondary"
                hund_cls = "class:interim_border bold" if line_style and line_style[0] == "interim" else "class:accent bold"
                return [
                    (border_cls, line[:idx]),
                    (hund_cls, "hund"),
                    (border_cls, line[idx + 4 :]),
                ]
            elif line.startswith("└") or line.startswith("╰"):
                border_cls = "class:interim_border" if line_style and line_style[0] == "interim" else "class:secondary"
                meta_match = re.search(
                    r"^(.*?─\s+)([0-9.]+(?:s|ms|m|h)?|\w+)(\s+─+[┘╯]|─+[┘╯]|[┘╯])$",
                    line,
                )
                if meta_match:
                    return [
                        (border_cls, meta_match.group(1)),
                        ("class:accent bold", meta_match.group(2)),
                        (border_cls, meta_match.group(3)),
                    ]
                return [(border_cls, line)]
            elif line.startswith("│") and line.endswith("│"):
                if not line.strip("│ "):
                    border_cls = "class:interim_border" if line_style and line_style[0] == "interim" else "class:secondary"
                    return [(border_cls, line)]

                if line.startswith("│   ") and line.endswith("   │") and len(line) >= 8:
                    pad_str = "│   "
                    end_str = "   │"
                    content = line[4:-4]
                elif line.startswith("│  ") and line.endswith("  │") and len(line) >= 6:
                    pad_str = "│  "
                    end_str = "  │"
                    content = line[3:-3]
                elif line.startswith("│ ") and line.endswith(" │") and len(line) >= 4:
                    pad_str = "│ "
                    end_str = " │"
                    content = line[2:-2]
                else:
                    pad_str = "│"
                    end_str = "│"
                    content = line[1:-1]

                indent_len = len(content) - len(content.lstrip())
                indent_str = content[:indent_len]
                cur = content.lstrip()

                line_style = registry.get_line_style(lineno)
                if line_style is not None:
                    stype, slang = line_style
                    if stype == "interim":
                        parsed = [("class:interim_text", cur)]
                    elif stype == "code":
                        if cur.startswith("──"):
                            parsed = [("class:secondary", indent_str), ("class:accent bold", cur)]
                        elif cur.startswith("─") and set(cur.strip()) == {"─"}:
                            parsed = [("class:secondary", indent_str), ("class:secondary", cur)]
                        else:
                            parsed = _lex_pygments_code(cur, indent_str, slang or "python")
                    elif stype == "table":
                        if slang == "sep" or set(cur.strip()) <= {"|", "-", "+", "┼", "─"}:
                            parsed = [("class:secondary", indent_str), ("class:secondary", cur)]
                        elif slang == "header":
                            parts = cur.split("|")
                            toks: list[tuple[str, str]] = [("class:secondary", indent_str)]
                            for p_idx, part in enumerate(parts):
                                if p_idx > 0:
                                    toks.append(("class:secondary", "|"))
                                toks.append(("class:accent bold", part))
                            parsed = toks
                        else:
                            parts = cur.split("|")
                            toks = [("class:secondary", indent_str)]
                            for p_idx, part in enumerate(parts):
                                if p_idx > 0:
                                    toks.append(("class:secondary", "|"))
                                toks.append(("class:primary", part))
                            parsed = toks
                    elif stype == "diff":
                        if cur.startswith("──"):
                            parsed = [("class:secondary", indent_str), ("class:accent bold", cur)]
                        elif cur.startswith("─") and set(cur.strip()) == {"─"}:
                            parsed = [("class:secondary", indent_str), ("class:secondary", cur)]
                        elif cur.startswith("└ "):
                            m_header = re.match(r"^└\s+(.*?)(?:\s+(\(\+(\d+)\s+-(\d+)\)))?$", cur)
                            if m_header:
                                fn = m_header.group(1)
                                counts = m_header.group(2)
                                toks = [("", indent_str), ("class:diff_tree", "└ "), ("class:diff_file_header", fn)]
                                if counts:
                                    adds = m_header.group(3)
                                    dels = m_header.group(4)
                                    toks.extend([
                                        ("class:secondary", "  ("),
                                        ("class:diff_stat_add", f"+{adds}"),
                                        ("class:secondary", " "),
                                        ("class:diff_stat_del", f"-{dels}"),
                                        ("class:secondary", ")"),
                                    ])
                                parsed = toks
                            else:
                                parsed = [
                                    ("", indent_str),
                                    ("class:diff_tree", "└ "),
                                    ("class:diff_file_header", cur[2:]),
                                ]
                        elif m_wrap := re.match(r"^\s*(\(\+(\d+)\s+-(\d+)\))$", cur):
                            adds = m_wrap.group(2)
                            dels = m_wrap.group(3)
                            parsed = [
                                ("", indent_str),
                                ("class:secondary", "  ("),
                                ("class:diff_stat_add", f"+{adds}"),
                                ("class:secondary", " "),
                                ("class:diff_stat_del", f"-{dels}"),
                                ("class:secondary", ")"),
                            ]
                        elif cur == "… Diff preview limited.":
                            parsed = [("", indent_str), ("class:secondary", cur)]
                        elif pm := re.match(r"^([+-])(\s*\d+\s+)(.*)$", cur):
                            is_add = pm.group(1) == "+"
                            fg_cls = "class:add_fg" if is_add else "class:del_fg"
                            row_style = "class:add" if is_add else "class:del"
                            target_lang = slang or "python"
                            if target_lang in ("diff", "patch", ""):
                                target_lang = "html" if ("<" in cur and ">" in cur) else "python"
                            parsed = [
                                ("", indent_str),
                                (fg_cls, pm.group(1)),
                                ("class:diff_lineno", pm.group(2)),
                            ] + _lex_pygments_code(pm.group(3), "", target_lang, row_style=row_style, muted=(row_style == "class:add"))
                        elif marker := re.match(r"^([+-]\s*(?:\d+\s+)?)(.*)$", cur):
                            style = "class:add" if marker.group(1).startswith("+") else "class:del"
                            fg_cls = "class:add_fg" if style == "class:add" else "class:del_fg"
                            target_lang = slang or "python"
                            if target_lang in ("diff", "patch", ""):
                                target_lang = "html" if ("<" in cur and ">" in cur) else "python"
                            parsed = [("" , indent_str), (fg_cls, marker.group(1)[:1]), (style, marker.group(1)[1:])] + _lex_pygments_code(
                                marker.group(2), "", target_lang, row_style=style, muted=(style == "class:add")
                            )
                            if not indent_str:
                                parsed = [(fg_cls, marker.group(1)[:1]), (style, marker.group(1)[1:])] + _lex_pygments_code(
                                    marker.group(2), "", target_lang, row_style=style, muted=(style == "class:add")
                                )
                        elif context := re.match(r"^(\s{2}\s*\d{1,4}\s+)(.*)$", cur):
                            target_lang = slang or "python"
                            if target_lang in ("diff", "patch", ""):
                                target_lang = "html" if ("<" in cur and ">" in cur) else "python"
                            parsed = [("", indent_str), ("class:diff_lineno", context.group(1))] + _lex_pygments_code(
                                context.group(2), "", target_lang, muted=True
                            )
                        elif cur.startswith("@@"):
                            parsed = [("class:secondary", indent_str), ("class:accent", cur)]
                        else:
                            parsed = [("class:secondary", indent_str), ("class:primary", cur)]
                    else:
                        parsed = _parse_semantic_line(cur, indent_str, bold_open=(lineno in bold_open_lines))
                else:
                    stype = None
                    parsed = _parse_semantic_line(cur, indent_str, bold_open=(lineno in bold_open_lines))

                diff = len(content) - sum(len(t[1]) for t in parsed)
                if stype == "interim" or (line_style and line_style[0] == "interim"):
                    row_style = "class:interim_border"
                elif stype == "diff" and cur.startswith(("+", "-")) and parsed and parsed[0][0] in ("class:add", "class:del"):
                    row_style = parsed[0][0]
                else:
                    row_style = "class:secondary"
                fill = [(row_style, " " * diff)] if diff > 0 else []
                return [(row_style, pad_str)] + parsed + fill + [(row_style, end_str)]
            elif stripped.startswith("#"):
                return [("class:header", line)]

            indent_len = len(line) - len(stripped)
            indent_str = line[:indent_len]
            return _parse_semantic_line(stripped, indent_str, bold_open=(lineno in bold_open_lines))

        return get_line


class _SelectableControl(BufferControl):
    """Output control: wheel scroll via the view-scroll callback, and
    single-drag selection (focus on mouse-down instead of mouse-up)."""

    def __init__(
        self,
        *args,
        scroll_cb=None,
        fallback_focus=None,
        tail_follow_getter=None,
        padding_getter=None,
        view_scroll_getter=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.scroll_cb = scroll_cb
        self.fallback_focus = fallback_focus
        self.tail_follow_getter = tail_follow_getter
        self.padding_getter = padding_getter
        self.view_scroll_getter = view_scroll_getter
        self._last_click_timestamp = 0.0

    def create_content(self, width: int, height: int | None) -> Any:
        content = super().create_content(width, height)
        orig_get_line = content.get_line
        orig_line_count = content.line_count
        extra_padding = self.padding_getter() if self.padding_getter is not None else 0
        tail_follow = self.tail_follow_getter() if self.tail_follow_getter is not None else False
        view_row = None
        if self.buffer.selection_state is not None and self.view_scroll_getter is not None:
            try:
                view_row = max(0, int(self.view_scroll_getter()))
            except (TypeError, ValueError):
                pass

        if extra_padding > 0 and orig_line_count > 0:
            def get_line(i: int):
                if i < orig_line_count:
                    return orig_get_line(i)
                return []

            cur_pos = content.cursor_position
            if tail_follow:
                cur_pos = Point(x=0, y=orig_line_count + extra_padding - 1)
            elif view_row is not None:
                cur_pos = Point(x=0, y=min(view_row, orig_line_count - 1))
            elif self.buffer.selection_state is None:
                cur_pos = Point(x=0, y=cur_pos.y if cur_pos else 0)

            return UIContent(
                get_line=get_line,
                line_count=orig_line_count + extra_padding,
                cursor_position=cur_pos,
                show_cursor=content.show_cursor,
            )
        else:
            if view_row is not None and orig_line_count > 0:
                content.cursor_position = Point(x=0, y=min(view_row, orig_line_count - 1))
            elif self.buffer.selection_state is None:
                orig_cursor = content.cursor_position
                if orig_cursor is not None:
                    content.cursor_position = Point(x=0, y=orig_cursor.y)
            return content

    def mouse_handler(self, mouse_event: MouseEvent) -> Any:
        et = mouse_event.event_type
        if et in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
            if self.scroll_cb is not None:
                self.scroll_cb(3 if et == MouseEventType.SCROLL_UP else -3)
            return None

        buffer = self.buffer
        position = mouse_event.position

        if et == MouseEventType.MOUSE_DOWN:
            try:
                get_app().layout.current_control = self
            except Exception:
                pass

        if get_app().layout.current_control == self:
            if self._last_get_processed_line:
                processed_line = self._last_get_processed_line(position.y)
                xpos = processed_line.display_to_source(position.x)

                # Window already translates screen coordinates to document coordinates.
                index = buffer.document.translate_row_col_to_index(position.y, xpos)

                if et == MouseEventType.MOUSE_DOWN:
                    buffer.exit_selection()
                    buffer.cursor_position = index
                    return None

                elif (
                    et == MouseEventType.MOUSE_MOVE
                    and mouse_event.button != MouseButton.NONE
                ):
                    if (
                        buffer.selection_state is None
                        and abs(buffer.cursor_position - index) > 0
                    ):
                        buffer.start_selection(selection_type=SelectionType.CHARACTERS)
                    buffer.cursor_position = index
                    return None

                elif et == MouseEventType.MOUSE_UP:
                    if abs(buffer.cursor_position - index) > 1:
                        if buffer.selection_state is None:
                            buffer.start_selection(selection_type=SelectionType.CHARACTERS)
                        buffer.cursor_position = index

                    now = time.time()
                    double_click = (
                        self._last_click_timestamp
                        and now - self._last_click_timestamp < 0.35
                    )
                    self._last_click_timestamp = now

                    if double_click:
                        start, end = buffer.document.find_boundaries_of_current_word()
                        buffer.cursor_position += start
                        buffer.start_selection(selection_type=SelectionType.CHARACTERS)
                        buffer.cursor_position += end - start

                    if buffer.selection_state is None and self.fallback_focus is not None:
                        try:
                            focus_target = (
                                self.fallback_focus()
                                if callable(self.fallback_focus)
                                else self.fallback_focus
                            )
                            if focus_target is not None:
                                get_app().layout.focus(focus_target)
                        except Exception:
                            pass
                    return None

        return None


class _MinimalScrollbarMargin(ScrollbarMargin):
    """Windows Terminal-minimal scrollbar margin with auto-hide."""

    def __init__(
        self,
        tail_follow_getter: Callable[[], bool] | None = None,
        view_scroll_getter: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(display_arrows=False)
        self.tail_follow_getter = tail_follow_getter
        self.view_scroll_getter = view_scroll_getter

    def get_width(self, get_ui_content: Any) -> int:
        return 1

    def create_margin(
        self, window_render_info: WindowRenderInfo, width: int, height: int
    ) -> StyleAndTextTuples:
        content_height = window_render_info.content_height
        window_height = window_render_info.window_height
        if window_height <= 0 or content_height <= 0:
            return []

        max_scroll = max(0, content_height - window_height)
        is_tail = self.tail_follow_getter() if self.tail_follow_getter is not None else False
        is_scrolled_up = (not is_tail) and (window_render_info.vertical_scroll < max_scroll)

        if not is_scrolled_up:
            result: StyleAndTextTuples = []
            for _ in range(window_height):
                result.append(("", " "))
                result.append(("", "\n"))
            return result

        try:
            fraction_visible = len(window_render_info.displayed_lines) / float(content_height)
            fraction_above = window_render_info.vertical_scroll / float(content_height)
            scrollbar_height = min(window_height, max(1, int(window_height * fraction_visible)))
            scrollbar_top = int(window_height * fraction_above)
            scrollbar_top = min(scrollbar_top, max(0, window_height - scrollbar_height))
        except ZeroDivisionError:
            scrollbar_height = window_height
            scrollbar_top = 0

        def is_scroll_button(row: int) -> bool:
            return scrollbar_top <= row < (scrollbar_top + scrollbar_height)

        result = []
        for i in range(window_height):
            if is_scroll_button(i):
                result.append(("class:scrollbar.button", " "))
            else:
                result.append(("class:scrollbar.background", " "))
            result.append(("", "\n"))
        return result


_CONFIRM_COLORS = {
    ConfirmVerdict.APPROVE_ONCE: "class:success",
    ConfirmVerdict.EDIT: "class:accent",
    ConfirmVerdict.ALLOW_TURN: "class:warning",
    ConfirmVerdict.ALLOW_SESSION: "class:warning",
    ConfirmVerdict.DENY: "class:danger",
}


def _confirm_options(
    tool_name: str, *, session_allowable: bool = True, turn_allowable: bool = False
):
    return [
        (v, label, _CONFIRM_COLORS[v])
        for v, label in confirmation_options(
            tool_name, session_allowable=session_allowable, turn_allowable=turn_allowable
        )
    ]


def _discard_console(width: int = 100) -> Console:
    """Rich console that discards output (agent turn only talks through the sink)."""
    return Console(file=io.StringIO(), color_system=None, force_terminal=False, width=width)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


def create_fullscreen_app(
    rt,
    state,
    *,
    banner: str = "",
    session_id: str = "session",
    output: Any = None,
    input: Any = None,
) -> tuple[Application, dict[str, Any]]:
    """Build and return the Prompt Toolkit application and internal closure state."""
    _MODAL_ACTIVE[0] = False
    screens = ScreenController()
    screen_snapshots: dict[str, Any] = {}
    modal_editor = ModalTextEditor()
    model_options: list[Any] = []
    auth_target_provider: dict[str, str] = {}
    custom_wizard_data: dict[str, str] = {}
    custom_step = [0]

    def _manage_entries() -> list[tuple[str, str, str, str]]:
        entries = []
        for preset in PROVIDER_PRESETS:
            if preset.provider_id == "custom":
                continue
            cred_state, env_var = get_credential_status(preset.credential_id, preset.env_name)
            if cred_state == "environment":
                badge = "[Environment]"
                detail = f"Controlled by {env_var} environment variable (cannot be modified via vault)"
            elif cred_state == "configured":
                badge = "[Configured]"
                detail = "Key saved in Windows Credential Manager"
            else:
                badge = "[Needs key]"
                detail = "No credential saved"
            model_summary = preset.default_models[0] if preset.default_models else ""
            entries.append((preset.name, model_summary, badge, detail))
        for ep in getattr(rt.cfg, "custom_endpoints", []):
            cred_state, env_var = get_credential_status(ep.credential_id, "HUND_API_KEY")
            badge = "[Configured]" if cred_state in ("configured", "environment") else "[Needs key]"
            entries.append((ep.name, ep.model_id, badge, f"Base URL: {ep.base_url}"))
        return entries

    # ---- output buffer (read-only + focusable so the mouse can select) ----
    block_registry = ResponseBlockRegistry()
    output_lexer = _OutputLexer(block_registry=block_registry)
    output_buffer = Buffer(name="output", multiline=True, read_only=True)
    output_control = _SelectableControl(
        buffer=output_buffer,
        lexer=output_lexer,
        fallback_focus=lambda: input_window,
        tail_follow_getter=lambda: tail_following[0],
        padding_getter=lambda: 7 if _app_height() >= 27 and screens.destination is DestinationView.CHAT else 0,
        view_scroll_getter=lambda: output_window.vertical_scroll,
    )
    output_window = Window(
        content=output_control,
        wrap_lines=False,
        always_hide_cursor=True,
        dont_extend_height=False,
        height=Dimension(weight=1),
        right_margins=[
            _MinimalScrollbarMargin(
                tail_follow_getter=lambda: tail_following[0],
                view_scroll_getter=lambda: output_window.vertical_scroll,
            )
        ],
    )

    # ---- input buffer + prompt ----
    history_path = hund_home() / "repl_history"
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    repl_history = FileHistory(str(history_path))

    ws = getattr(rt, "workspace", None) or Path.cwd()
    completer = SlashCommandCompleter(ws)
    auto_suggest = AutoSuggestFromHistory()
    try:
        _hist_strings = [s for s in repl_history.load_history_strings() if s]
    except Exception:
        _hist_strings = []

    input_buffer = Buffer(
        name="input",
        multiline=True,
        completer=completer,
        history=repl_history,
        auto_suggest=auto_suggest,
        complete_while_typing=True,
        enable_history_search=False,
    )
    if _hist_strings:
        input_buffer._working_lines = deque(_hist_strings + [""])
        input_buffer.working_index = len(input_buffer._working_lines) - 1

    paste_folded = [False]

    def _input_height() -> int:
        if paste_folded[0]:
            return 1
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
        return min(max(total_rows, 1), 6)

    input_control = BufferControl(buffer=input_buffer, focus_on_click=True)
    input_window = Window(
        content=input_control,
        height=_input_height,
        dont_extend_height=True,
        wrap_lines=True,
    )
    prompt_window = Window(
        content=FormattedTextControl(lambda: [("class:prompt", "  ❯ ")]),
        width=4,
        dont_extend_width=True,
        height=_input_height,
        dont_extend_height=True,
    )
    input_row = VSplit([prompt_window, input_window])
    completion_container = _FullWidthCompletionsMenu(
        max_height=MAX_VISIBLE_COMPLETIONS
    )

    output_control.fallback_focus = input_window

    # ---- status bar ----
    turn_running = [False]
    transient_notice: list[Any] = ["", 0.0]

    def set_status_notice(msg: str, duration: float = 2.0) -> None:
        transient_notice[0] = msg
        transient_notice[1] = time.monotonic() + duration
        _invalidate()

    def status_text() -> list[tuple[str, str]]:
        model = state.extra.get("model", "deepseek-v4-flash")
        tokens = state.extra.get("tokens", 0)
        limit = state.extra.get("token_limit", 1_000_000)
        dur = time.time() - state.start_time
        lat = state.extra.get("last_latency_s", 0.0) if turn_running[0] else None

        cleaned_model = model
        if "(" in model and ")" in model:
            cleaned_model = model.split("(")[-1].split(")")[0].strip()
        if not cleaned_model:
            cleaned_model = "deepseek-v4-flash"

        token_str = format_tokens_ratio(tokens, limit)
        duration_str = format_duration(dur)

        segments: list[tuple[str, str]] = [
            ("class:header", "  " + cleaned_model),
            ("class:status", f" │ {token_str} │ {duration_str}"),
        ]
        if lat is not None and lat > 0:
            segments.append(("class:status", f" │ {lat:.1f}s"))
        if transient_notice[0] and time.monotonic() < transient_notice[1]:
            segments.append(("class:accent bold", f" │ {transient_notice[0]}"))
        return segments

    status_window = Window(content=FormattedTextControl(status_text), height=1)

    mascot_machine = MascotMachine()

    def _mascot_text() -> list[tuple[str, str]]:
        tint, art = mascot_machine.frame(getattr(state, "theme_name", "marshmallow"))
        # Sprite sheets contain a shared blank top row. Dropping only that row
        # reduces the chat/mascot boundary while preserving the feet baseline.
        art = mirror_art(art.removeprefix("\n"))
        if _MODAL_ACTIVE[0]:
            return [("class:backdrop", art)]
        return [(f"class:mascot fg:{tint}", art)]

    mascot_window = _TransparentSpriteWindow(
        _mascot_text,
        scroll_cb_getter=lambda: output_control.scroll_cb,
        width=13,
        height=7,
    )

    def _mascot_status_text() -> list[tuple[str, str]]:
        if not turn_running[0] or _MODAL_ACTIVE[0]:
            return []
        skin = theme.get_skin(getattr(state, "theme_name", "marshmallow"))
        color = skin["tokens"].get("mascot_status", skin["tokens"]["secondary"])
        dot_count = (
            3 if getattr(rt.cfg, "reduced_motion", False)
            else int(time.monotonic() / 0.32) % 3 + 1
        )
        dots = ("." * dot_count).ljust(3)
        phase = int(time.monotonic() / 0.10)
        return _shine_fragments(f"running{dots}", color, phase)

    mascot_status_window = _TransparentSpriteWindow(
        _mascot_status_text,
        scroll_cb_getter=lambda: output_control.scroll_cb,
        width=12,
        height=1,
    )
    mascot_status_container = ConditionalContainer(
        mascot_status_window,
        filter=Condition(
            lambda: _app_height() >= 27
            and turn_running[0]
            and screens.destination is DestinationView.CHAT
            and not _MODAL_ACTIVE[0]
        ),
    )
    mascot_container = ConditionalContainer(
        mascot_window,
        filter=Condition(
            lambda: _app_height() >= 27
            and screens.destination is DestinationView.CHAT
        ),
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
        reason = _confirm.get("reason", "Approval required")
        row(f"  Why: {reason}", "class:secondary")
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

    confirm_window = Window(
        content=FormattedTextControl(_confirm_text),
        dont_extend_height=True,
        dont_extend_width=True,
    )
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

    doctor_review_fixes = [False]

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
        if destination is DestinationView.SYSTEM:
            return render_system(
                snapshot, width=width, height=height,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if destination is DestinationView.DOCTOR:
            return render_doctor(
                snapshot, width=width, height=height,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
                review_fixes=bool(doctor_review_fixes[0]),
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
        if overlay is OverlayView.AUTH:
            return render_auth_modal(
                screens.selected.get("auth", 0),
                width,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.AUTH_ADD:
            return render_auth_add_modal(
                PROVIDER_PRESETS,
                screens.selected.get("auth_add", 0),
                width,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.AUTH_MANAGE:
            entries = _manage_entries()
            return render_auth_manage_modal(
                entries,
                screens.selected.get("auth_manage", 0),
                width,
                screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.AUTH_KEY:
            target_name = auth_target_provider.get("name", "Provider")
            return render_model_key_modal(
                target_name,
                modal_editor.get_masked(),
                width,
                screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.AUTH_CUSTOM:
            return render_auth_custom_wizard_modal(
                custom_step[0],
                custom_wizard_data,
                modal_editor.get_raw(),
                width,
                screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.AUTH_FORGET_CONFIRM:
            target_name = auth_target_provider.get("name", "Provider")
            return render_auth_forget_modal(
                target_name,
                width,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.MODEL_CUSTOM:
            return render_model_custom_modal(
                modal_editor.get_raw(), width, screens.status,
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
        if overlay is OverlayView.MODEL_KEY:
            selected = screens.selected.get("model", 0)
            option = model_options[selected] if model_options else active_option(rt.cfg)
            return render_model_key_modal(
                option.provider_name, modal_editor.get_masked(), width, screens.status,
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
            lambda: screens.overlay is not OverlayView.NONE
            and screens.overlay is not OverlayView.CONFIRM
        ),
    )

    authoring_view: list[Any | None] = [None]
    authoring_selected = [0]
    authoring_anchor: list[int | None] = [None]
    authoring_span: list[tuple[int, int] | None] = [None]

    def _authoring_fragments() -> list[tuple[str, str]]:
        view = authoring_view[0]
        if view is None:
            return []
        from .skill_authoring import render_authoring_stepper

        rendered = render_authoring_stepper(
            view,
            selected_index=authoring_selected[0],
            width=_responsive_content_width(_app_width()),
            ascii_only=getattr(rt.cfg, "ascii_ui", False),
        )
        fragments: list[tuple[str, str]] = []
        lines = rendered.splitlines()
        selected_lines_remaining = 0
        if getattr(view, "options", None):
            from .unicode_cells import cell_width, wrap_cells
            selected_idx = authoring_selected[0] % len(view.options)
            sel_opt = view.options[selected_idx]
            width = _responsive_content_width(_app_width())
            rail = "|" if getattr(rt.cfg, "ascii_ui", False) else "│"
            indent = "  "
            prefix = f"{indent}{rail}  "
            body_width = max(16, width - cell_width(prefix) - 2)
            marker = ">" if getattr(rt.cfg, "ascii_ui", False) else "›"
            wrapped_opt = wrap_cells(f"{marker} {sel_opt.label}", body_width)
            selected_lines_total = len(wrapped_opt)
        else:
            selected_lines_total = 1

        for index, line in enumerate(lines):
            suffix = "\n" if index < len(lines) - 1 else ""
            if index == 0:
                fragments.append(("class:growth_gold bold", line + suffix))
                continue
            rail_prefix = next(
                (prefix for prefix in ("  │  ", "  |  ") if line.startswith(prefix)),
                "",
            )
            if rail_prefix:
                fragments.append(("class:growth_gold", rail_prefix))
                body = line[len(rail_prefix):]
                if body.startswith(("› ", "> ")):
                    selected_lines_remaining = max(0, selected_lines_total - 1)
                    body_style = "class:growth_gold bold"
                elif selected_lines_remaining > 0:
                    selected_lines_remaining -= 1
                    body_style = "class:growth_gold bold"
                else:
                    if body == getattr(view, "title", ""):
                        body_style = "class:growth_gold bold"
                    elif body == getattr(view, "description", "") or body.startswith(("Choose what happens", "Type your answer", "Describe the workflow")):
                        body_style = "class:growth_cream"
                    elif body.startswith(("SCOPE", "LIMITATION")):
                        body_style = "class:growth_brass"
                    else:
                        body_style = "class:secondary"
                fragments.append((body_style, body + suffix))
                continue
            selected_lines_remaining = 0
            style = (
                "class:growth_gold"
                if line.lstrip().startswith(("└", "`"))
                else "class:secondary"
            )
            fragments.append((style, line + suffix))
        return fragments

    def _move_authoring_selection(delta: int) -> None:
        view = authoring_view[0]
        if view is None or not view.options:
            return
        authoring_selected[0] = (
            authoring_selected[0] + delta
        ) % len(view.options)
        _sync_authoring_inline()
        _invalidate()

    authoring_window = Window(
        content=FormattedTextControl(_authoring_fragments),
        height=Dimension(min=1, max=18),
        dont_extend_height=True,
        wrap_lines=False,
        always_hide_cursor=True,
    )
    authoring_container = ConditionalContainer(
        authoring_window,
        filter=Condition(
            lambda: authoring_view[0] is not None
            and screens.destination is DestinationView.CHAT
            and screens.overlay is OverlayView.NONE
            and not _confirm.get("active")
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
                # Mascot floats over the transcript bottom-right instead of
                # reserving a full-width row. A conditional 7-row gap below
                # the transcript reserves mascot space while at the bottom;
                # scrolled up, the transparent float only covers its pixels.
                FloatContainer(
                    content=output_window,
                    floats=[
                        Float(content=mascot_status_container, left=2, bottom=0, transparent=True),
                        Float(content=mascot_container, right=0, bottom=0, transparent=True),
                    ],
                ),
                input_border_top,
                input_row,
                completion_container,
                input_border_bottom,
                status_window,
            ]),
            floats=[
                Float(content=screen_container, left=0, right=0, top=0, bottom=0),
                Float(content=overlay_container, transparent=True),
                Float(
                    content=confirm_container,
                    transparent=True,
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
    block_id_seq = [0]

    def _next_app_block_id() -> int:
        block_id_seq[0] += 1
        return block_id_seq[0]

    payload_by_id: dict[int, ResponsePayloadRecord] = {}
    response_payloads: list[ResponsePayloadRecord] = []
    active_response: list[ResponsePayloadRecord | None] = [None]
    active_skill_seed: list[Any | None] = [None]
    editing_skill_seed: list[Any | None] = [None]
    skill_seed_focused = [False]
    rendered_skill_seed = [""]

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

    def append(text: str, *, follow_tail: bool = True) -> None:
        if not text:
            return
        with _append_lock:
            prev_scroll = getattr(output_window, "vertical_scroll", 0)
            new_text = output_buffer.text + text
            _set_output(new_text, follow_tail=follow_tail)
            if not follow_tail:
                output_window.vertical_scroll = prev_scroll
        _invalidate()

    def _render_inline_authoring() -> str:
        view = authoring_view[0]
        if view is None:
            return ""
        from .skill_authoring import render_authoring_stepper

        return render_authoring_stepper(
            view,
            selected_index=authoring_selected[0],
            width=_content_width(),
            ascii_only=getattr(rt.cfg, "ascii_ui", False),
        )

    def _sync_authoring_inline(
        rendered: str | None = None, *, permanent: bool = False
    ) -> None:
        """Replace one typed authoring span inside the scrollable transcript."""
        content = _render_inline_authoring() if rendered is None else rendered
        with _append_lock:
            current = output_buffer.text
            span = authoring_span[0]
            if span is None:
                start = authoring_anchor[0]
                if start is None or start < 0 or start > len(current):
                    start = len(current)
                end = start
            else:
                start, end = span
                if not (0 <= start <= end <= len(current)):
                    start = end = len(current)
            replacement = content.rstrip("\n") + "\n\n" if content else ""
            updated = current[:start] + replacement + current[end:]
            _set_output(updated, follow_tail=tail_following[0])
            if permanent or not replacement:
                authoring_span[0] = None
                authoring_anchor[0] = None
            else:
                authoring_span[0] = (start, start + len(replacement))
                authoring_anchor[0] = start
        _invalidate()

    # seed banner
    from .render import build_startup_banner
    def _banner_width() -> int:
        return _content_width()

    actual_width = _banner_width()
    rendered_banner = build_startup_banner(rt, width=actual_width)
    seed = rendered_banner.rstrip("\n") + "\n\n"
    _set_output(seed, follow_tail=False)

    def _reflow_non_response_lines(sub_lines: list[str]) -> list[str]:
        """Reflow banner and special panels in non-response line slices."""
        out: list[str] = []
        in_panel = False
        panel_lines: list[str] = []
        app_w = _banner_width()
        for line in sub_lines:
            if line.startswith("╔") and line.endswith("╗"):
                in_panel = True
                panel_lines = [line]
            elif in_panel and (line.startswith("╚") and line.endswith("╝")):
                in_panel = False
                panel_lines.append(line)
                panel_text = "\n".join(panel_lines)
                if "── MOTOR SKILLS" in panel_text or "── DOMAIN SKILLS" in panel_text:
                    from .skills_view import render_skills_panel
                    new_panel = render_skills_panel(rt, width=app_w)
                    out.extend(new_panel.split("\n"))
                elif "SKILL DETAIL:" in panel_text:
                    from .skills_view import render_skill_detail
                    sk_name = ""
                    for pl in panel_lines:
                        if "SKILL DETAIL:" in pl:
                            sk_name = pl.split("SKILL DETAIL:")[-1].strip(" ║│═").strip()
                            break
                    if sk_name:
                        new_panel = render_skill_detail(sk_name, rt, width=app_w)
                        out.extend(new_panel.split("\n"))
                    else:
                        out.extend(panel_lines)
                elif "OS      " in panel_text or "── BASE ATTRIBUTES ──" in panel_text or "HUND AI" in panel_text:
                    new_banner = build_startup_banner(rt, width=app_w)
                    out.extend(new_banner.split("\n"))
                else:
                    out.extend(panel_lines)
            elif in_panel:
                panel_lines.append(line)
            else:
                out.append(line)
        if in_panel:
            out.extend(panel_lines)
        return out

    def _reflow_borders() -> None:
        """Re-width response box borders and re-wrap content using registry spans without string scanning."""
        with _append_lock:
            text = output_buffer.text
            had_inline_authoring = False
            inline_span = authoring_span[0]
            if inline_span is not None and authoring_view[0] is not None:
                inline_start, inline_end = inline_span
                if 0 <= inline_start <= inline_end <= len(text):
                    text = text[:inline_start] + text[inline_end:]
                    had_inline_authoring = True
                    authoring_span[0] = None
            lines = text.split("\n")
            doc_len = len(lines)
            records = block_registry.records()
            cw = _content_width()

            old_lines = len(lines)
            prev_scroll = getattr(output_window, "vertical_scroll", 0)
            dist = max(0, old_lines - 1 - prev_scroll)

            # Validate spans: strictly ascending, non-overlapping, in-bounds
            is_valid = True
            last_span_end = 0
            for rec in records:
                if rec.start_line < last_span_end or rec.start_line + rec.line_count > doc_len or rec.line_count <= 0:
                    is_valid = False
                    break
                last_span_end = rec.start_line + rec.line_count

            if not is_valid:
                # Malformed/stale span fallback: preserve visible text, reflow panels safely
                reflowed_plain = _reflow_non_response_lines(lines)
                block_registry.clear()
                if reflowed_plain != lines or had_inline_authoring:
                    new_text = "\n".join(reflowed_plain)
                    if had_inline_authoring:
                        rendered = _render_inline_authoring().rstrip("\n") + "\n\n"
                        start = len(new_text)
                        new_text += rendered
                        authoring_anchor[0] = start
                        authoring_span[0] = (start, start + len(rendered))
                    _set_output(new_text, follow_tail=tail_following[0])
                    if not tail_following[0]:
                        new_lines_count = new_text.count("\n") + 1
                        output_window.vertical_scroll = max(0, new_lines_count - 1 - dist)
                    _invalidate()
                return

            new_lines: list[str] = []
            new_registry = ResponseBlockRegistry()
            last_idx = 0

            for rec in records:
                # 1. Non-response lines before this response box span
                if rec.start_line > last_idx:
                    before_lines = _reflow_non_response_lines(lines[last_idx:rec.start_line])
                    new_lines.extend(before_lines)

                # 2. Re-render the response box using stable block_id payload
                payload = payload_by_id.get(rec.block_id)
                if payload is not None:
                    re_boxed, line_meta = render_response_box_from_segments(payload.segments, cw, meta=payload.meta)
                    re_lines = re_boxed.split("\n")
                    new_start = len(new_lines)
                    new_count = len(re_lines)
                    new_registry.register_or_update(rec.block_id, new_start, new_count, line_meta)
                    new_lines.extend(re_lines)
                else:
                    # Artifact blocks have no response payload; regenerate their width.
                    orig_block = lines[rec.start_line:rec.start_line + rec.line_count]
                    if any(meta[0] == "diff" for meta in rec.line_metadata.values()):
                        from .render import repad_diff_block
                        orig_block = repad_diff_block(orig_block, cw)
                    new_registry.register_or_update(rec.block_id, len(new_lines), len(orig_block), rec.line_metadata)
                    new_lines.extend(orig_block)

                last_idx = rec.start_line + rec.line_count

            # 3. Trailing non-response lines after the last response box span
            if last_idx < doc_len:
                after_lines = _reflow_non_response_lines(lines[last_idx:])
                new_lines.extend(after_lines)

            new_text = "\n".join(new_lines)
            if had_inline_authoring:
                rendered = _render_inline_authoring().rstrip("\n") + "\n\n"
                start = len(new_text)
                new_text += rendered
                authoring_anchor[0] = start
                authoring_span[0] = (start, start + len(rendered))
            block_registry.replace_from(new_registry)
            _set_output(new_text, follow_tail=tail_following[0])
            if not tail_following[0]:
                new_lines_count = new_text.count("\n") + 1
                output_window.vertical_scroll = max(0, new_lines_count - 1 - dist)
            _invalidate()

    messages = getattr(rt, "messages", [])
    frozen = messages[0].content if messages else ""

    active_sink: list[Any] = [None]

    # ---- sink (called from the agent worker thread) ----
    class _Sink:
        def __init__(self) -> None:
            self._cancelled = False
            self._box_open = False
            self._box_start_marker: int | None = None
            self._block_id = _next_app_block_id()
            self._tool_marker: int | None = None
            self._tool_start_time: float = 0.0
            self._tool_args: dict = {}
            self._activity = ActivityTimeline()
            self._activity_marker: int | None = None
            self._activity_end: int | None = None
            self._activity_prefix = ""
            self._active_tool_event_id: int | None = None
            self._pending_confirmation_tool: str | None = None
            self._tool_switched = False
            self._user_input = ""
            self._turn_start_time: float = 0.0
            self._pending_past_timer: threading.Timer | None = None
            self._md = StreamingMarkdownFilter(content_width=_content_width())
            self._snapshot = None
            self._learning_markers: dict[str, int] = {}
            self._authoring_mode = False
            self._revealed_len: int = 0
            self._reveal_generation: int = 0
            self._reveal_cancel = threading.Event()
            self._reveal_thread: threading.Thread | None = None
            self._current_boxed: str = ""
            self._current_line_meta: dict[int, tuple[str, str]] = {}
            self._in_tool_loop = False
            self._intermediate_marker: int | None = None
            self._intermediate_end: int | None = None
            active_sink[0] = self

        def reveal_now(self) -> None:
            self._reveal_generation += 1
            self._reveal_cancel.set()
            if self._box_open and self._box_start_marker is not None and self._current_boxed:
                self._revealed_len = len(self._current_boxed)
                with _append_lock:
                    prefix = output_buffer.text[: self._box_start_marker]
                    start_line = prefix.count("\n")
                    new_text = prefix + self._current_boxed
                    _set_output(new_text, follow_tail=tail_following[0])
                    block_registry.register_or_update(
                        self._block_id,
                        start_line=start_line,
                        line_count=self._current_boxed.count("\n") + 1,
                        line_metadata=self._current_line_meta,
                    )
                _invalidate()

        def cancel(self) -> None:
            self._cancelled = True
            self.clear_thinking()
            self.clear_presentation_state()

        def is_cancelled(self) -> bool:
            return self._cancelled

        def set_authoring_mode(self, active: bool) -> None:
            self._authoring_mode = active

        def set_user_input(self, text: str) -> None:
            self._cancelled = False
            self.reveal_now()
            self._user_input = text or ""
            self._tool_switched = False
            self._turn_start_time = time.time()
            self._revealed_len = 0
            self._current_boxed = ""
            self._current_line_meta = {}
            self._in_tool_loop = False
            self._intermediate_marker = None
            self._intermediate_end = None
            self._activity.clear()
            self._activity_marker = None
            self._activity_end = None
            self._activity_prefix = ""
            self._active_tool_event_id = None
            self._pending_confirmation_tool = None
            self._pending_tool_results: list[tuple[str, Any]] = []
            self._block_id = _next_app_block_id()
            self._box_open = False
            self._md = StreamingMarkdownFilter(content_width=_content_width())

        def set_turn_snapshot(self, snapshot) -> None:
            self._snapshot = snapshot

        def clear_presentation_state(self) -> None:
            """Drop transient render state without touching conversation history."""
            self._reveal_generation += 1
            self._reveal_cancel.set()
            self._revealed_len = 0
            self._current_boxed = ""
            self._current_line_meta = {}
            self._in_tool_loop = False
            self._intermediate_marker = None
            self._intermediate_end = None
            self._cancel_timers()
            self._box_open = False
            self._box_start_marker = None
            self._tool_marker = None
            self._activity.clear()
            self._activity_marker = None
            self._activity_end = None
            self._activity_prefix = ""
            self._active_tool_event_id = None
            self._pending_confirmation_tool = None
            self._learning_markers.clear()
            self._md = StreamingMarkdownFilter(content_width=_content_width())

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
            cw = _content_width()
            flow_rows = self._activity.render_flow(cw, past_intent=self._activity_prefix.strip())
            block_lines = [row.text for row in flow_rows]
            block = ("\n".join(block_lines) + "\n") if block_lines else ""
            with _append_lock:
                current = output_buffer.text
                tail = current[self._activity_end:] if self._activity_end is not None else ""
                prefix = current[: self._activity_marker]
                _set_output(prefix + block + tail, follow_tail=tail_following[0])
                self._activity_end = self._activity_marker + len(block)
                start_line = prefix.count("\n")
                line_meta = {}
                for idx, row in enumerate(flow_rows):
                    if row.kind == "diff":
                        eff_lang = normalize_language_alias(row.language) or "python"
                        if eff_lang in ("diff", "patch", ""):
                            eff_lang = "python"
                        line_meta[idx] = ("diff", eff_lang)
                if line_meta:
                    block_registry.register_or_update(
                        self._block_id + 99999,
                        start_line,
                        len(block_lines),
                        line_meta,
                    )
            _invalidate()

        def narrate(self, text: str) -> None:
            if self._cancelled:
                return
            if not self._turn_start_time:
                self._turn_start_time = time.time()
            self.clear_thinking()
            self._intermediate_text = text
            if self._activity_marker is None:
                with _append_lock:
                    cur = output_buffer.text
                    if cur and not cur.endswith("\n"):
                        cur += "\n"
                    self._activity_marker = len(cur)
                    self._activity_end = self._activity_marker
            self._activity.add_narration(text)
            self._render_activity()

        def chunk(self, text: str) -> None:
            if self._cancelled:
                return
            if not self._turn_start_time:
                self._turn_start_time = time.time()
            self.clear_thinking()

            self._md.feed(text)
            if not self._box_open:
                self._box_open = True
                self._revealed_len = 0
                with _append_lock:
                    cur = output_buffer.text
                    if cur and not cur.endswith("\n\n"):
                        extra = "\n" if cur.endswith("\n") else "\n\n"
                        _set_output(cur + extra, follow_tail=tail_following[0])
                self._box_start_marker = len(output_buffer.text)

            segs = self._md.get_segments()
            cw = _content_width()
            boxed, line_meta = render_response_box_from_segments(segs, cw)
            self._current_boxed = boxed
            self._current_line_meta = line_meta
            active_rec = ResponsePayloadRecord(
                block_id=self._block_id,
                canonical_chunks=self._md._canonical_chunks,
                segments=segs,
            )
            active_response[0] = active_rec
            payload_by_id[self._block_id] = active_rec

            if getattr(rt.cfg, "reduced_motion", False):
                self._revealed_len = len(boxed)
                with _append_lock:
                    prefix = output_buffer.text[: self._box_start_marker]
                    start_line = prefix.count("\n")
                    new_text = prefix + boxed
                    _set_output(new_text, follow_tail=tail_following[0])
                    block_registry.register_or_update(
                        self._block_id,
                        start_line=start_line,
                        line_count=boxed.count("\n") + 1,
                        line_metadata=line_meta,
                    )
                _invalidate()
            else:
                self._reveal_generation += 1
                gen = self._reveal_generation
                self._reveal_cancel.set()
                cancel_evt = threading.Event()
                self._reveal_cancel = cancel_evt

                prev_len = min(self._revealed_len, len(boxed))
                target_len = len(boxed)

                def _reveal_worker(
                    target_gen: int,
                    cancel: threading.Event,
                    start_len: int,
                    end_len: int,
                    target_boxed: str,
                    meta: dict,
                    box_marker: int,
                    block_id: int,
                ) -> None:
                    try:
                        curr = start_len
                        chars_to_add = end_len - start_len
                        if chars_to_add <= 0:
                            return
                        steps = min(chars_to_add, 13)
                        step_size = max(1, (chars_to_add + steps - 1) // steps)
                        step_delay = min(0.015, 0.200 / steps) if steps > 0 else 0.015

                        while curr < end_len:
                            if cancel.is_set() or self._reveal_generation != target_gen:
                                return
                            time.sleep(step_delay)
                            if cancel.is_set() or self._reveal_generation != target_gen:
                                return
                            curr = min(curr + step_size, end_len)
                            self._revealed_len = curr
                            with _append_lock:
                                if cancel.is_set() or self._reveal_generation != target_gen:
                                    return
                                prefix = output_buffer.text[:box_marker]
                                start_line = prefix.count("\n")
                                revealed_text = target_boxed[:curr]
                                _set_output(prefix + revealed_text, follow_tail=tail_following[0])
                                block_registry.register_or_update(
                                    block_id,
                                    start_line=start_line,
                                    line_count=revealed_text.count("\n") + 1,
                                    line_metadata=meta,
                                )
                            _invalidate()
                    except Exception:
                        pass

                t = threading.Thread(
                    target=_reveal_worker,
                    args=(
                        gen,
                        cancel_evt,
                        prev_len,
                        target_len,
                        boxed,
                        line_meta,
                        self._box_start_marker,
                        self._block_id,
                    ),
                    daemon=True,
                )
                self._reveal_thread = t
                t.start()

        def end_assistant(self) -> None:
            if self._cancelled:
                return
            self.reveal_now()
            self._in_tool_loop = False
            self._intermediate_marker = None
            self._intermediate_end = None
            self._activity_marker = None
            self._activity_end = None
            dur = (time.time() - self._turn_start_time) if self._turn_start_time else state.extra.get("last_latency_s", 0.0)
            meta_parts: list[str] = []
            if dur and dur > 0:
                meta_parts.append(f"{dur:.1f}s")
            last_res = getattr(getattr(rt, "client", None), "last_result", None)
            tt = getattr(last_res, "total_tokens", None)
            if isinstance(tt, (int, float)) and tt > 0:
                pt = getattr(last_res, "prompt_tokens", 0) or 0
                ct = getattr(last_res, "completion_tokens", 0) or 0
                pt_val = pt if isinstance(pt, (int, float)) else 0
                ct_val = ct if isinstance(ct, (int, float)) else 0
                tt_str = f"{tt/1000:.1f}k" if tt >= 1000 else f"{int(tt)}"
                pt_str = f"{pt_val/1000:.1f}k" if pt_val >= 1000 else f"{int(pt_val)}"
                ct_str = f"{ct_val/1000:.1f}k" if ct_val >= 1000 else f"{int(ct_val)}"
                meta_parts.append(f"{tt_str} tokens ({pt_str} in / {ct_str} out)")
            meta = " · ".join(meta_parts) if meta_parts else None

            if self._box_open:
                self._md.flush()
                segs = self._md.get_segments()
                cw = _content_width()
                boxed, line_meta = render_response_box_from_segments(segs, cw, meta=meta)
                canonical_full = self._md.canonical_source

                record = ResponsePayloadRecord(
                    block_id=self._block_id,
                    canonical_chunks=list(self._md._canonical_chunks),
                    segments=segs,
                    meta=meta,
                    canonical_source_cached=canonical_full,
                )
                active_response[0] = record
                payload_by_id[self._block_id] = record
                response_payloads.append(record)

                if messages and getattr(messages[-1], "role", "") == "assistant":
                    messages[-1].content = canonical_full

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
                    start_line = prefix.count("\n")
                    new_text = prefix + boxed + refl_text + "\n\n"
                    _set_output(new_text, follow_tail=tail_following[0])
                    block_registry.register_or_update(
                        self._block_id,
                        start_line=start_line,
                        line_count=boxed.count("\n") + 1,
                        line_metadata=line_meta,
                    )

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
                                        _set_output(base_prefix + base_boxed + "\n" + "\n".join(shimmered) + "\n\n", follow_tail=tail_following[0])
                                    _invalidate()
                                time.sleep(0.04)
                                with _append_lock:
                                    _set_output(base_prefix + base_boxed + "\n" + "\n".join(final_refl) + "\n\n", follow_tail=tail_following[0])
                                _invalidate()
                            except Exception:
                                pass

                        threading.Thread(
                            target=_animate_glint,
                            args=(prefix, boxed, reflection_lines),
                            daemon=True,
                        ).start()

                self._box_open = False
                active_response[0] = None
                self._turn_start_time = 0.0
                _invalidate()
            else:
                append("\n\n")
                self._turn_start_time = 0.0
            self._md = StreamingMarkdownFilter(content_width=_content_width())

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

        def skill_seed(self, seed) -> None:
            from .skill_seed import render_skill_seed

            rendered = render_skill_seed(
                seed,
                _content_width(),
                ascii_only=getattr(rt.cfg, "ascii_ui", False),
            )
            with _append_lock:
                base = output_buffer.text.rstrip("\n") + "\n\n"
                _set_output(base + rendered + "\n\n")
            active_skill_seed[0] = seed
            editing_skill_seed[0] = None
            skill_seed_focused[0] = True
            rendered_skill_seed[0] = rendered
            layout.focus(input_window)
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
                formatted = _format_runtime_error(clean, max_width=_app_width() - 4)
                append(formatted + "\n")

        def edit(self, request: ConfirmRequest) -> dict | None:
            return prompt_edits(request)

        def confirm(self, request: ConfirmRequest) -> ConfirmVerdict:
            tool_name = getattr(request, "tool_name", None) or getattr(request, "tool", None)
            if tool_name:
                self._pending_confirmation_tool = str(tool_name)
            if self._active_tool_event_id is not None:
                self._activity.mark_confirmation(self._active_tool_event_id)

            title = _confirm_title(request)
            detail = _confirm_detail(request)
            if len(detail) > 58:
                detail = detail[:55] + "..."
            _confirm["title"] = title
            _confirm["options"] = _confirm_options(
                request.tool_name, session_allowable=request.session_allowable,
                turn_allowable=request.turn_allowable,
            )
            _confirm["detail"] = detail
            _confirm["reason"] = _confirm_reason(request)
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
            self._flush_pending_tool_results()
            with _append_lock:
                _set_output(output_buffer.text)
            _invalidate()
            return _confirm["answer"]

        def tool_start(self, name: str, args: dict | None = None) -> None:
            self._in_tool_loop = True
            self._intermediate_marker = None
            self._intermediate_end = None
            if self._authoring_mode and name == "create_skill":
                return
            self.clear_thinking()
            if self._box_open:
                self._reveal_cancel.set()
                self._box_open = False
                self._box_start_marker = None
            self._md = StreamingMarkdownFilter(content_width=_content_width())

            self._tool_args = args if isinstance(args, dict) else {}
            self._tool_start_time = time.time()
            desc = _format_tool_desc(name, self._tool_args)
            if self._activity_marker is None:
                self._activity_marker = len(output_buffer.text)
                self._activity_end = self._activity_marker
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
            screen_reader = getattr(rt.cfg, "screen_reader", False)
            if not screen_reader:
                req_confirm = (self._pending_confirmation_tool == name)
                self._pending_confirmation_tool = None
                self._active_tool_event_id = self._activity.start(
                    name,
                    desc,
                    group=activity_group(name, verification=verification),
                    required_confirmation=req_confirm,
                    security_relevant=None,
                )
                self._render_activity()

        def tool_result(self, name: str, shown: Any) -> None:
            self._in_tool_loop = False
            if self._authoring_mode and name == "create_skill":
                return
            if _confirm["active"]:
                self._pending_tool_results.append((name, shown))
                return
            dur = time.time() - self._tool_start_time

            # Typed File Change Rendering nested directly under the tool activity
            file_change = None
            try:
                from ..tools.file_tool import FileChangeResult, pop_last_file_change_result, get_file_change_by_id
                if isinstance(shown, FileChangeResult):
                    file_change = shown
                elif isinstance(shown, dict) and "committed_content_or_diff" in shown:
                    file_change = FileChangeResult.from_dict(shown)
                elif hasattr(shown, "change_id"):
                    file_change = get_file_change_by_id(getattr(shown, "change_id"))
                elif name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
                    file_change = pop_last_file_change_result()
            except Exception:
                file_change = None

            if file_change is not None and not getattr(file_change, "binary", False):
                cw = _content_width()
                status = getattr(file_change, "status", "")
                preview = getattr(file_change, "display_preview", "")
                committed = getattr(file_change, "committed_content_or_diff", "")
                path = getattr(file_change, "path", "")
                lang = getattr(file_change, "content_type_or_language", "")
                cid = getattr(file_change, "change_id", None)

                diff_content = ""
                if status == "created" and preview:
                    diff_content = "\n".join(f"+{line}" for line in preview.splitlines())
                elif status == "modified" and (preview or committed):
                    diff_content = preview or committed

                if diff_content:
                    from .render import format_diff_block
                    artifact_block = format_diff_block(
                        diff_content,
                        filename=path,
                        width=cw,
                        is_limited=bool(getattr(file_change, "truncated", False)),
                    )
                    eff_lang = normalize_language_alias(lang or (path.rsplit(".", 1)[-1] if "." in path else "python"))
                    if eff_lang in ("diff", "patch", ""):
                        eff_lang = "python"
                    if self._active_tool_event_id is not None:
                        self._activity.attach_diff(
                            self._active_tool_event_id,
                            artifact_block.splitlines(),
                            eff_lang,
                            change_id=cid,
                        )

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

        def _flush_pending_tool_results(self) -> None:
            pending, self._pending_tool_results = self._pending_tool_results, []
            for item in pending:
                if len(item) == 3:
                    pending_event_id, pending_name, pending_shown = item
                    if pending_event_id is not None:
                        self._active_tool_event_id = pending_event_id
                else:
                    pending_name, pending_shown = item
                self.tool_result(pending_name, pending_shown)

        def blocked(self, name: str, reason: str) -> None:
            if self._authoring_mode and name == "create_skill":
                return
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
            if self._authoring_mode and name == "create_skill":
                return
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

    def clear_screen() -> str | None:
        """Atomically clear visible transcript state while preserving messages."""
        if turn_running[0]:
            return "Wait for the active turn to finish before clearing."
        with _append_lock:
            block_registry.clear()
            payload_by_id.clear()
            response_payloads.clear()
            active_response[0] = None
            authoring_anchor[0] = None
            authoring_span[0] = None
            tail_following[0] = False
            sink.clear_presentation_state()
            _set_output("", follow_tail=False)
            output_window.vertical_scroll = 0
        return None

    def _replace_skill_seed(replacement: str) -> None:
        previous = rendered_skill_seed[0]
        with _append_lock:
            current = output_buffer.text
            index = current.rfind(previous) if previous else -1
            if index >= 0:
                current = current[:index] + replacement + current[index + len(previous):]
            elif replacement:
                current = current.rstrip("\n") + "\n\n" + replacement + "\n"
            _set_output(current)
        rendered_skill_seed[0] = replacement
        _invalidate()

    def _handle_skill_seed(action: str, edit_text: str = "") -> None:
        seed = active_skill_seed[0] or editing_skill_seed[0]
        if seed is None:
            return
        from hund.learning.skill_proposals import SkillProposalStore
        from .skill_seed import render_skill_seed

        store = SkillProposalStore()
        if action == "edit" and edit_text:
            store.respond(seed.proposal_id, "edit")
            updated = store.respond(
                seed.proposal_id, "apply_edit", edit_text=edit_text
            )
            if updated is not None:
                rendered = render_skill_seed(
                    updated,
                    _content_width(),
                    ascii_only=getattr(rt.cfg, "ascii_ui", False),
                )
                _replace_skill_seed(rendered)
                active_skill_seed[0] = updated
                editing_skill_seed[0] = None
                skill_seed_focused[0] = True
            return
        updated = store.respond(seed.proposal_id, action)
        if action == "edit":
            editing_skill_seed[0] = updated or seed
            active_skill_seed[0] = None
            skill_seed_focused[0] = False
            append("What should hund change about its name, scope, or workflow?\n")
            return
        if action == "accept":
            if getattr(rt.cfg, "enable_skill_materialization", False):
                from hund.learning.skill_proposals import materialize_accepted_proposal
                from ..skills.authoring import PublicationReceipt, render_publication_receipt

                ok, res = materialize_accepted_proposal(
                    seed.proposal_id,
                    workspace_path=getattr(rt, "workspace", None),
                    desired_disposition="vault",
                )
                if ok:
                    receipt_text = (
                        render_publication_receipt(
                            res,
                            width=_content_width(),
                            ascii_only=getattr(rt.cfg, "ascii_ui", False),
                        )
                        if isinstance(res, PublicationReceipt)
                        else str(res)
                    )
                    _replace_skill_seed(f"  · Skill proposal accepted & materialized.\n{receipt_text}")
                else:
                    _replace_skill_seed(f"  · Skill proposal accepted, but publication failed: {res}")
            else:
                _replace_skill_seed("  · Skill proposal accepted; creation remains disabled in this rollout.")
            active_skill_seed[0] = None
            editing_skill_seed[0] = None
            skill_seed_focused[0] = False
            layout.focus(input_window)
            return
        receipts = {
            "decline": "Understood — hund will not suggest this workflow again unless it changes materially.",
            "later": "  · Skill proposal deferred.",
            "never": "  · Future suggestions for this workflow disabled.",
        }
        _replace_skill_seed(receipts.get(action, f"  · Action {action} completed."))
        active_skill_seed[0] = None
        editing_skill_seed[0] = None
        skill_seed_focused[0] = False
        layout.focus(input_window)

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
                    snapshot = collect_stats(
                        workspace=getattr(rt, "workspace", None)
                    )
                elif destination is DestinationView.SKILLS:
                    snapshot = collect_skills(
                        workspace=getattr(rt, "workspace", None),
                        include_proposals=getattr(
                            rt.cfg, "enable_skill_proposals", False
                        )
                    )
                elif destination is DestinationView.TOOLS:
                    snapshot = collect_tools()
                elif destination is DestinationView.USAGE:
                    snapshot = collect_usage(session_id=session_id)
                elif destination is DestinationView.SYSTEM:
                    from ..stats.environment_snapshot import create_environment_snapshot
                    snapshot = create_environment_snapshot(force_fresh=False)
                elif destination is DestinationView.DOCTOR:
                    from ..doctor import diagnose_system
                    snapshot = diagnose_system(rt, rt.workspace if hasattr(rt, "workspace") else None)
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
            model_options.clear()
            model_options.extend(get_options(rt.cfg))
            current_model = getattr(rt.cfg.provider, "model", "")
            for idx, opt in enumerate(model_options):
                if opt.model_id == current_model:
                    screens.selected["model"] = idx
                    break
        elif overlay is OverlayView.AUTH:
            screens.selected["auth"] = 0
        elif overlay is OverlayView.AUTH_ADD:
            screens.selected["auth_add"] = 0
        elif overlay is OverlayView.AUTH_MANAGE:
            screens.selected["auth_manage"] = 0
        screens.open_overlay(overlay)
        modal_editor.clear()
        _invalidate()

    # ---- slash command runner ----
    def run_command(user_text: str) -> None:
        buf = io.StringIO()
        app_w = _content_width()
        console = Console(file=buf, color_system=None, force_terminal=False, width=app_w)
        ctx = CommandContext(
            console=console,
            rt=rt,
            state=state,
            clear_screen=clear_screen,
        )
        dispatch_command(user_text, ctx)
        out = buf.getvalue()
        if out:
            append(out.rstrip("\n") + "\n\n")
        refresh_stats(state)
        _reflow_borders()
        _invalidate()

    # ---- agent turn runner (background thread) ----
    def _spawn_turn(echo_user: str | None, authoring_action=None) -> None:
        turn_running[0] = True
        mascot_machine.start_turn()
        run_id = uuid.uuid4().hex
        user_text = echo_user
        if echo_user is not None:
            w = max(_content_width() - 4, 20)
            wrapped_lines: list[str] = []
            for raw_line in echo_user.splitlines():
                clean_l = raw_line.replace("\t", "    ").rstrip("\r")
                clean_l = "".join(ch for ch in clean_l if ch >= " " or ch == "\t")
                if not clean_l.strip():
                    wrapped_lines.append("")
                elif len(clean_l) <= w:
                    wrapped_lines.append(clean_l)
                else:
                    indent_match = re.match(r"^(\s*)", clean_l)
                    lead_indent = indent_match.group(1) if indent_match else ""
                    wrapped_lines.extend(
                        textwrap.wrap(
                            clean_l,
                            width=w,
                            subsequent_indent=lead_indent,
                            break_long_words=False,
                            break_on_hyphens=False,
                        )
                        or [clean_l]
                    )
            if not wrapped_lines:
                wrapped_lines = [echo_user]

            formatted_echo = theme.USER_PREFIX + " " + wrapped_lines[0]
            if len(wrapped_lines) > 1:
                formatted_echo += "\n" + "\n".join(f"  {ln}" if ln else "" for ln in wrapped_lines[1:])
            append(formatted_echo + "\n\n", follow_tail=tail_following[0])
            authoring_anchor[0] = len(output_buffer.text)
            from ..agent.user_context import expand_user_context
            expanded_context = expand_user_context(echo_user, rt.workspace)
            messages.append(Message(role="user", content=expanded_context.prompt))
            if expanded_context.warns_about_size:
                append(
                    f"(context warning: about {expanded_context.estimated_tokens} tokens)\n",
                    follow_tail=tail_following[0],
                )
            _session_save(session_id, "user", echo_user, run_id=run_id)
        elif authoring_action is None:
            user_text = next(
                (m.content for m in reversed(messages) if getattr(m, "role", "") == "user"),
                "",
            )
        else:
            user_text = ""

        sink.set_user_input(user_text or "")
        sink.set_authoring_mode(
            authoring_action is not None or authoring_view[0] is not None
        )
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
                authoring_outcome = _run_authoring_runtime(
                    user_text or "",
                    session_id=session_id,
                    workspace=rt.workspace,
                    engine=rt.engine,
                    console=console,
                    client=getattr(rt, "client", None),
                    width=_content_width(),
                    ascii_only=getattr(rt.cfg, "ascii_ui", False),
                    hooks=sink,
                    run_id=run_id,
                    authoring_action=authoring_action,
                    transient=True,
                )
                if authoring_outcome.handled:
                    authoring_view[0] = authoring_outcome.view
                    authoring_selected[0] = 0
                    authoring_outputs = list(authoring_outcome.outputs)
                    if authoring_outcome.receipt is not None:
                        from .skill_authoring import render_publication_receipt

                        authoring_outputs = [render_publication_receipt(
                            authoring_outcome.receipt,
                            width=_content_width(),
                            ascii_only=getattr(rt.cfg, "ascii_ui", False),
                        )]
                        if getattr(authoring_outcome, "skill", None) is not None:
                            rt.pinned_skill = authoring_outcome.skill
                        else:
                            from ..skills.vault import SkillVault
                            vault = SkillVault()
                            skill_name = getattr(authoring_outcome.receipt, "skill_name", "")
                            if skill_name:
                                rt.pinned_skill = vault.find_skill(skill_name, workspace=rt.workspace)
                    assistant_text = "\n\n".join(authoring_outputs)
                    if authoring_outcome.view is not None:
                        _sync_authoring_inline()
                    elif assistant_text:
                        _sync_authoring_inline(assistant_text, permanent=True)
                        messages.append(Message(role="assistant", content=assistant_text))
                        _session_save(session_id, "assistant", assistant_text, run_id=run_id)
                    else:
                        _sync_authoring_inline("", permanent=True)
                    return

                authoring_anchor[0] = None
                client_key = getattr(rt.client, "api_key", None)
                if not getattr(rt, "key", "") or not client_key:
                    from ..providers.catalog import active_option, activate_model
                    curr_opt = active_option(rt.cfg)
                    activate_model(rt, curr_opt)

                tokens_before = estimate_tokens(messages)
                # Deterministic compression is local and bounded. It still belongs
                # off the Prompt Toolkit thread so submitting a prompt never freezes
                # the terminal when a long session crosses the token threshold.
                cw = getattr(getattr(getattr(rt, "cfg", None), "provider", None), "context_window", None)
                comp = maybe_compress(messages, client=getattr(rt, "client", None), context_window=cw)
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
                    set_status_notice(f"{comp.dropped_turns} turns compressed", duration=4.0)
                live_skills = _safe_skills(workspace=rt.workspace)
                rt.skills = live_skills
                dynamic_msg = _dynamic_context_message(
                    skills=live_skills,
                    user_text=user_text or "",
                    workspace_id=str(rt.workspace),
                    domain_hint=rt.domain_hint,
                    pinned_skill=getattr(rt, "pinned_skill", None),
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
                append(_format_runtime_error(e, max_width=_app_width() - 4))
            finally:
                rt.pinned_skill = None
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
                sink.set_authoring_mode(False)
                last_res = getattr(getattr(rt, "client", None), "last_result", None)
                if last_res and getattr(last_res, "prompt_tokens", 0) > 0:
                    state.extra["tokens"] = last_res.prompt_tokens
                else:
                    try:
                        from ..store.sqlite import connect_requests
                        with connect_requests() as conn:
                            row = conn.execute(
                                "SELECT prompt_tokens FROM requests WHERE prompt_tokens > 0 ORDER BY created_at DESC LIMIT 1"
                            ).fetchone()
                            if row and row[0]:
                                state.extra["tokens"] = int(row[0])
                            else:
                                state.extra["tokens"] = estimate_tokens(messages)
                    except Exception:
                        state.extra["tokens"] = estimate_tokens(messages)
                refresh_stats(state)
                _reflow_borders()
                turn_running[0] = False
                _invalidate()

        threading.Thread(target=worker, daemon=True).start()

    def run_turn(user_text: str) -> None:
        _spawn_turn(user_text)

    def _commit_authoring_selection() -> None:
        view = authoring_view[0]
        if view is None or not view.options or turn_running[0]:
            return
        from ..skills.authoring_runtime import (
            AuthoringAction,
            AuthoringActionKind,
        )

        option = view.options[authoring_selected[0] % len(view.options)]
        kind = (
            option.action
            if isinstance(option.action, AuthoringActionKind)
            else AuthoringActionKind(option.action)
        )
        action = AuthoringAction(
            kind,
            key=view.question_key,
            value=option.value,
        )
        _spawn_turn(None, authoring_action=action)

    def copy_last_response() -> None:
        last = ""
        if response_payloads:
            last = response_payloads[-1].canonical_source
        elif active_response[0] is not None:
            last = active_response[0].canonical_source
        elif messages:
            last = next(
                (m.content for m in reversed(messages) if getattr(m, "role", "") == "assistant"),
                "",
            )
        if not last:
            set_status_notice("nothing to copy")
            return
        if clipboard.copy_text(last):
            set_status_notice("copied last response to clipboard")
        else:
            set_status_notice("copy failed")

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
        normalized_text = normalize_terminal_input(buf.text)
        if normalized_text != buf.text:
            buf.text = normalized_text
        raw_text = normalized_text.strip()
        if not raw_text:
            return False
        if authoring_view[0] is not None:
            active_qkey = authoring_view[0].question_key
            if active_qkey in {"clarification", "correct_mini_draft"}:
                from ..skills.authoring_runtime import (
                    AuthoringAction,
                    AuthoringActionKind,
                )

                buf.reset()
                _spawn_turn(
                    None,
                    authoring_action=AuthoringAction(
                        AuthoringActionKind.ANSWER,
                        key=active_qkey,
                        value=raw_text,
                    ),
                )
                return True
            buf.reset()
            set_status_notice("Use Up/Down and Enter to continue skill authoring.")
            return True
        if editing_skill_seed[0] is not None:
            buf.reset()
            _handle_skill_seed("edit", raw_text)
            return True
        if active_skill_seed[0] is not None:
            from hund.learning.skill_proposals import natural_proposal_action

            proposal_action = natural_proposal_action(raw_text)
            if proposal_action is not None:
                buf.reset()
                _handle_skill_seed(
                    proposal_action,
                    raw_text if proposal_action == "edit" else "",
                )
                return True
            skill_seed_focused[0] = False
        buf.append_to_history()
        try:
            cur_strings = [s for s in repl_history.load_history_strings() if s]
        except Exception:
            cur_strings = []
        if not cur_strings or cur_strings[-1] != raw_text:
            cur_strings.append(raw_text)
        buf._working_lines = deque(cur_strings + [""])
        buf.working_index = len(buf._working_lines) - 1
        buf.reset()
        paste_folded[0] = False

        text = raw_text
        if text.startswith("/"):
            text = resolve_slash_command(text)

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
            "/system": DestinationView.SYSTEM,
            "/doctor": DestinationView.DOCTOR,
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

        if text == "/auth":
            _open_overlay(OverlayView.AUTH)
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
        lambda: screens.overlay is not OverlayView.NONE
        and screens.overlay is not OverlayView.CONFIRM
    )
    modal_active = Condition(
        lambda: bool(_confirm.get("active"))
        or (
            screens.overlay is not OverlayView.NONE
            and screens.overlay is not OverlayView.CONFIRM
        )
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
    authoring_active = Condition(
        lambda: authoring_view[0] is not None
        and screens.destination is DestinationView.CHAT
        and screens.overlay is OverlayView.NONE
        and not _confirm.get("active")
    )
    authoring_choice_active = Condition(
        lambda: authoring_view[0] is not None
        and bool(authoring_view[0].options)
        and screens.destination is DestinationView.CHAT
        and screens.overlay is OverlayView.NONE
        and not _confirm.get("active")
    )
    skill_seed_active = Condition(
        lambda: active_skill_seed[0] is not None
        and skill_seed_focused[0]
        and input_buffer.text == ""
        and layout.has_focus(input_window)
        and screens.destination is DestinationView.CHAT
        and screens.overlay is OverlayView.NONE
        and not _confirm.get("active")
    )
    modal_input_active = Condition(
        lambda: screens.overlay in {
            OverlayView.MODEL_CUSTOM,
            OverlayView.MODEL_KEY,
            OverlayView.AUTH_KEY,
            OverlayView.AUTH_CUSTOM,
        } and not _confirm.get("active")
    )

    def _scroll_lines(count: int) -> None:
        ri = output_window.render_info
        if ri is None:
            return
        first = ri.first_visible_line(after_scroll_offset=True)
        wh = ri.window_height
        lc = output_buffer.document.line_count
        if output_buffer.selection_state is not None:
            output_window.vertical_scroll = max(0, min(max(0, lc - wh), first - count))
            tail_following[0] = False
            _invalidate()
            return
        if count > 0:  # up
            target = max(0, first - count)
            tail_following[0] = False
        else:  # down
            target = min(lc - 1, first + wh - 1 + (-count))
            if target >= lc - 1:
                tail_following[0] = True
            else:
                tail_following[0] = False
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
            buf.exit_selection()
            layout.focus(input_window)
            if clipboard.copy_text(text):
                set_status_notice("copied to clipboard")
                return True
        return False

    kb = KeyBindings()

    @kb.add("a", filter=skill_seed_active)
    @kb.add("A", filter=skill_seed_active)
    def _accept_skill_seed(event):
        _handle_skill_seed("accept")

    @kb.add("e", filter=skill_seed_active)
    @kb.add("E", filter=skill_seed_active)
    def _edit_skill_seed(event):
        _handle_skill_seed("edit")

    @kb.add("d", filter=skill_seed_active)
    @kb.add("D", filter=skill_seed_active)
    def _decline_skill_seed(event):
        _handle_skill_seed("decline")

    @kb.add(Keys.Any, filter=authoring_choice_active)
    def _authoring_ignore_text(event):
        set_status_notice("Use Up/Down and Enter to continue skill authoring.")

    @kb.add("up", filter=authoring_choice_active)
    def _authoring_up(event):
        _move_authoring_selection(-1)

    @kb.add("down", filter=authoring_choice_active)
    def _authoring_down(event):
        _move_authoring_selection(1)

    @kb.add("enter", filter=authoring_choice_active)
    def _authoring_enter(event):
        _commit_authoring_selection()

    @kb.add("escape", eager=True, filter=authoring_active)
    def _authoring_back(event):
        if turn_running[0]:
            return
        from ..skills.authoring_runtime import AuthoringAction, AuthoringActionKind

        _spawn_turn(
            None,
            authoring_action=AuthoringAction(AuthoringActionKind.BACK),
        )

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
    @kb.add("Y", filter=confirm_active)
    def _y(event):
        _confirm["answer"] = ConfirmVerdict.APPROVE_ONCE
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("e", filter=confirm_active)
    @kb.add("E", filter=confirm_active)
    def _e(event):
        verdicts = {item[0] for item in _confirm["options"]}
        _confirm["answer"] = (
            ConfirmVerdict.EDIT if ConfirmVerdict.EDIT in verdicts else ConfirmVerdict.DENY
        )
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("a", filter=confirm_active)
    @kb.add("A", filter=confirm_active)
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

    @kb.add("t", filter=confirm_active)
    @kb.add("T", filter=confirm_active)
    def _t(event):
        verdicts = {item[0] for item in _confirm["options"]}
        _confirm["answer"] = ConfirmVerdict.ALLOW_TURN if ConfirmVerdict.ALLOW_TURN in verdicts else ConfirmVerdict.DENY
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("n", filter=confirm_active)
    @kb.add("N", filter=confirm_active)
    @kb.add("escape", eager=True, filter=confirm_active)
    def _n(event):
        _confirm["answer"] = ConfirmVerdict.DENY
        _confirm["active"] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("escape", eager=True, filter=~confirm_active & ~authoring_active)
    def _escape(event):
        if screens.destination is not DestinationView.CHAT:
            _close_destination()
            return
        if screens.overlay is not OverlayView.NONE:
            screens.overlay = OverlayView.NONE
            modal_editor.clear()
            screens.status = ""
            _invalidate()
            return
        if (
            active_skill_seed[0] is not None
            and skill_seed_focused[0]
            and input_buffer.text == ""
        ):
            _handle_skill_seed("later")
            return
        if output_buffer.selection_state is not None:
            output_buffer.exit_selection()
        layout.focus(input_window)
        _invalidate()

    @kb.add("q", filter=destination_active & ~modal_active)
    @kb.add("Q", filter=destination_active & ~modal_active)
    def _destination_q(event):
        _close_destination()

    @kb.add("q", filter=Condition(
        lambda: screens.overlay in {
            OverlayView.THEME,
            OverlayView.MODEL,
            OverlayView.AUTH,
            OverlayView.AUTH_ADD,
            OverlayView.AUTH_MANAGE,
        } and not _confirm.get("active")
    ))
    @kb.add("Q", filter=Condition(
        lambda: screens.overlay in {
            OverlayView.THEME,
            OverlayView.MODEL,
            OverlayView.AUTH,
            OverlayView.AUTH_ADD,
            OverlayView.AUTH_MANAGE,
        } and not _confirm.get("active")
    ))
    def _overlay_q(event):
        screens.overlay = OverlayView.NONE
        modal_editor.clear()
        screens.status = ""
        _invalidate()

    @kb.add("backspace", filter=destination_active & ~modal_active)
    def _destination_back(event):
        res = screens.step_back()
        if res == "destination":
            _close_destination()
        elif res != "none":
            _invalidate()

    @kb.add("r", filter=destination_active & ~modal_active)
    @kb.add("R", filter=destination_active & ~modal_active)
    def _destination_r(event):
        if screens.destination is DestinationView.SYSTEM:
            from ..stats.environment_snapshot import create_environment_snapshot
            screen_snapshots["system"] = create_environment_snapshot(force_fresh=True)
            _invalidate()

    @kb.add("f", filter=destination_active & ~modal_active)
    @kb.add("F", filter=destination_active & ~modal_active)
    def _destination_f(event):
        if screens.destination is DestinationView.DOCTOR:
            doctor_review_fixes[0] = not doctor_review_fixes[0]
            _invalidate()

    @kb.add("backspace", filter=overlay_active & ~modal_input_active & ~confirm_active)
    def _overlay_nav_back(event):
        res = screens.step_back()
        if res in ("nested", "overlay"):
            modal_editor.clear()
            screens.status = ""
            _invalidate()

    @kb.add("up", filter=overlay_active & ~confirm_active)
    def _overlay_up(event):
        if screens.overlay is OverlayView.THEME:
            screens.move("theme", -1, len(theme.theme_names()))
        elif screens.overlay is OverlayView.MODEL:
            screens.move("model", -1, len(model_options))
        elif screens.overlay is OverlayView.AUTH:
            screens.move("auth", -1, 2)
        elif screens.overlay is OverlayView.AUTH_ADD:
            screens.move("auth_add", -1, len(PROVIDER_PRESETS))
        elif screens.overlay is OverlayView.AUTH_MANAGE:
            screens.move("auth_manage", -1, max(len(_manage_entries()), 1))
        _invalidate()

    @kb.add("down", filter=overlay_active & ~confirm_active)
    def _overlay_down(event):
        if screens.overlay is OverlayView.THEME:
            screens.move("theme", 1, len(theme.theme_names()))
        elif screens.overlay is OverlayView.MODEL:
            screens.move("model", 1, len(model_options))
        elif screens.overlay is OverlayView.AUTH:
            screens.move("auth", 1, 2)
        elif screens.overlay is OverlayView.AUTH_ADD:
            screens.move("auth_add", 1, len(PROVIDER_PRESETS))
        elif screens.overlay is OverlayView.AUTH_MANAGE:
            screens.move("auth_manage", 1, max(len(_manage_entries()), 1))
        _invalidate()

    @kb.add("up", filter=destination_active & ~modal_active)
    def _screen_up(event):
        key = screens.destination.value
        snapshot = screen_snapshots.get(key)
        if screens.destination is DestinationView.SKILLS and snapshot is not None:
            screens.move(
                key, -1,
                len(snapshot.equipped) + len(snapshot.parked) + len(snapshot.proposals),
            )
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
            screens.move(
                key, 1,
                len(snapshot.equipped) + len(snapshot.parked) + len(snapshot.proposals),
            )
            screens.scroll_by(key, 1, 10_000)
        elif screens.destination is DestinationView.TOOLS and snapshot is not None:
            screens.move(key, 1, len(snapshot.tools))
            screens.scroll_by(key, 1, 10_000)
        else:
            screens.scroll_by(key, 1, 10_000)
        _invalidate()

    # agyD/0 (Gate 3): Home/End/j/k scroll destination views (spec §2.5.1).
    @kb.add("home", filter=destination_active & ~modal_active)
    def _screen_home(event):
        screens.scroll_by(screens.destination.value, -10_000, 10_000)
        _invalidate()

    @kb.add("end", filter=destination_active & ~modal_active)
    def _screen_end(event):
        screens.scroll_by(screens.destination.value, 10_000, 10_000)
        _invalidate()

    @kb.add("j", filter=destination_active & ~modal_active)
    def _screen_j(event):
        _screen_up(event)

    @kb.add("k", filter=destination_active & ~modal_active)
    def _screen_k(event):
        _screen_down(event)

    @kb.add("u", filter=destination_active & ~modal_active)
    @kb.add("U", filter=destination_active & ~modal_active)
    def _unsuppress_skill_seed(event):
        if screens.destination is not DestinationView.SKILLS:
            return
        snapshot = screen_snapshots.get(DestinationView.SKILLS.value)
        if snapshot is None:
            return
        offset = len(snapshot.equipped) + len(snapshot.parked)
        selected = screens.selected.get(DestinationView.SKILLS.value, 0)
        if selected < offset or (selected - offset) >= len(snapshot.proposals):
            return
        from hund.learning.skill_proposals import SkillProposalStore

        item = snapshot.proposals[selected - offset]
        if SkillProposalStore().unsuppress(item.candidate_id):
            screens.status = f"Re-enabled {item.name}."
            screen_snapshots[DestinationView.SKILLS.value] = collect_skills(
                workspace=getattr(rt, "workspace", None),
                include_proposals=True
            )
            screens.selected[DestinationView.SKILLS.value] = 0
        else:
            screens.status = "Could not re-enable this Skill Seed."
        _invalidate()

    @kb.add("enter", filter=destination_active & ~modal_active)
    def _destination_enter(event):
        if screens.destination is DestinationView.SKILLS:
            if screens.detail.get("skills"):
                screens.detail["skills"] = None
                _invalidate()
                return
            snapshot = screen_snapshots.get(DestinationView.SKILLS.value)
            if snapshot is None:
                return
            all_skills = snapshot.equipped + snapshot.parked
            selected = screens.selected.get(DestinationView.SKILLS.value, 0)
            if 0 <= selected < len(all_skills):
                skill = all_skills[selected]
                screens.detail["skills"] = skill.name
                _invalidate()
        elif screens.destination is DestinationView.TOOLS:
            if screens.detail.get("tools"):
                screens.detail["tools"] = None
                _invalidate()
                return
            snapshot = screen_snapshots.get(DestinationView.TOOLS.value)
            if snapshot is None:
                return
            selected = screens.selected.get(DestinationView.TOOLS.value, 0)
            if 0 <= selected < len(snapshot.tools):
                tool = snapshot.tools[selected]
                screens.detail["tools"] = tool.name
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
            if model_options:
                option = model_options[screens.selected.get("model", 0) % len(model_options)]
                ok, message = activate_model(rt, option)
                screens.status = message
                if ok:
                    state.extra["model"] = option.model_id
                    state.extra["token_limit"] = option.context_window
                    screens.overlay = OverlayView.NONE
        elif screens.overlay is OverlayView.AUTH:
            choice = screens.selected.get("auth", 0)
            if choice == 0:
                screens.selected["auth_add"] = 0
                modal_editor.clear()
                screens.open_overlay(OverlayView.AUTH_ADD)
            else:
                screens.selected["auth_manage"] = 0
                screens.open_overlay(OverlayView.AUTH_MANAGE)
        elif screens.overlay is OverlayView.AUTH_ADD:
            idx = screens.selected.get("auth_add", 0) % len(PROVIDER_PRESETS)
            preset = PROVIDER_PRESETS[idx]
            if preset.provider_id == "custom":
                custom_step[0] = 0
                custom_wizard_data.clear()
                modal_editor.clear()
                screens.open_overlay(OverlayView.AUTH_CUSTOM)
            else:
                auth_target_provider["name"] = preset.name
                auth_target_provider["credential_id"] = preset.credential_id
                auth_target_provider["env_name"] = preset.env_name
                modal_editor.clear()
                screens.open_overlay(OverlayView.AUTH_KEY)
        elif screens.overlay is OverlayView.AUTH_KEY:
            secret = modal_editor.get_raw().strip()
            if not secret:
                screens.status = "API key cannot be empty."
            else:
                cred_id = auth_target_provider.get("credential_id", "deepseek")
                if save_api_key(secret, cred_id):
                    modal_editor.clear()
                    model_options.clear()
                    model_options.extend(get_options(rt.cfg))
                    screens.open_overlay(OverlayView.MODEL)
                    screens.status = f"Saved API key for {auth_target_provider.get('name', 'Provider')}."
                else:
                    screens.status = "Credential vault unavailable."
        elif screens.overlay is OverlayView.AUTH_CUSTOM:
            step = custom_step[0]
            val = modal_editor.get_raw().strip()
            if step == 0:
                if not val or len(val) > 32:
                    screens.status = "Name must be between 1 and 32 characters."
                else:
                    custom_wizard_data["name"] = val
                    custom_step[0] = 1
                    modal_editor.clear()
                    screens.status = ""
            elif step == 1:
                if not val.startswith(("http://", "https://")):
                    screens.status = "Base URL must start with http:// or https://"
                else:
                    custom_wizard_data["base_url"] = val.rstrip("/")
                    custom_step[0] = 2
                    modal_editor.clear()
                    screens.status = ""
            elif step == 2:
                if not val:
                    screens.status = "Model ID cannot be empty."
                else:
                    custom_wizard_data["model_id"] = val
                    custom_step[0] = 3
                    modal_editor.set_text("32768")
                    screens.status = ""
            elif step == 3:
                try:
                    ctx_val = int(val)
                    if not 1_024 <= ctx_val <= 10_000_000:
                        raise ValueError()
                    custom_wizard_data["context_window"] = str(ctx_val)
                    custom_step[0] = 4
                    modal_editor.clear()
                    screens.status = ""
                except Exception:
                    screens.status = "Context window must be an integer between 1,024 and 10,000,000."
            elif step == 4:
                if not val:
                    screens.status = "API key is required."
                else:
                    ep_id = "custom_" + uuid.uuid4().hex[:8]
                    saved_vault = False
                    try:
                        saved_vault = save_api_key(val, ep_id)
                    except Exception:
                        saved_vault = False

                    if not saved_vault:
                        screens.status = "Credential vault unavailable."
                    else:
                        ep = CustomEndpoint(
                            id=ep_id,
                            name=custom_wizard_data["name"],
                            base_url=custom_wizard_data["base_url"],
                            model_id=custom_wizard_data["model_id"],
                            context_window=int(custom_wizard_data["context_window"]),
                            credential_id=ep_id,
                        )
                        rt.cfg.custom_endpoints.append(ep)
                        try:
                            rt.cfg.save()
                            modal_editor.clear()
                            model_options.clear()
                            model_options.extend(get_options(rt.cfg))
                            screens.open_overlay(OverlayView.MODEL)
                            screens.status = f"Added custom endpoint: {ep.name}"
                        except Exception:
                            rt.cfg.custom_endpoints.pop()
                            try:
                                delete_api_key(ep_id)
                            except Exception:
                                pass
                            screens.status = "Failed to save configuration."
        elif screens.overlay is OverlayView.MODEL_CUSTOM:
            try:
                provider, base_url, model, context = [
                    part.strip() for part in modal_editor.get_raw().split("|", 3)
                ]
                option = custom_model(provider, base_url, model, int(context))
                ok, message = activate_model(rt, option)
                screens.status = message
                if ok:
                    model_options.insert(0, option)
                    state.extra["model"] = option.model_id
                    state.extra["token_limit"] = option.context_window
                    modal_editor.clear()
                    screens.overlay = OverlayView.NONE
            except Exception:
                screens.status = "Use: provider | base URL | model ID | context window"
        elif screens.overlay is OverlayView.MODEL_KEY:
            if model_options:
                option = model_options[screens.selected.get("model", 0) % len(model_options)]
                secret = modal_editor.get_raw().strip()
                modal_editor.clear()
                if save_api_key(secret, option.credential_id):
                    model_options.clear()
                    model_options.extend(get_options(rt.cfg))
                    screens.overlay = OverlayView.MODEL
                    screens.status = "Credential stored in Windows Credential Manager."
                else:
                    screens.status = (
                        f"Credential vault unavailable. Set {option.env_name or 'HUND_API_KEY'}."
                    )
        _invalidate()

    @kb.add("a", filter=Condition(lambda: screens.overlay is OverlayView.MODEL and not _confirm.get("active")))
    @kb.add("A", filter=Condition(lambda: screens.overlay is OverlayView.MODEL and not _confirm.get("active")))
    def _model_add(event):
        screens.selected["auth_add"] = 0
        modal_editor.clear()
        screens.open_overlay(OverlayView.AUTH_ADD)
        _invalidate()

    @kb.add("r", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_MANAGE and not _confirm.get("active")))
    @kb.add("R", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_MANAGE and not _confirm.get("active")))
    def _auth_manage_replace(event):
        entries = _manage_entries()
        if not entries:
            return
        idx = screens.selected.get("auth_manage", 0) % len(entries)
        non_custom_presets = [p for p in PROVIDER_PRESETS if p.provider_id != "custom"]
        if idx < len(non_custom_presets):
            preset = non_custom_presets[idx]
            cred_state, env_var = get_credential_status(preset.credential_id, preset.env_name)
            if cred_state == "environment":
                screens.status = f"Controlled by {env_var} environment variable (cannot replace via vault)."
                _invalidate()
                return
            auth_target_provider["name"] = preset.name
            auth_target_provider["credential_id"] = preset.credential_id
            auth_target_provider["env_name"] = preset.env_name
        else:
            ep_idx = idx - len(non_custom_presets)
            ep = rt.cfg.custom_endpoints[ep_idx]
            auth_target_provider["name"] = ep.name
            auth_target_provider["credential_id"] = ep.credential_id
            auth_target_provider["env_name"] = "HUND_API_KEY"
        modal_editor.clear()
        screens.open_overlay(OverlayView.AUTH_KEY)
        _invalidate()

    @kb.add("d", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_MANAGE and not _confirm.get("active")))
    @kb.add("D", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_MANAGE and not _confirm.get("active")))
    def _auth_manage_forget(event):
        entries = _manage_entries()
        if not entries:
            return
        idx = screens.selected.get("auth_manage", 0) % len(entries)
        non_custom_presets = [p for p in PROVIDER_PRESETS if p.provider_id != "custom"]
        if idx < len(non_custom_presets):
            preset = non_custom_presets[idx]
            cred_id = preset.credential_id
            name = preset.name
            cred_state, env_var = get_credential_status(preset.credential_id, preset.env_name)
        else:
            ep_idx = idx - len(non_custom_presets)
            ep = rt.cfg.custom_endpoints[ep_idx]
            cred_id = ep.credential_id
            name = ep.name
            cred_state, env_var = get_credential_status(ep.credential_id, "HUND_API_KEY")

        active_opt = active_option(rt.cfg)
        if cred_id == active_opt.credential_id:
            screens.status = f"Switch active model with /model before forgetting credential for {name}."
            _invalidate()
            return
        if cred_state == "environment":
            screens.status = f"Controlled by {env_var} environment variable (cannot delete from vault)."
            _invalidate()
            return
        auth_target_provider["name"] = name
        auth_target_provider["credential_id"] = cred_id
        modal_editor.clear()
        screens.open_overlay(OverlayView.AUTH_FORGET_CONFIRM)
        _invalidate()

    @kb.add("y", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_FORGET_CONFIRM and not _confirm.get("active")))
    @kb.add("Y", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_FORGET_CONFIRM and not _confirm.get("active")))
    def _auth_forget_yes(event):
        cred_id = auth_target_provider.get("credential_id", "")
        name = auth_target_provider.get("name", "Provider")
        delete_api_key(cred_id)
        rt.cfg.custom_endpoints = [ep for ep in rt.cfg.custom_endpoints if ep.credential_id != cred_id]
        rt.cfg.save()
        screens.status = f"Deleted credential for {name}."
        modal_editor.clear()
        screens.open_overlay(OverlayView.AUTH_MANAGE)
        _invalidate()

    @kb.add("n", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_FORGET_CONFIRM and not _confirm.get("active")))
    @kb.add("N", filter=Condition(lambda: screens.overlay is OverlayView.AUTH_FORGET_CONFIRM and not _confirm.get("active")))
    def _auth_forget_no(event):
        modal_editor.clear()
        screens.open_overlay(OverlayView.AUTH_MANAGE)
        _invalidate()

    @kb.add("k", filter=Condition(lambda: screens.overlay is OverlayView.MODEL and not _confirm.get("active")))
    @kb.add("K", filter=Condition(lambda: screens.overlay is OverlayView.MODEL and not _confirm.get("active")))
    def _model_key(event):
        if model_options:
            option = model_options[screens.selected.get("model", 0) % len(model_options)]
            auth_target_provider["name"] = option.provider_name
            auth_target_provider["credential_id"] = option.credential_id
            auth_target_provider["env_name"] = option.env_name
        modal_editor.clear()
        screens.open_overlay(OverlayView.AUTH_KEY)
        _invalidate()

    @kb.add(Keys.BracketedPaste, filter=modal_input_active)
    def _modal_bracketed_paste(event):
        data = getattr(event, "data", "") or ""
        modal_editor.insert_text(data)
        _invalidate()

    @kb.add(Keys.BracketedPaste, filter=overlay_active & ~modal_input_active)
    def _ignore_bracketed_paste_in_nav_overlay(event):
        pass

    @kb.add("c-v", filter=modal_input_active)
    @kb.add(Keys.ControlV, filter=modal_input_active)
    @kb.add(Keys.Insert, filter=modal_input_active)
    def _modal_paste(event):
        from .clipboard import paste_text
        clip = paste_text()
        if clip:
            modal_editor.insert_text(clip)
            _invalidate()

    @kb.add("backspace", filter=modal_input_active)
    def _modal_backspace(event):
        if modal_editor.get_raw():
            modal_editor.delete_char()
            _invalidate()
        else:
            res = screens.step_back()
            if res in ("nested", "overlay"):
                modal_editor.clear()
                screens.status = ""
                _invalidate()

    @kb.add("c-w", filter=modal_input_active)
    @kb.add(Keys.ControlW, filter=modal_input_active)
    @kb.add("escape", "backspace", filter=modal_input_active)
    @kb.add("escape", "delete", filter=modal_input_active)
    def _modal_delete_word(event):
        if modal_editor.get_raw():
            modal_editor.delete_word()
            _invalidate()

    @kb.add("c-u", filter=modal_input_active)
    def _modal_clear_line(event):
        modal_editor.clear()
        _invalidate()

    @kb.add("c-w", filter=has_focus(input_window) & chat_active)
    @kb.add(Keys.ControlW, filter=has_focus(input_window) & chat_active)
    @kb.add("escape", "backspace", filter=has_focus(input_window) & chat_active)
    @kb.add("escape", "delete", filter=has_focus(input_window) & chat_active)
    def _chat_alt_backspace(event):
        buf = input_buffer
        if buf.cursor_position > 0:
            pos = buf.cursor_position
            before = buf.text[:pos]
            new_before = ModalTextEditor.calc_deleted_word(before)
            deleted_count = len(before) - len(new_before)
            buf.delete_before_cursor(count=deleted_count)
            _invalidate()

    @kb.add("left", filter=modal_input_active)
    def _modal_left(event):
        pass

    @kb.add("right", filter=modal_input_active)
    def _modal_right(event):
        pass

    @kb.add("home", filter=modal_input_active)
    def _modal_home(event):
        pass

    @kb.add("end", filter=modal_input_active)
    def _modal_end(event):
        pass

    @kb.add(Keys.Any, filter=modal_input_active)
    def _modal_type(event):
        for key in event.key_sequence:
            if len(key.data) == 1 and key.data.isprintable():
                modal_editor.insert_text(key.data)
        _invalidate()

    @kb.add("f2", filter=has_focus(input_window) & chat_active)
    def _f2_toggle_paste_fold(event):
        if "\n" in input_buffer.text or len(input_buffer.text) > 80:
            paste_folded[0] = not paste_folded[0]
            if paste_folded[0]:
                line_count = len(input_buffer.text.splitlines())
                char_count = len(input_buffer.text)
                set_status_notice(f"Folded paste ({line_count} lines, {char_count} chars). Press F2 to expand.")
            else:
                set_status_notice("Expanded paste. Press F2 to fold.")
            _invalidate()

    @kb.add("c-c")
    def _ctrl_c(event):
        if _confirm["active"]:
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = False
            _confirm["event"].set()
            _invalidate()
        elif _copy_selection():
            pass
        elif turn_running[0]:
            turn_running[0] = False
            sink.cancel()
            mascot_machine.finish_turn()
            append("\n[turn cancelled]\n")
            set_status_notice("turn cancelled")
            _invalidate()
        elif input_buffer.text.strip():
            input_buffer.reset()
            set_status_notice("line cleared")
            _invalidate()
        else:
            set_status_notice("Nothing to copy. Use /exit or Ctrl+D to quit.", duration=1.8)

    @kb.add("c-d", filter=~modal_active)
    def _ctrl_d(event):
        if turn_running[0]:
            set_status_notice("Cancel the active turn before exiting.")
            return
        event.app.exit()

    @kb.add("up", filter=has_focus(input_window) & chat_active & ~authoring_active & ~has_completions)
    def _history_up(event):
        doc = input_buffer.document
        if doc.cursor_position_row == 0:
            input_buffer.history_backward()
        else:
            input_buffer.cursor_up()

    @kb.add("down", filter=has_focus(input_window) & chat_active & ~authoring_active & ~has_completions)
    def _history_down(event):
        doc = input_buffer.document
        if doc.cursor_position_row == doc.line_count - 1:
            input_buffer.history_forward()
        else:
            input_buffer.cursor_down()

    @kb.add("backspace", filter=has_selection & has_focus(input_window) & chat_active)
    @kb.add("delete", filter=has_selection & has_focus(input_window) & chat_active)
    def _delete_selection(event):
        buf = input_buffer
        try:
            r = buf.document.selection_range()
        except Exception:
            r = None
        if r:
            start, end = r
            buf.text = buf.text[:start] + buf.text[end:]
            buf.cursor_position = start
            buf.exit_selection()
        else:
            buf.exit_selection()

    @kb.add(Keys.Any, filter=has_selection & has_focus(input_window) & chat_active)
    def _replace_selection(event):
        buf = input_buffer
        for k in event.key_sequence:
            if len(k.data) == 1 and k.data.isprintable():
                try:
                    r = buf.document.selection_range()
                except Exception:
                    r = None
                if r:
                    start, end = r
                    buf.text = buf.text[:start] + k.data + buf.text[end:]
                    buf.cursor_position = start + 1
                    buf.exit_selection()
                else:
                    buf.exit_selection()
                    buf.insert_text(k.data)

    @kb.add("c-a", filter=has_focus(input_window) & chat_active)
    def _select_all(event):
        buf = input_buffer
        if buf.text:
            buf.cursor_position = 0
            buf.start_selection()
            buf.cursor_position = len(buf.text)

    @kb.add("c-x", filter=has_focus(input_window) & chat_active)
    def _cut_selection(event):
        buf = input_buffer
        try:
            r = buf.document.selection_range()
        except Exception:
            r = None
        if r:
            start, end = r
            selected = buf.text[start:end]
            if selected:
                clipboard.copy_text(selected)
                buf.cut_selection()
                set_status_notice("cut to clipboard")
        elif buf.text:
            clipboard.copy_text(buf.text)
            buf.reset()
            set_status_notice("cut to clipboard")

    @kb.add("c-v", filter=has_focus(input_window) & chat_active)
    def _paste_clipboard(event):
        raw = clipboard.paste_text()
        if raw:
            clean = raw.replace("\t", "    ").replace("\r\n", "\n").replace("\r", "\n")
            clean = "".join(ch for ch in clean if ch == "\n" or (ch >= " " and ord(ch) != 0x7F))
            input_buffer.insert_text(clean)

    @kb.add("c-z", filter=has_focus(input_window) & chat_active)
    def _undo(event):
        input_buffer.undo()

    @kb.add("c-y", filter=has_focus(input_window) & chat_active)
    def _redo(event):
        input_buffer.redo()

    @kb.add("pageup")
    def _pgup(event):
        if screens.destination is not DestinationView.CHAT:
            screens.scroll_by(screens.destination.value, -15, 10_000)
            _invalidate()
        else:
            _scroll_lines(15)

    @kb.add("pagedown")
    def _pgdn(event):
        if screens.destination is not DestinationView.CHAT:
            screens.scroll_by(screens.destination.value, 15, 10_000)
            _invalidate()
        else:
            _scroll_lines(-15)

    @kb.add("s-up", filter=chat_active)
    def _scroll_history_up(event):
        _scroll_lines(4)

    @kb.add("s-down", filter=chat_active)
    def _scroll_history_down(event):
        _scroll_lines(-4)

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

    @kb.add("enter", filter=has_focus(input_window) & chat_active & ~authoring_choice_active)
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
        output=output,
        input=input,
    )
    app.timeoutlen = 0.001
    app.ttimeoutlen = 0.001

    def _on_before_key_press(_kp) -> None:
        if active_sink[0] is not None:
            try:
                active_sink[0].reveal_now()
            except Exception:
                pass

    app.key_processor.before_key_press += _on_before_key_press
    holder["app"] = app

    context = {
        "screens": screens,
        "screen_snapshots": screen_snapshots,
        "modal_editor": modal_editor,
        "model_options": model_options,
        "auth_target_provider": auth_target_provider,
        "custom_wizard_data": custom_wizard_data,
        "custom_step": custom_step,
        "kb": kb,
        "layout": layout,
        "input_buffer": input_buffer,
        "output_buffer": output_buffer,
        "block_registry": block_registry,
        "payload_by_id": payload_by_id,
        "response_payloads": response_payloads,
        "clear_screen": clear_screen,
        "turn_running": turn_running,
        "authoring_view": authoring_view,
        "authoring_selected": authoring_selected,
        "authoring_anchor": authoring_anchor,
        "authoring_span": authoring_span,
        "authoring_container": authoring_container,
        "_authoring_fragments": _authoring_fragments,
        "_sync_authoring_inline": _sync_authoring_inline,
        "_move_authoring_selection": _move_authoring_selection,
        "_commit_authoring_selection": _commit_authoring_selection,
        "active_sink": active_sink,
        "sink": sink,
        "sink_cls": _Sink,
        "_confirm": _confirm,
        "state": state,
        "rt": rt,
        "set_status_notice": set_status_notice,
        "status_text": status_text,
        "transient_notice": transient_notice,
        "_app_width": _app_width,
        "_reflow_borders": _reflow_borders,
        "_invalidate": _invalidate,
        "output_window": output_window,
        "tail_following": tail_following,
    }
    return app, context


async def run_fullscreen(rt, state, *, banner: str, session_id: str) -> int:
    """Run the full-screen REPL application. Returns exit code."""
    app, context = create_fullscreen_app(rt, state, banner=banner, session_id=session_id)
    _app_width = context["_app_width"]
    _reflow_borders = context["_reflow_borders"]
    _invalidate = context["_invalidate"]

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

    previous_sigint = None
    if os.name == "nt":
        previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        result = await app.run_async()
    finally:
        watchers_stop.set()
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
    return result if isinstance(result, int) else 0

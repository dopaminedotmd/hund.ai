"""Full-screen TUI for the Hund REPL.

prompt_toolkit Application with a scrollable, semantically-colored output
buffer, a single input buffer, and an in-app arrow-key confirmation modal.

The output buffer is read-only (safe against stray typing) but focusable, so
the mouse can select text; Ctrl+C copies a selection to the clipboard (or
exits when there is none). The agent turn runs in a background thread.
"""
from __future__ import annotations

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
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
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
from .input import (
    SLASH_COMMANDS,
    SLASH_COMMAND_METAS,
    PromptState,
    SlashCommandCompleter,
    format_duration,
    format_status_bar,
    format_tokens_ratio,
)
from .output import parse_confirm_input, strip_markdown, strip_rich, StreamingMarkdownFilter, _confirm_title, _confirm_detail
from .render import box_bottom as _r_box_bottom, box_top as _r_box_top, refresh_stats, render_response_box
from ..agent.types import ConfirmRequest, ConfirmVerdict

from .phrases import select_thinking_phrase

_S = theme.SEMANTIC

_STYLE = theme.make_pt_style("bone")


def _trunc(val: Any, max_len: int = 45) -> str:
    s = str(val or "")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _format_tool_desc(name: str, args: dict | None) -> str:
    args = args or {}
    if name == "read_file":
        path = _trunc(args.get("path", ""))
        return f"read {path}"
    elif name == "search_files":
        pattern = _trunc(args.get("pattern", "*"))
        path = args.get("path")
        if path and path != ".":
            return f"searched {_trunc(path)} for {pattern}"
        return f"searched {pattern}"
    elif name == "write_file":
        path = _trunc(args.get("path", ""))
        return f"wrote {path}"
    elif name == "delete_file":
        path = _trunc(args.get("path", ""))
        return f"deleted {path}"
    elif name == "terminal":
        cmd = _trunc(args.get("command", ""))
        return f"ran {cmd}"
    elif name == "web_search":
        q = _trunc(args.get("query", ""))
        return f"searched the web for {q}"
    elif name == "web_extract":
        url = _trunc(args.get("url", ""))
        return f"read {url}"
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
    m_stat = re.search(r"^(.*?\b)(CLR|PRC|EFF|END|MAS)(\s+\w+\s+)([█░]+)(\s+\d+%)(\s*)$", part)
    if m_stat:
        return [
            ("", m_stat.group(1)),
            ("class:accent bold", m_stat.group(2)),
            ("class:primary", m_stat.group(3)),
            ("class:learning", m_stat.group(4)),
            ("class:secondary", m_stat.group(5)),
            ("", m_stat.group(6)),
        ]
    m_skill = re.search(r"^(.*?\s+)([\w\-]+)(\s+)([█░]+)(\s+\d+%)(\s*)$", part)
    if m_skill:
        return [
            ("", m_skill.group(1)),
            ("class:primary", m_skill.group(2)),
            ("", m_skill.group(3)),
            ("class:learning", m_skill.group(4)),
            ("class:secondary", m_skill.group(5)),
            ("", m_skill.group(6)),
        ]
    return [("class:primary", part)]


def _lex_banner_line(line: str) -> list[tuple[str, str]]:
    if line.startswith("╔") and line.endswith("╗"):
        return [("class:accent", line)]
    if line.startswith("╚") and line.endswith("╝"):
        return [("class:accent", line)]
    if not (line.startswith("║") and line.endswith("║")):
        return [("class:primary", line)]

    content = line[1:-1]
    tokens: list[tuple[str, str]] = [("class:accent", "║")]

    if any(c in content for c in ("▄▄", "▀██", "████▄")):
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
    elif re.match(r"^\s+(OS|HOST|CPU|RAM|GPU|MODEL)\s+", content):
        m = re.match(r"^(\s+)(OS|HOST|CPU|RAM|GPU|MODEL)(\s+)(.*)$", content)
        if m:
            tokens.append(("", m.group(1)))
            tokens.append(("class:label", m.group(2)))
            tokens.append(("", m.group(3)))
            tokens.append(("class:primary", m.group(4)))
    elif "── BASE ATTRIBUTES ──" in content or "── SKILLS" in content:
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
        tokens.append(("class:primary", content))

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
                    tokens.append(("class:accent", "⟳"))
                    tokens.append(("class:tool", rest[1:]))
                elif rest.startswith("✓"):
                    tokens.append(("class:success", "✓"))
                    tokens.append(("class:tool", rest[1:]))
                elif rest.startswith("✗") or rest.startswith("⊘"):
                    tokens.append(("class:danger", rest[0]))
                    tokens.append(("class:danger", rest[1:]))
                else:
                    tokens.append(("class:secondary", rest))
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
                line.startswith("  hund ")
                or stripped.startswith("hund is ")
                or stripped.startswith("hund was ")
                or (stripped.startswith("hund ") and stripped.endswith("."))
            ):
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
                meta_match = re.search(r"^(.*?─\s+)([0-9.]+(?:s|ms|m|h)?|\w+)(\s+─+┘|─+┘|┘)$", line)
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

_CONFIRM_OPTIONS = [
    (ConfirmVerdict.APPROVE_ONCE, "Run once", "class:success"),
    (ConfirmVerdict.EDIT, "Edit command", "class:accent"),
    (ConfirmVerdict.ALLOW_SESSION, "Allow for this session", "class:warning"),
    (ConfirmVerdict.DENY, "Deny", "class:danger"),
]


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
    completer = SlashCommandCompleter()
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
        content=FormattedTextControl(lambda: [("class:prompt", "❯ ")]),
        width=3,
        dont_extend_width=True,
        height=_input_height,
        dont_extend_height=False,
    )
    input_row = VSplit([prompt_window, input_window])

    output_control.fallback_focus = input_window

    # ---- status bar ----
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
            ("class:header", " " + cleaned_model),
            ("class:status", f" │ {token_str} │ {duration_str}"),
        ]
        if lat is not None and lat > 0:
            segments.append(("class:status", f" │ {lat:.1f}s"))
        return segments

    status_window = Window(content=FormattedTextControl(status_text), height=1)

    # ---- confirmation modal (arrow-key select) ----
    _confirm = {
        "active": False,
        "title": "hund wants to run a command",
        "detail": "",
        "selected": 0,
        "answer": ConfirmVerdict.DENY,
        "event": threading.Event(),
    }

    def _confirm_text():
        if not _confirm["active"]:
            return []
        W = 64
        out: list[tuple[str, str]] = []

        def row(content: str, style: str = "class:primary") -> None:
            out.append(("class:secondary", "│ "))
            out.append((style, content))
            out.append(("class:secondary", " " * max(W - 4 - len(content), 0) + " │\n"))

        title = _confirm.get("title", "hund wants to run a command")
        title_dashes = max(W - len(title) - 5, 2)
        out.append(("class:secondary", "┌─ "))
        out.append(("class:warning bold", title))
        out.append(("class:secondary", " " + "─" * title_dashes + "┐\n"))

        row("", "class:secondary")
        detail = _confirm.get("detail", "")
        row(f"  {detail}", "class:accent")
        row("", "class:secondary")
        for i, (_code, label, color) in enumerate(_CONFIRM_OPTIONS):
            if i == _confirm["selected"]:
                row("  ❯ ● " + label, color + " bold")
            else:
                row("    ○ " + label, "class:secondary")
        row("", "class:secondary")
        out.append(("class:secondary", "└" + "─" * (W - 2) + "┘\n"))
        out.append(("class:secondary", "   ↑↓ select · Enter confirm · Esc deny"))
        return out

    _thinking: dict[str, Any] = {
        "active": False,
        "text": "hund is reading",
        "past": None,
        "dot_count": 1,
        "start_time": 0.0,
    }

    def _thinking_text() -> list[tuple[str, str]]:
        if not _thinking["active"]:
            return []
        dots = "." * _thinking["dot_count"]
        return [("class:thinking", f"  {_thinking['text']}{dots}\n")]

    thinking_window = Window(
        content=FormattedTextControl(_thinking_text),
        height=1,
        dont_extend_height=True,
    )
    thinking_container = ConditionalContainer(
        thinking_window, filter=Condition(lambda: bool(_thinking["active"]))
    )

    confirm_window = Window(content=FormattedTextControl(_confirm_text), height=12)
    confirm_container = ConditionalContainer(
        confirm_window, filter=Condition(lambda: _confirm["active"])
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
                thinking_container,
                input_border_top,
                input_row,
                input_border_bottom,
                status_window,
            ]),
            floats=[
                Float(
                    content=confirm_container,
                ),
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=12),
                )
            ],
        ),
        focused_element=input_window,
    )

    # ---- shared mutable state ----
    holder: dict[str, Any] = {}
    turn_running = [False]

    def _invalidate() -> None:
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

    def _box_top(width: int | None = None) -> str:
        return _r_box_top(width if width is not None else _app_width())

    def _box_bottom(meta: str | None = None, width: int | None = None) -> str:
        return _r_box_bottom(width if width is not None else _app_width(), meta=meta)

    _append_lock = threading.Lock()

    def _set_output(new_text: str) -> None:
        """Set output_buffer with cursor at start-of-last-line so horizontal scroll is always 0."""
        last_nl = new_text.rfind("\n")
        cur_pos = last_nl + 1 if last_nl >= 0 else 0
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
    actual_width = _app_width()
    rendered_banner = build_startup_banner(rt, width=actual_width)
    seed = rendered_banner.rstrip("\n") + "\n\n"
    _set_output(seed)

    def _reflow_borders() -> None:
        """Re-width response box borders and re-wrap content to the current terminal width."""
        with _append_lock:
            text = output_buffer.text
            lines = text.split("\n")
            new_lines: list[str] = []
            changed = False
            in_box = False
            in_banner = False
            box_lines: list[str] = []

            for line in lines:
                if (
                    line.startswith("╔")
                    and line.endswith("╗")
                    and "SKILLS" not in line
                    and "DETAIL" not in line
                    and "CARD" not in line
                    and line.strip("╔═╗") == ""
                ):
                    in_banner = True
                    new_banner = build_startup_banner(rt, width=_app_width())
                    new_lines.extend(new_banner.split("\n"))
                    changed = True
                elif in_banner and (line.startswith("╚") and line.endswith("╝")):
                    in_banner = False
                elif in_banner:
                    continue
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

                    # Unbox lines
                    content_lines: list[str] = []
                    for bl in box_lines:
                        if not bl.strip("│ "):
                            continue  # Skip top/bottom padding rows
                        if bl.startswith("│  ") and bl.endswith("  │"):
                            content_lines.append(bl[3:-3].rstrip())
                        elif bl.startswith("│ ") and bl.endswith(" │"):
                            content_lines.append(bl[2:-2].rstrip())
                        elif bl.startswith("│") and bl.endswith("│"):
                            content_lines.append(bl[1:-1].rstrip())
                        else:
                            content_lines.append(bl.rstrip())
                    raw_content = "\n".join(content_lines).strip("\n")
                    re_boxed = render_response_box(raw_content, _app_width(), meta=box_meta)
                    new_lines.extend(re_boxed.split("\n"))
                    changed = True
                elif in_box:
                    box_lines.append(line)
                else:
                    new_lines.append(line)

            if changed:
                new_text = "\n".join(new_lines)
                _set_output(new_text)
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
            self._tool_switched = False
            self._user_input = ""
            self._turn_start_time: float = 0.0
            self._anim_timer: threading.Timer | None = None
            self._pending_past_timer: threading.Timer | None = None
            self._md = StreamingMarkdownFilter()
            self._snapshot = None

        def set_user_input(self, text: str) -> None:
            self._user_input = text or ""
            self._tool_switched = False
            self._turn_start_time = time.time()

        def set_turn_snapshot(self, snapshot) -> None:
            self._snapshot = snapshot

        def _cancel_timers(self) -> None:
            if self._anim_timer is not None:
                try:
                    self._anim_timer.cancel()
                except Exception:
                    pass
                self._anim_timer = None
            if self._pending_past_timer is not None:
                try:
                    self._pending_past_timer.cancel()
                except Exception:
                    pass
                self._pending_past_timer = None

        def _start_anim_timer(self) -> None:
            if self._anim_timer is not None:
                try:
                    self._anim_timer.cancel()
                except Exception:
                    pass

            def _tick() -> None:
                if _thinking["active"]:
                    _thinking["dot_count"] = (_thinking["dot_count"] % 3) + 1
                    _invalidate()
                    self._anim_timer = threading.Timer(0.3, _tick)
                    self._anim_timer.daemon = True
                    self._anim_timer.start()

            self._anim_timer = threading.Timer(0.3, _tick)
            self._anim_timer.daemon = True
            self._anim_timer.start()

        def thinking(self, msg: str | None = None) -> None:
            if not self._turn_start_time:
                self._turn_start_time = time.time()
            self._cancel_timers()
            _thinking["active"] = True
            _thinking["text"] = msg.rstrip(".…") if msg else "hund is reading"
            _thinking["past"] = None
            _thinking["dot_count"] = 1
            _thinking["start_time"] = time.time()
            self._tool_switched = False
            self._start_anim_timer()
            _invalidate()

        def clear_thinking(self) -> None:
            self._cancel_timers()
            if _thinking["active"]:
                _thinking["active"] = False
                past = _thinking.get("past")
                start_time = _thinking.get("start_time", 0.0)
                _thinking["past"] = None
                _invalidate()

                if past:
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
            boxed = render_response_box(self._raw_response, _app_width())
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
                boxed = render_response_box(self._raw_response, _app_width(), meta=meta)

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

                if reflection_lines and not input_buffer.text.strip():
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
                self._raw_response = ""
                self._turn_start_time = 0.0
                _invalidate()
            else:
                append("\n\n")
                self._turn_start_time = 0.0

        def error(self, markup: str) -> None:
            clean = strip_rich(strip_markdown(markup)).strip()
            if self._tool_marker is not None:
                err_line = f"  ┊ ✗ error: {_trunc(clean, 50)}\n"
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + err_line
                    _set_output(new_text)
                self._tool_marker = None
                _invalidate()
            else:
                append(clean + "\n")

        def confirm(self, request: ConfirmRequest) -> ConfirmVerdict:
            title = _confirm_title(request)
            detail = _confirm_detail(request)
            if len(detail) > 58:
                detail = detail[:55] + "..."
            _confirm["title"] = title
            _confirm["detail"] = detail
            _confirm["selected"] = 0
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = True
            _MODAL_ACTIVE[0] = True
            with _append_lock:
                _set_output(output_buffer.text)
            _confirm["event"].clear()
            _invalidate()
            _confirm["event"].wait()
            _confirm["active"] = False
            _MODAL_ACTIVE[0] = False
            with _append_lock:
                _set_output(output_buffer.text)
            _invalidate()
            return _confirm["answer"]

        def tool_start(self, name: str, args) -> None:
            if not self._tool_switched:
                u_text = self._user_input
                if not u_text and messages:
                    u_text = next(
                        (m.content for m in reversed(messages) if getattr(m, "role", "") == "user"),
                        "",
                    )
                gerund, past = select_thinking_phrase(u_text)
                _thinking["text"] = gerund
                _thinking["past"] = past
                _thinking["start_time"] = time.time()
                _thinking["active"] = True
                self._tool_switched = True
                self._start_anim_timer()
                _invalidate()

            if self._box_open:
                self._box_open = False
                self._box_start_marker = None
                self._raw_response = ""

            self._tool_args = args if isinstance(args, dict) else {}
            self._tool_start_time = time.time()
            self._tool_marker = len(output_buffer.text)
            desc = _format_tool_desc(name, self._tool_args)
            append(f"  ┊ ⟳ {desc}\n")

        def tool_result(self, name: str, shown: str) -> None:
            dur = time.time() - self._tool_start_time
            dur_str = f"{dur:.1f}s"
            desc = _format_tool_desc(name, self._tool_args)
            body = ""
            if name == "write_file" and isinstance(self._tool_args, dict):
                content = self._tool_args.get("content")
                if isinstance(content, str) and content.strip():
                    lines = content.rstrip("\n").splitlines()
                    max_lines = 40
                    visible = lines[:max_lines]
                    body = "".join(f"      + {ln}\n" for ln in visible)
                    if len(lines) > max_lines:
                        body += f"      ... ({len(lines) - max_lines} more lines)\n"
            elif name in ("edit_file", "patch", "apply_patch", "replace_file_content") and isinstance(self._tool_args, dict):
                diff = self._tool_args.get("diff") or self._tool_args.get("patch")
                if isinstance(diff, str) and diff.strip():
                    diff_lines = diff.rstrip("\n").splitlines()
                    body = "".join(f"      {ln}\n" for ln in diff_lines[:40])
                else:
                    target = self._tool_args.get("target_content")
                    replacement = self._tool_args.get("replacement_content")
                    if isinstance(target, str) and isinstance(replacement, str):
                        t_lines = target.rstrip("\n").splitlines()
                        r_lines = replacement.rstrip("\n").splitlines()
                        body = "".join(f"      - {ln}\n" for ln in t_lines) + "".join(f"      + {ln}\n" for ln in r_lines)

            result_line = f"  ┊ ✓ {desc}  {dur_str}\n" + body
            if self._tool_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + result_line
                    _set_output(new_text)
                self._tool_marker = None
                _invalidate()
            else:
                append(result_line)

        def blocked(self, name: str, reason: str) -> None:
            clean_reason = _trunc(reason, 40)
            blocked_line = f"  ┊ ✗ blocked {name} — {clean_reason}\n"
            if self._tool_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + blocked_line
                    _set_output(new_text)
                self._tool_marker = None
                _invalidate()
            else:
                append(blocked_line)

        def declined(self, name: str, reason: str) -> None:
            clean_reason = _trunc(reason, 40)
            declined_line = f"  ┊ ✗ declined {name} — {clean_reason}\n"
            if self._tool_marker is not None:
                with _append_lock:
                    new_text = output_buffer.text[: self._tool_marker] + declined_line
                    _set_output(new_text)
                self._tool_marker = None
                _invalidate()
            else:
                append(declined_line)

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
        refresh_stats(state)
        _reflow_borders()
        _invalidate()

    # ---- agent turn runner (background thread) ----
    def _spawn_turn(echo_user: str | None) -> None:
        turn_running[0] = True
        run_id = uuid.uuid4().hex
        user_text = echo_user
        if echo_user is not None:
            w = max(_app_width() - 4, 20)
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
            messages.append(Message(role="user", content=echo_user))
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
            user_text=user_text or "",
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
    confirm_active = Condition(lambda: _confirm["active"])

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
        _confirm["selected"] = (_confirm["selected"] - 1) % len(_CONFIRM_OPTIONS)
        event.app.invalidate()

    @kb.add("down", filter=confirm_active)
    def _down(event):
        _confirm["selected"] = (_confirm["selected"] + 1) % len(_CONFIRM_OPTIONS)
        event.app.invalidate()

    @kb.add("enter", filter=confirm_active)
    def _enter(event):
        _confirm["answer"] = _CONFIRM_OPTIONS[_confirm["selected"]][0]
        _confirm["active"] = False
        _MODAL_ACTIVE[0] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("y", filter=confirm_active)
    def _y(event):
        _confirm["answer"] = ConfirmVerdict.APPROVE_ONCE
        _confirm["active"] = False
        _MODAL_ACTIVE[0] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("e", filter=confirm_active)
    def _e(event):
        _confirm["answer"] = ConfirmVerdict.EDIT
        _confirm["active"] = False
        _MODAL_ACTIVE[0] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("a", filter=confirm_active)
    def _a(event):
        _confirm["answer"] = ConfirmVerdict.ALLOW_SESSION
        _confirm["active"] = False
        _MODAL_ACTIVE[0] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("n", filter=confirm_active)
    @kb.add("escape", filter=confirm_active)
    def _n(event):
        _confirm["answer"] = ConfirmVerdict.DENY
        _confirm["active"] = False
        _MODAL_ACTIVE[0] = False
        _confirm["event"].set()
        _invalidate()

    @kb.add("escape", filter=~confirm_active)
    def _escape(event):
        if output_buffer.selection_state is not None:
            output_buffer.exit_selection()
        layout.focus(input_window)
        _invalidate()

    @kb.add("c-c")
    def _ctrl_c(event):
        if _confirm["active"]:
            _confirm["answer"] = ConfirmVerdict.DENY
            _confirm["active"] = False
            _MODAL_ACTIVE[0] = False
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
        _scroll_lines(3)

    @kb.add("<scroll-down>")
    def _scroll_down(event):
        _scroll_lines(-3)

    @kb.add("enter", filter=has_focus(input_window) & ~confirm_active)
    def _enter_submit(event):
        input_buffer.validate_and_handle()

    @kb.add("c-j", filter=has_focus(input_window) & ~confirm_active)
    def _newline_input(event):
        input_buffer.insert_text("\n")

    @kb.add(Keys.Any, filter=has_focus(output_window) & ~confirm_active)
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
    initial_skin = getattr(state, "theme_name", "bone") or "bone"
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=theme.make_pt_style(initial_skin),
        mouse_support=True,
    )
    holder["app"] = app

    # Re-width box borders when the terminal is resized (polling is cheap).
    def _width_watcher() -> None:
        last = -1
        while True:
            time.sleep(0.05)
            w = _app_width()
            if w != last:
                last = w
                _reflow_borders()

    threading.Thread(target=_width_watcher, daemon=True).start()

    result = await app.run_async()
    return result if isinstance(result, int) else 0


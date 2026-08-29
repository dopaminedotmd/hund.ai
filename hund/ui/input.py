"""Prompt Toolkit input session, slash command autocomplete, and status bar.

Input:
- WordCompleter with short descriptions for instant completion on '/'
- Bottom toolbar: model │ tokens/limit │ session duration │ ⏱ latency
- Single-line and multi-line keybindings
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, CompleteEvent, WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from collections.abc import Iterable

from ..paths import hund_home
from ..agent.user_context import workspace_files
from . import theme
from .command_spec import get_autocomplete_metas
from .keys import build_repl_keybindings

SLASH_COMMAND_METAS: dict[str, str] = get_autocomplete_metas()


SLASH_COMMANDS = list(SLASH_COMMAND_METAS.keys())
MAX_VISIBLE_COMPLETIONS = 6


def normalize_terminal_input(text: str) -> str:
    """Convert Win32 UTF-16 surrogate input into UTF-8-safe Unicode text."""
    if not any(0xD800 <= ord(char) <= 0xDFFF for char in text):
        return text

    normalized: list[str] = []
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        if 0xD800 <= codepoint <= 0xDBFF and index + 1 < len(text):
            low = ord(text[index + 1])
            if 0xDC00 <= low <= 0xDFFF:
                scalar = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)
                normalized.append(chr(scalar))
                index += 2
                continue
        if 0xD800 <= codepoint <= 0xDFFF:
            normalized.append("\uFFFD")
        else:
            normalized.append(text[index])
        index += 1
    return "".join(normalized)


def resolve_slash_command(text: str) -> str:
    """Resolve exact or prefix slash command to full command name, preserving args.

    Examples:
        '/mod' -> '/model'
        '/sk' -> '/skills'
        '/sta' -> '/stats'
        '/mod deepseek' -> '/model deepseek'
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return stripped
    parts = stripped.split(maxsplit=1)
    cmd_token = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Exact match check
    for cmd in SLASH_COMMANDS:
        if cmd_token == cmd.lower():
            return f"{cmd} {args}".strip()

    # Prefix match check
    candidates = [cmd for cmd in SLASH_COMMANDS if cmd.lower().startswith(cmd_token)]
    if candidates:
        return f"{candidates[0]} {args}".strip()

    return stripped


def _fuzzy_score(query: str, candidate: str) -> tuple[int, int] | None:
    """Score multi-word subsequence matches; lower values are better."""
    tokens = [token for token in query.lower().split() if token]
    haystack = candidate.lower()
    total_gap = 0
    for token in tokens:
        position = -1
        first = None
        for char in token:
            position = haystack.find(char, position + 1)
            if position < 0:
                return None
            if first is None:
                first = position
        total_gap += position - (first or 0) - len(token) + 1
    return total_gap, len(candidate)


class SlashCommandCompleter(Completer):
    """Fuzzy, multi-word slash command completer."""

    def __init__(self, workspace: Any = None) -> None:
        self.workspace = workspace

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor.lstrip()
        token = document.get_word_before_cursor(WORD=True)
        if token.startswith("@"):
            if token.startswith("@file:") and self.workspace is not None:
                query = token[len("@file:"):]
                for path in workspace_files(self.workspace, query):
                    yield Completion(
                        text=f"@file:{path}",
                        start_position=-len(token),
                        display=path,
                        display_meta="workspace file",
                    )
            else:
                for item, meta in (
                    ("@file:", "attach workspace file"),
                    ("@git:diff", "attach working tree diff"),
                    ("@git:status", "attach git status"),
                ):
                    if item.startswith(token.lower()):
                        yield Completion(item, start_position=-len(token), display_meta=meta)
            return
        if not text.startswith("/"):
            return
        if text.endswith(" ") and text.strip().lower() in {
            command.lower() for command in SLASH_COMMANDS
        }:
            return
        query = text.lower()
        ranked: list[tuple[tuple[int, int], str, str]] = []
        for cmd, meta in SLASH_COMMAND_METAS.items():
            query_parts = query.split()
            score = _fuzzy_score(query_parts[0], cmd)
            if score is not None and len(query_parts) > 1:
                meta_score = _fuzzy_score(" ".join(query_parts[1:]), meta)
                score = (
                    (score[0] + meta_score[0], score[1] + meta_score[1])
                    if meta_score is not None
                    else None
                )
            if score is not None:
                ranked.append((score, cmd, meta))
        for _score, cmd, meta in sorted(ranked):
            yield Completion(
                text=cmd,
                start_position=-len(text),
                display=cmd,
                display_meta=meta,
            )


@dataclass
class PromptState:
    """Cached stats & telemetry for bottom_toolbar. Updated per turn."""
    stats_text: list[tuple[str, str]] | None = None
    prev_tiers: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None
    theme_name: str = "marshmallow"
    notifications_enabled: bool = True
    start_time: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)


def format_tokens_ratio(tokens: int, limit: int = 1_000_000) -> str:
    """Format token consumption ratio, e.g. 4.6K/1M or 14K/128K."""
    if tokens >= 1_000_000:
        t_str = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 10_000:
        t_str = f"{tokens // 1000}K"
    elif tokens >= 1_000:
        t_str = f"{tokens / 1000:.1f}K"
    else:
        t_str = f"{tokens}"

    if limit >= 1_000_000:
        l_str = f"{limit // 1_000_000}M"
    elif limit >= 1_000:
        l_str = f"{limit // 1000}K"
    else:
        l_str = f"{limit}"
    return f"{t_str}/{l_str}"


def format_duration(seconds: float) -> str:
    """Format elapsed seconds into e.g. 4h 27m or 12m or 45s."""
    secs = int(max(0, seconds))
    hours = secs // 3600
    minutes = (secs % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m"
    return f"{secs}s"


def format_status_bar(
    model: str,
    tokens: int = 0,
    limit: int = 1_000_000,
    duration_s: float = 0.0,
    latency_s: float | None = None,
) -> str:
    """Build canonical single-line status bar text (no emojis, latency optional)."""
    # Clean model name e.g. "DeepSeek (deepseek-v4-pro)" -> "deepseek-v4-pro"
    cleaned_model = model
    if "(" in model and ")" in model:
        cleaned_model = model.split("(")[-1].split(")")[0].strip()
    if not cleaned_model:
        cleaned_model = "deepseek-v4-flash"

    token_str = format_tokens_ratio(tokens, limit)
    duration_str = format_duration(duration_s)

    base = f"{cleaned_model} │ {token_str} │ {duration_str}"
    if latency_s is not None and latency_s > 0:
        return f"{base} │ {latency_s:.1f}s"
    return base


def _toolbar(state: PromptState):
    """Render single-line dim status bar for bottom toolbar."""
    model = state.extra.get("model", "deepseek-v4-flash")
    tokens = state.extra.get("tokens", 0)
    limit = state.extra.get("token_limit", 1_000_000)
    duration_s = time.time() - state.start_time
    latency_s = state.extra.get("last_latency_s")

    text = format_status_bar(model, tokens, limit, duration_s, latency_s)
    return [("class:bottom-toolbar fg:ansibrightblack", text)]


def create_session(state: PromptState) -> PromptSession:
    completer = WordCompleter(
        SLASH_COMMANDS,
        ignore_case=True,
        meta_dict=SLASH_COMMAND_METAS,
        sentence=False,
    )
    history_path = hund_home() / "repl_history"
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    return PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        bottom_toolbar=lambda: _toolbar(state),
        multiline=False,
        vi_mode=False,
        complete_while_typing=True,
        enable_history_search=True,
        key_bindings=build_repl_keybindings(),
        style=Style.from_dict({"bottom-toolbar": "fg:#3E4451"}),
    )


def prompt_message() -> str:
    """Prompt prefix '❯ '."""
    return f"{theme.USER_PREFIX} "

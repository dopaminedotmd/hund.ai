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
from . import theme
from .keys import build_repl_keybindings

SLASH_COMMAND_METAS: dict[str, str] = {
    "/exit": "Exit the REPL session",
    "/help": "Show command palette and keybindings",
    "/stats": "View character card and RPG stats",
    "/model": "View or switch active LLM model",
    "/skills": "Manage and inspect equipped skills and vault",
    "/profile": "View host hardware and environment profile",
    "/tools": "List registered tools and risk levels",
    "/history": "View session turn history",
    "/clear": "Clear active conversation context",
    "/progress": "View session activity and progression",
    "/domains": "View domain confidence and specializations",
    "/memory": "Show and manage persistent user memory",
    "/export": "Export session transcript to file",
    "/config": "View active configuration settings",
    "/copy": "Copy last assistant response to clipboard",
    "/theme": "Switch terminal visual palette",
    "/session": "Inspect or search session archive",
    "/retry": "Regenerate last assistant response",
    "/restore": "Restore previous session messages into active context",
    "/notifications": "Toggle desktop notifications",
    "/mascot": "Display Hund ASCII mascot",
    "/usage": "View token and resource consumption",
    "/doctor": "Run hardware and system diagnosis",
    "/compress": "Compress context to save tokens",
    "/diff": "View working tree modifications",
    "/undo": "File backup and restore information",
    "/lessons": "View learned lessons and feedback",
}


SLASH_COMMANDS = list(SLASH_COMMAND_METAS.keys())


class SlashCommandCompleter(Completer):
    """Context-aware slash command completer that properly filters prefixes."""

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return
        # Stop completing once space/arguments are entered
        if " " in text:
            return
        query = text.lower()
        for cmd, meta in SLASH_COMMAND_METAS.items():
            if cmd.lower().startswith(query):
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
    theme_name: str = "bone"
    notifications_enabled: bool = True
    start_time: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)


def format_tokens_ratio(tokens: int, limit: int = 1_000_000) -> str:
    """Format token consumption ratio, e.g. 274K/1M or 14K/128K."""
    if tokens >= 1_000_000:
        t_str = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        t_str = f"{tokens // 1000}K"
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
        cleaned_model = "deepseek-v4-pro"

    token_str = format_tokens_ratio(tokens, limit)
    duration_str = format_duration(duration_s)

    base = f"{cleaned_model} │ {token_str} │ {duration_str}"
    if latency_s is not None and latency_s > 0:
        return f"{base} │ {latency_s:.1f}s"
    return base


def _toolbar(state: PromptState):
    """Render single-line dim status bar for bottom toolbar."""
    model = state.extra.get("model", "deepseek-v4-pro")
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

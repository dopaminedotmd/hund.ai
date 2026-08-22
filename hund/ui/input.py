"""Prompt Toolkit-input: history, autocomplete, Ctrl+R, bottom_toolbar stats.

Enter = send. Alt+Enter (Esc,Enter) = new line.
bottom_toolbar displays single-line status bar with model, tokens, workspace, and stats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from ..paths import hund_home
from . import theme
from .keys import build_repl_keybindings

SLASH_COMMANDS = [
    "/exit", "/stats", "/skills", "/profile", "/tools",
    "/history", "/clear", "/progress", "/domains", "/memory",
    "/help", "/export", "/config", "/theme", "/session", "/retry",
    "/notifications", "/mascot",
]


@dataclass
class PromptState:
    """Cached stats & telemetry for bottom_toolbar. Updated per turn."""
    stats_text: list[tuple[str, str]] | None = None
    prev_tiers: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None
    theme_name: str = "default"
    notifications_enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def _toolbar(state: PromptState):
    """Render single-line dim status bar for bottom toolbar."""
    model = state.extra.get("model", "DeepSeek")
    tokens = state.extra.get("tokens", 0)
    ctx_str = f"{tokens // 1000}k ctx" if tokens >= 1000 else f"{tokens} ctx" if tokens else "ready"
    ws = state.extra.get("workspace", "hund.ai")

    segs: list[tuple[str, str]] = [
        ("class:bottom-toolbar fg:ansicyan bold", f"[{model}] "),
        ("class:bottom-toolbar fg:ansibrightblack", f"│ {ctx_str} │ {ws} │ "),
    ]

    if state.stats_text:
        segs.extend(state.stats_text)
    else:
        segs.append(("class:bottom-toolbar fg:ansibrightblack", "hund"))
    return segs


def create_session(state: PromptState) -> PromptSession:
    completer = WordCompleter(SLASH_COMMANDS, ignore_case=True, meta_dict={
        c: "" for c in SLASH_COMMANDS
    })
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
        multiline=False,            # Enter = send
        vi_mode=False,
        complete_while_typing=True,
        enable_history_search=True,  # Ctrl+R
        key_bindings=build_repl_keybindings(),
    )


def prompt_message() -> str:
    """Prompt prefix 'user > ' (formatted by PT)."""
    return f"{theme.USER_PREFIX} "

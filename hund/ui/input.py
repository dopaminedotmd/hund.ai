"""Prompt Toolkit-input: history, autocomplete, Ctrl+R, bottom_toolbar stats.

Enter = skicka. Alt+Enter (Esc,Enter) = ny rad (Discord/Telegram).
bottom_toolbar visar stats-rad (en lösning, inte \r).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from ..paths import hund_home
from . import theme

# Slash-kommandon (P0: bara /exit live; resten autocomplete + P1-handlers)
SLASH_COMMANDS = [
    "/exit", "/stats", "/skills", "/profile", "/tools",
    "/history", "/clear", "/progress", "/domains", "/memory",
    "/help", "/export", "/config", "/theme", "/session", "/retry",
    "/notifications", "/mascot",
]


@dataclass
class PromptState:
    """Cachead stats-rad for bottom_toolbar. Uppdateras per turn, inte per tangent."""
    stats_text: list[tuple[str, str]] | None = None
    prev_tiers: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None
    theme_name: str = "default"
    notifications_enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def _make_keybindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _newline(event) -> None:
        # Alt+Enter / Esc,Enter -> ny rad i bufferten (Enter ensamt skickar)
        event.current_buffer.insert_text("\n")

    return kb


def _toolbar(state: PromptState):
    if state.stats_text:
        return state.stats_text
    return [("class:bottom-toolbar", "hund")]


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
        multiline=False,            # Enter = skicka
        vi_mode=False,
        complete_while_typing=True,
        enable_history_search=True,  # Ctrl+R
        key_bindings=_make_keybindings(),
    )


def prompt_message() -> str:
    """Prompt-prefix 'du> ' (formateras av PT)."""
    return f"{theme.USER_PREFIX} "

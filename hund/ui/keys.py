"""Centralized keybinding registry and prompt_toolkit keybindings for hund.ui.

Unified keymap architecture:
- Context-aware key handling (Input vs Confirm vs Streaming).
- Chord sequences (Alt+Enter / Esc,Enter for newlines).
- Documented keymap table for /help palette and status hints.
"""
from __future__ import annotations

from typing import Callable
from prompt_toolkit.key_binding import KeyBindings

KEYMAP: dict[str, list[dict[str, str]]] = {
    "Chat Input": [
        {"key": "Enter", "action": "Send prompt / execute command"},
        {"key": "Alt+Enter (Esc,Enter)", "action": "Insert newline (multi-line input)"},
        {"key": "Ctrl+R", "action": "Reverse search prompt history"},
        {"key": "Tab", "action": "Auto-complete slash commands"},
        {"key": "Ctrl+C", "action": "Cancel current line (double-tap to exit)"},
        {"key": "Ctrl+D / /exit", "action": "Exit REPL cleanly"},
    ],
    "Confirmation Modal": [
        {"key": "y", "action": "Approve and execute once"},
        {"key": "e", "action": "Edit command before execution"},
        {"key": "a", "action": "Allow tool for this session"},
        {"key": "n / Esc / Enter", "action": "Deny and abort (default)"},
    ],
    "Streaming Output": [
        {"key": "Ctrl+C", "action": "Interrupt active agent generation"},
    ],
}


def build_repl_keybindings(
    *,
    on_newline: Callable[[], None] | None = None,
) -> KeyBindings:
    """Build standardized KeyBindings for REPL prompt session."""
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _handle_newline(event) -> None:
        """Alt+Enter / Esc,Enter -> insert newline in buffer."""
        if on_newline:
            on_newline()
        event.current_buffer.insert_text("\n")

    return kb


def format_keymap_summary() -> list[str]:
    """Format keymap as rows for /help command."""
    lines: list[str] = []
    for section, entries in KEYMAP.items():
        lines.append(f"[bold cyan]{section}[/bold cyan]")
        for entry in entries:
            key = entry["key"]
            action = entry["action"]
            lines.append(f"  [bold white]{key:<24}[/bold white] [dim]{action}[/dim]")
    return lines

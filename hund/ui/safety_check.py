"""Workspace safety trust check for Hund REPL.

Prompts the user once per workspace (similar to Claude Code folder trust)
with interactive arrow-key selection and persists trusted paths in
%LOCALAPPDATA%/hund/brain/trusted_workspaces.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from rich.console import Console

from ..paths import hund_home

_TRUST_FILE = "trusted_workspaces.json"


def _get_trust_path() -> Path:
    return hund_home() / "brain" / _TRUST_FILE


def _normalize_path(p: Path | str) -> str:
    try:
        return str(Path(p).resolve()).lower()
    except Exception:
        return str(p).lower()


def load_trusted_workspaces() -> list[str]:
    """Load list of trusted workspace paths."""
    path = _get_trust_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [_normalize_path(p) for p in data]
    except Exception:
        pass
    return []


def is_workspace_trusted(workspace: Path | str) -> bool:
    """Check if the given workspace path is already trusted."""
    norm = _normalize_path(workspace)
    trusted = load_trusted_workspaces()
    return norm in trusted


def mark_workspace_trusted(workspace: Path | str) -> None:
    """Persist workspace path to trusted list."""
    norm = _normalize_path(workspace)
    trusted = load_trusted_workspaces()
    if norm not in trusted:
        trusted.append(norm)
    path = _get_trust_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trusted, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def parse_trust_choice(choice: str) -> bool:
    """Parse user choice string for trust prompt."""
    raw = (choice or "").strip().lower()
    if raw in {"", "1", "y", "yes", "enter", "true"}:
        return True
    return False


def interactive_trust_menu(workspace: Path | str) -> bool:
    """Display interactive arrow-key selector for workspace folder trust."""
    options = [
        (True, "1. Yes, I trust this folder"),
        (False, "2. No, exit"),
    ]
    selected = [0]
    ws_str = str(Path(workspace).resolve())

    def get_formatted_text():
        lines = []
        lines.append(("bold fg:ansiwhite", "Accessing workspace: "))
        lines.append(("bold fg:ansicyan", f"{ws_str}\n"))
        lines.append(("fg:ansiwhite", "Quick safety check: Is this a project you created or one you trust?\n\n"))

        for idx, (val, label) in enumerate(options):
            if idx == selected[0]:
                lines.append(("bold fg:ansigreen", f"  ❯ ● [{label}]\n"))
            else:
                lines.append(("fg:ansibrightblack", f"    ○  {label}\n"))

        lines.append(("\nfg:ansibrightblack dim", "Use ↑/↓ arrows to select · Enter to confirm · Esc to cancel"))
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

    @kb.add("1")
    @kb.add("y")
    @kb.add("Y")
    def _opt1(event):
        event.app.exit(result=True)

    @kb.add("2")
    @kb.add("n")
    @kb.add("N")
    @kb.add("escape")
    @kb.add("c-c")
    def _opt2(event):
        event.app.exit(result=False)

    layout = Layout(Window(FormattedTextControl(get_formatted_text), height=8))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)
    try:
        res = app.run()
        return bool(res)
    except Exception:
        return False


async def prompt_workspace_trust(
    console: Console,
    prompt_session: Any,
    workspace: Path | str,
) -> bool:
    """Prompt user once per workspace for folder trust."""
    if is_workspace_trusted(workspace):
        return True

    if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        trusted = interactive_trust_menu(workspace)
    else:
        # Non-interactive / test fallback
        ws_path = str(Path(workspace).resolve())
        console.print(f"[bold]Accessing workspace:[/bold] [cyan]{ws_path}[/cyan]")
        console.print("Quick safety check: Is this a project you created or one you trust?\n")
        console.print("  [bold green]❯ 1.[/bold green] Yes, I trust this folder")
        console.print("    [dim]2.[/dim] No, exit\n")
        console.print("[dim]Enter to confirm · Esc to cancel[/dim]")
        try:
            ans = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "2"
        trusted = parse_trust_choice(ans)

    if trusted:
        mark_workspace_trusted(workspace)
        console.print()
        return True

    return False

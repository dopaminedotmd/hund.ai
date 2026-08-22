"""Workspace safety trust check for Hund REPL.

Prompts the user once per workspace (similar to Claude Code folder trust)
with a simple 1/2/Enter prompt and persists trusted paths in
%LOCALAPPDATA%/hund/brain/trusted_workspaces.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
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
    return _normalize_path(workspace) in load_trusted_workspaces()


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


async def prompt_workspace_trust(
    console: Console,
    prompt_session: Any,
    workspace: Path | str,
) -> bool:
    """Prompt user once per workspace for folder trust (simple 1/2/Enter)."""
    if is_workspace_trusted(workspace):
        return True

    ws_path = str(Path(workspace).resolve())
    console.print(f"[bold]Accessing workspace:[/bold] [cyan]{ws_path}[/cyan]")
    console.print("Quick safety check: Is this a project you created or one you trust?\n")
    console.print("  [bold green]❯ 1.[/bold green] Yes, I trust this folder")
    console.print("    [dim]2.[/dim] No, exit\n")
    console.print("[dim]Enter to confirm · Esc to cancel[/dim]")

    trust_session = PromptSession(
        message=FormattedText([("bold", "Trust? [1/2] ")]),
    )
    try:
        ans = await trust_session.prompt_async()
    except (EOFError, KeyboardInterrupt):
        ans = "2"
    trusted = parse_trust_choice(ans)
    if trusted:
        mark_workspace_trusted(workspace)
        console.print()
    return trusted

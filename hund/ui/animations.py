"""Animations and notification helpers for hund.ui.

Strict zero-emoji ASCII formatting (* instead of glitter glyphs, [OK] for success).
Level-up uses 3 flat async lines that scroll naturally in the terminal history.
"""
from __future__ import annotations

import asyncio

from rich.console import Console

from . import theme

# Notification label mappings (event_type -> label). Zero emojis.
_NOTIFY_LABELS = {
    "skill_created": "[Skills] new skill",
    "forge_approved": "[OK] forge approved",
    "forge_rejected": "[note] forge feedback",
    "memory_updated": "[mem] memory updated",
    "gap_closed": "[gap] gap closed",
}


async def level_up(
    console: Console,
    stat_name: str,
    old_tier: str,
    new_tier: str,
    value: float | None,
) -> None:
    """Three flat async lines on tier change. Scrolls away cleanly without blocking."""
    console.print()
    console.print(
        f"[bold bright_yellow]* * *  {stat_name}: {old_tier} -> {new_tier}!  * * *[/bold bright_yellow]"
    )
    await asyncio.sleep(0.2)
    val_str = f"({value})" if value is not None else ""
    console.print(
        f"[bold green][OK][/bold green]  {stat_name} is now [bold]{new_tier}[/bold]{('  ' + val_str) if val_str else ''}"
    )
    await asyncio.sleep(0.1)
    console.print("[dim]+50 XP (tier elevation bonus)[/dim]")


def notify(console: Console, event_type: str, detail: str = "") -> None:
    """A single subtle dim line in the conversation flow."""
    label = _NOTIFY_LABELS.get(event_type, event_type)
    line = f"{theme.HUND_INDENT}[dim]* {label}"
    if detail:
        line += f" -- {detail}[/dim]"
    else:
        line += "[/dim]"
    console.print(line)

"""Animationer och notifikationer for hund.ui.

ASCII endast (CLAUDE.md): * istallet for ✦, [OK] istallet for emojis.
Level-up = 3 rader, syns i scroll. asyncio.sleep (ej blockande).
"""
from __future__ import annotations

import asyncio

from rich.console import Console

from . import theme

# Notis-etiketter (event_type -> label). Inga emojis.
_NOTIFY_LABELS = {
    "skill_created": "[Skills] ny skill",
    "forge_approved": "[OK] forge godkande",
    "forge_rejected": "[note] forge feedback",
    "memory_updated": "[mem] minne uppdaterat",
    "gap_closed": "[gap] gap stangt",
}


async def level_up(
    console: Console,
    stat_name: str,
    old_tier: str,
    new_tier: str,
    value: float | None,
) -> None:
    """Tre rader vid tier-skifte. Syns i scroll, blockar ej (asyncio.sleep)."""
    console.print()
    console.print(
        f"[bold bright_yellow]* * *  {stat_name}: {old_tier} -> {new_tier}!  * * *[/bold bright_yellow]"
    )
    await asyncio.sleep(0.2)
    val_str = f"({value})" if value is not None else ""
    console.print(
        f"[bold green][OK][/bold green]  {stat_name} ar nu [bold]{new_tier}[/bold]{('  ' + val_str) if val_str else ''}"
    )
    await asyncio.sleep(0.1)
    console.print("[dim]+50 XP (tier-skifte bonus)[/dim]")


def notify(console: Console, event_type: str, detail: str = "") -> None:
    """En dim rad i konversationsflodet. For sophistication i scroll."""
    label = _NOTIFY_LABELS.get(event_type, event_type)
    line = f"{theme.HUND_INDENT}[dim]* {label}"
    if detail:
        line += f" -- {detail}[/dim]"
    else:
        line += "[/dim]"
    console.print(line)

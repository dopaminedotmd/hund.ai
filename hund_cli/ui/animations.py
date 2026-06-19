"""Små Rich-animationer för terminal-UI:n."""
from __future__ import annotations

import time

from rich.progress import BarColumn, Progress, TextColumn


def dots_animation(live, message: str, duration_ms: int = 200) -> None:
    """Visa message med en, två och tre prickar via aktiv Live-instans."""
    delay = max(0, duration_ms) / 1000
    for dots in (".", "..", "..."):
        live.update(f"[dim]{message}{dots}[/dim]", refresh=True)
        time.sleep(delay)


def level_up_glitter(stat: str, old: str, new: str) -> list[str]:
    """Returnera tre glitterframes med roterande symbolpositioner."""
    message = f"{stat}: {old} → {new}!"
    return [
        f"₊ ⊹ ˖ ⭑  {message}  ⭑ ˖ ⊹ ₊",
        f"˖ ⭑ ₊ ⊹  {message}  ⊹ ₊ ⭑ ˖",
        f"⭑ ˖ ⊹ ₊  {message}  ₊ ⊹ ˖ ⭑",
    ]


def level_up_bar(stat: str, pct: int) -> None:
    """Visa transient progress från noll till angiven procent."""
    target = max(0, min(100, pct))
    with Progress(
        TextColumn("[bold green]{task.description}"),
        BarColumn(bar_width=30),
        transient=True,
    ) as progress:
        task = progress.add_task(stat, total=100)
        for value in range(target + 1):
            progress.update(task, completed=value)
            time.sleep(0.002)

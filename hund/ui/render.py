"""Rendering: stats-rad (bottom_toolbar), startup, separator.

Ateranvander hund.stats - ingen ominventering (CLAUDE.md).
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

from ..paths import hund_home
from ..stats import compute_all
from ..stats.tiers import render_bar
from . import theme

# Forsta-gangs-flagg for mascot (plan open question 1 -> visa en gang + /mascot)
_MASCOT_FLAG = "mascot_seen"


def _bar(progress: int, width: int = theme.BAR_WIDTH) -> str:
    return render_bar(progress, width=width)


def stats_bar_segments(stats: dict[str, dict[str, Any]] | None = None):
    """Returnera list[(pt_style, text)] for prompt_toolkit bottom_toolbar.

    En tier-fargad rad:  CLR Mast ████████░ │ PRC Expe ██████░░░ │ ...
    """
    if stats is None:
        try:
            stats = compute_all()
        except Exception:
            stats = {}

    segs: list[tuple[str, str]] = []
    for i, key in enumerate(theme.STAT_ORDER):
        s = (stats or {}).get(key, {})
        abbr = theme.STAT_ABBR[key]
        tier = s.get("tier") or theme.EMDASH
        tier_short = (tier[:4]) if tier else theme.EMDASH
        progress = int(s.get("progress", 0) or 0)
        bar = _bar(progress)
        tier_style = "fg:" + theme.tier_pt(tier)
        if i:
            segs.append(("class:sep fg:ansibrightblack", " │ "))
        segs.append(("class:stat-label fg:ansibrightblack", f"{abbr} {tier_short} "))
        segs.append((tier_style, bar))
    return segs


def stats_bar_text(stats: dict[str, dict[str, Any]] | None = None) -> str:
    """Vanlig farglos enradig strang (for tester/icke-PT-kontexter)."""
    return "".join(text for _, text in stats_bar_segments(stats))


def user_prefix_markup() -> str:
    """Rich markup for user-prefix 'du>'."""
    return f"[{theme.USER_PREFIX_RICH}]{theme.USER_PREFIX}[/{theme.USER_PREFIX_RICH}]"


def separator(console: Console) -> None:
    """Tunn dim linje mellan logiska block."""
    console.print(f"[dim]{theme.SEPARATOR_CHAR * 40}[/dim]")


def _mascot() -> str:
    return (
        "  ▐▛██▜▌\n"
        "  ▐▌  ▐▌\n"
        "  ▐▌▄▄▐▌\n"
        "   ▀  ▀"
    )


def mascot() -> str:
    """Publik access till pixel-hund-art (for /mascot)."""
    return _mascot()


def render_startup(console: Console, rt, *, force_mascot: bool = False) -> None:
    """2-3 rader vid uppstart. Mascot visas forsta gangen (eller /mascot)."""
    home = hund_home()
    flag = home / _MASCOT_FLAG
    show_mascot = force_mascot or not flag.exists()
    if show_mascot:
        console.print(_mascot())
        try:
            home.mkdir(parents=True, exist_ok=True)
            flag.write_text("1", encoding="utf-8")
        except OSError:
            pass

    console.print("[bold cyan]hund[/bold cyan] är vaken. maskinen känns stabil.")
    domain = getattr(rt, "domain_hint", "?")
    sid = getattr(rt, "session_id", "??????")
    console.print(f"[dim]session #{sid[:6]} · {domain}[/dim]")
    console.print()


def refresh_stats(state):
    """Cachea stats for bottom_toolbar. Returnera stats-dict (for tier-diff)."""
    try:
        stats = compute_all()
    except Exception:
        state.stats_text = None
        return None
    state.stats_text = stats_bar_segments(stats)
    return stats

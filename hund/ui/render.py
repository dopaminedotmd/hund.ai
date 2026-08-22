"""Rendering helpers: stats bar (bottom_toolbar), startup banner, separator, character card.

Uses standard single-line box drawing via theme.boxify().
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

from ..paths import hund_home
from ..stats import compute_all
from ..stats.tiers import render_bar, render_stat
from . import theme

_MASCOT_FLAG = "mascot_seen"


def _bar(progress: int, width: int = theme.BAR_WIDTH) -> str:
    return render_bar(progress, width=width)


def stats_bar_segments(stats: dict[str, dict[str, Any]] | None = None):
    """Return list[(pt_style, text)] for prompt_toolkit bottom_toolbar.

    Tier-colored single row:  CLR Mast ████████░ │ PRC Expe ██████░░░ │ ...
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
    """Plain uncolored single-line text (for tests/non-PT contexts)."""
    return "".join(text for _, text in stats_bar_segments(stats))


def user_prefix_markup() -> str:
    """Rich markup for user prefix 'du>'."""
    return f"[{theme.USER_PREFIX_RICH}]{theme.USER_PREFIX}[/{theme.USER_PREFIX_RICH}]"


import difflib
from rich.syntax import Syntax

def separator(console: Console) -> None:
    """Thin dim line separating logical blocks."""
    console.print(f"[dim]{theme.SEPARATOR_CHAR * 60}[/dim]")


def _mascot() -> str:
    return (
        "  ▐▛██▜▌\n"
        "  ▐▌  ▐▌\n"
        "  ▐▌▄▄▐▌\n"
        "   ▀  ▀"
    )


def mascot() -> str:
    """Public access to pixel mascot art."""
    return _mascot()



def render_startup(console: Console, rt, *, force_mascot: bool = False) -> None:
    """Fastfetch-style two-column startup banner with ASCII art and system telemetry."""
    from ..doctor import inspect_environment
    profile = getattr(rt, "profile", None)
    if profile is None:
        try:
            profile = inspect_environment(getattr(rt, "workspace", None))
        except Exception:
            profile = None

    os_caption = getattr(profile, "os_caption", "")
    os_fallback = f"{getattr(profile, 'os', 'System')} {getattr(profile, 'os_version', '')}".strip()
    os_str = os_caption or os_fallback or "Windows"
    host_str = getattr(profile, "hostname", "") or "host"
    cpu_cores = getattr(profile, "cpu_count", None)
    cpu_str = getattr(profile, "processor", "") or "CPU"
    if cpu_cores:
        cpu_str += f" ({cpu_cores} cores)"
    ram_gb = getattr(profile, "total_ram_gb", 0.0)
    ram_str = f"{ram_gb:.1f} GB Total" if ram_gb else "RAM ready"
    gpu_str = getattr(profile, "gpu_model", "")
    if gpu_str and getattr(profile, "gpu_vram_mb", 0):
        gpu_str += f" ({getattr(profile, 'gpu_vram_mb', 0) / 1024:.1f} GB VRAM)"

    tools = []
    if getattr(profile, "has_git", False): tools.append("git")
    if getattr(profile, "has_python", False): tools.append("python")
    if getattr(profile, "has_uv", False): tools.append("uv")
    if getattr(profile, "has_node", False): tools.append("node")
    tools_str = ", ".join(tools) if tools else "tools ready"

    cfg = getattr(rt, "cfg", None)
    provider_name = getattr(getattr(cfg, "provider", None), "name", "DeepSeek")
    model_name = getattr(getattr(cfg, "provider", None), "model", "deepseek-v4-pro")
    slots_str = "6/6 active skills equipped · sqlite ok"

    mascot_lines = [
        "  ┬ ┬ ┬ ┬ ┌┐┌ ┌┬┐",
        "  ├─┤ │ │ │││  ││",
        "  ┴ ┴ └─┘ ┘└┘ ─┴┘",
        "  [Conscious Agent]",
        "",
        "",
        "",
        "",
    ]
    info_lines = [
        f"OS       : {os_str[:38]}",
        f"HOST     : {host_str[:38]}",
        f"CPU      : {cpu_str[:38]}",
        f"RAM      : {ram_str[:38]}",
        f"GPU      : {gpu_str[:38]}" if gpu_str else f"SHELL    : {getattr(profile, 'shell', 'powershell')}",
        f"TOOLS    : {tools_str[:38]}",
        f"MODEL    : {provider_name} ({model_name})",
        f"SLOTS    : {slots_str[:38]}",
    ]

    combined = []
    for i in range(max(len(mascot_lines), len(info_lines))):
        left = mascot_lines[i] if i < len(mascot_lines) else "                   "
        right = info_lines[i] if i < len(info_lines) else ""
        combined.append(f"{left:<21}  [dim]{right}[/dim]")

    card = theme.boxify("HUND AI [v0.1.0]", combined, width=74, border_style="dim", title_style="bold cyan")
    console.print(card)

    console.print("[bold cyan]hund[/bold cyan] is awake. machine feels stable.")
    domain = getattr(rt, "domain_hint", "?")
    sid = getattr(rt, "session_id", "??????")
    console.print(f"[dim]session #{sid[:6]} · {domain}[/dim]\n")


def render_diff(console: Console, old: str, new: str, filename: str = "") -> None:
    """Render unified diff with green additions and red deletions inside clean box."""
    diff = list(difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"a/{filename}" if filename else "a",
        tofile=f"b/{filename}" if filename else "b",
        lineterm="",
    ))
    if not diff:
        console.print(f"[dim](no diff changes for {filename})[/dim]")
        return

    formatted_lines: list[str] = []
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            formatted_lines.append(f"[bold dim]{line}[/bold dim]")
        elif line.startswith("+"):
            formatted_lines.append(f"[green]{line}[/green]")
        elif line.startswith("-"):
            formatted_lines.append(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            formatted_lines.append(f"[cyan]{line}[/cyan]")
        else:
            formatted_lines.append(f"[dim]{line}[/dim]")

    title = f"DIFF: {filename}" if filename else "DIFF"
    card = theme.boxify(title, formatted_lines, width=74, border_style="dim", title_style="bold cyan")
    console.print(card, highlight=False)



def render_code_block(console: Console, code: str, language: str = "python", filename: str = "") -> None:
    """Render syntax highlighted code with line numbers inside a boxed card."""
    syntax = Syntax(code, lexer=language, theme="monokai", line_numbers=True)
    title = f"[{language.upper()}] {filename}".strip()
    console.print(f"[dim]┌──[/dim] [bold cyan]{title}[/bold cyan] [dim]{theme.SEPARATOR_CHAR * max(20, 60 - len(title))}┐[/dim]")
    console.print(syntax)
    console.print(f"[dim]└{theme.SEPARATOR_CHAR * 68}┘[/dim]")



def refresh_stats(state):
    """Cache stats for bottom_toolbar. Return stats dict."""
    try:
        stats = compute_all()
    except Exception:
        state.stats_text = None
        return None
    state.stats_text = stats_bar_segments(stats)
    return stats


def render_character_card(
    console: Console,
    rt: Any,
    stats: dict[str, dict[str, Any]] | None = None,
    *,
    compact: bool = False,
) -> None:
    """Render a unified RPG-style character sheet for Hund inside standard box borders."""
    if stats is None:
        try:
            stats = compute_all()
        except Exception:
            stats = {}

    if compact:
        for key in theme.STAT_ORDER:
            s = (stats or {}).get(key)
            if s:
                console.print(render_stat(s))
        return

    # 1. Habitat & System info
    profile = getattr(rt, "profile", None)
    hostname = getattr(profile, "hostname", "") or "host"
    os_name = getattr(profile, "os_caption", "") or getattr(profile, "os", "") or "system"
    ram_gb = getattr(profile, "total_ram_gb", None)
    ram_str = f"{ram_gb:.0f}GB RAM" if ram_gb else "RAM unknown"
    shell_str = getattr(profile, "shell", "") or "shell"

    # Compute overall level
    level = sum(s.get("tier_idx", 1) for s in (stats or {}).values() if isinstance(s, dict)) or 5

    body_lines: list[str] = [
        f" [bold yellow]LEVEL:[/bold yellow] {level:<5} [bold yellow]CLASS:[/bold yellow] Machine-Bound Operator",
        f" [dim]HABITAT:[/dim] {hostname} · {os_name} · {ram_str} · {shell_str}",
        "",
        " [bold cyan]── BASE ATTRIBUTES ───────────────────────────────────────────────[/bold cyan]",
    ]

    stat_labels = {
        "clarity": "Clarity (CLR)     ",
        "precision": "Precision (PRC)   ",
        "efficiency": "Efficiency (EFF)  ",
        "endurance": "Endurance (END)   ",
        "mastery": "Mastery (MAS)     ",
    }
    for key in theme.STAT_ORDER:
        s = (stats or {}).get(key, {})
        label = stat_labels.get(key, f"{key:<18}")
        tier = s.get("tier") or theme.EMDASH
        progress = int(s.get("progress", 0) or 0)
        bar = _bar(progress, width=12)
        tier_color = theme.tier_rich(tier)
        val = s.get("value")
        val_str = f"({val})" if val is not None else ""
        tier_display = f"[{tier_color}]{tier:<10}[/{tier_color}]"
        body_lines.append(f" {label}  {bar}  {tier_display} {progress:>3}% {val_str:<10}")

    # 3. Domains
    try:
        from ..domains import confidence
        domain_items = confidence.list_confidence()
    except Exception:
        domain_items = []

    if domain_items:
        body_lines.append("")
        body_lines.append(" [bold cyan]── SPECIALIZATIONS (DOMAINS) ─────────────────────────────────────[/bold cyan]")
        for it in domain_items[:3]:
            d_name = it.get("domain", "?")
            d_score = int(it.get("score", 0) or 0)
            d_tier = it.get("confidence_tier", "?")
            d_bar = _bar(d_score, width=12)
            d_tier_color = theme.tier_rich(d_tier)
            body_lines.append(f" * {d_name:<16}  {d_bar}  [{d_tier_color}]{d_tier:<10}[/{d_tier_color}] {d_score:>3}%")

    # 4. Weekly Velocity
    try:
        from ..stats import compute_velocity
        vel = compute_velocity()
    except Exception:
        vel = None

    if vel:
        body_lines.append("")
        body_lines.append(" [bold cyan]── WEEKLY TREND (VELOCITY) ───────────────────────────────────────[/bold cyan]")
        parts = []
        for key in theme.STAT_ORDER:
            v = vel.get(key)
            if v:
                abbr = theme.STAT_ABBR.get(key, key[:3].upper())
                mark = "+" if v.get("improving") else "-"
                delta = v.get("delta_display", "0")
                parts.append(f"{abbr}: {mark}{delta}")
        if parts:
            line_str = " · ".join(parts[:4])
            body_lines.append(f" [dim]{line_str}[/dim]")

    card = theme.boxify("CHARACTER SHEET: HUND", body_lines, width=72, border_style="cyan", title_style="bold white")
    console.print(card)

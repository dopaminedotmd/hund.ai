"""Rendering helpers: stats bar (bottom_toolbar), startup banner, separator, character card.

Uses standard single-line box drawing via theme.boxify().
"""
from __future__ import annotations

import re
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
    """Thin dim line spanning the full terminal width."""
    width = getattr(console, "width", 80) or 80
    console.print(f"[dim]{theme.SEPARATOR_CHAR * width}[/dim]")


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



def build_startup_banner(rt, width: int = 80) -> str:
    """Build the fullscreen startup banner per TUI_FACIT.md §4 with clean telemetry and responsive layout."""
    import re
    from ..doctor import profile_environment
    from ..stats import compute_all
    from ..skills.vault import SkillVault

    W = max(width, 40)
    
    profile = getattr(rt, "profile", None)
    if profile is None:
        try:
            profile = profile_environment(getattr(rt, "workspace", None))
        except Exception:
            profile = None

    # Clean uncluttered OS string
    raw_os = getattr(profile, "os_caption", "") or f"{getattr(profile, 'os', 'System')} {getattr(profile, 'os_version', '')}".strip()
    os_str = re.sub(r"\s*\(2\d+H\d+\)", "", raw_os)
    os_str = re.sub(r"\s*\[x86_\d+\]", "", os_str)
    os_str = re.sub(r"\s*Build\s*\d+", "", os_str).strip() or "Windows"

    host_str = getattr(profile, "hostname", "") or "host"

    # Clean uncluttered CPU string
    cpu_cores = getattr(profile, "cpu_count", None)
    raw_cpu = getattr(profile, "processor", "") or ""
    cpu_clean = re.sub(r"Intel(?:\([R|TM]+\))?\s*", "", raw_cpu, flags=re.I)
    cpu_clean = re.sub(r"Core(?:\([R|TM]+\))?\s*", "", cpu_clean, flags=re.I)
    cpu_clean = re.sub(r"AMD\s*", "", cpu_clean, flags=re.I)
    cpu_clean = re.sub(r"\s*@\s*[\d.]+\s*[GM]Hz", "", cpu_clean, flags=re.I)
    cpu_clean = re.sub(r"\s*\(\d+C\s*/\s*\d+T\)", "", cpu_clean).strip()
    if cpu_cores and cpu_clean:
        cpu_str = f"{cpu_clean} ({cpu_cores} cores)"
    elif cpu_cores:
        cpu_str = f"CPU ({cpu_cores} cores)"
    else:
        cpu_str = cpu_clean or "CPU ready"

    ram_gb = getattr(profile, "total_ram_gb", 0.0)
    ram_str = f"{ram_gb:.1f} GB" if ram_gb else "RAM ready"

    # Clean uncluttered GPU string
    raw_gpu = getattr(profile, "gpu_model", "")
    gpu_clean = re.sub(r"\[Integrated\].*$", "", raw_gpu).strip()
    gpu_clean = re.sub(r"//.*$", "", gpu_clean).strip()
    gpu_clean = re.sub(r"Intel(?:\([R|TM]+\))?\s*", "Intel ", gpu_clean, flags=re.I)
    gpu_clean = re.sub(r"Graphics\s*", "", gpu_clean, flags=re.I).strip()
    gpu_clean = re.sub(r"NVIDIA\s+GeForce\s*", "", gpu_clean, flags=re.I).strip()
    if gpu_clean:
        gpu_str = gpu_clean
    else:
        gpu_str = getattr(profile, "shell", "PowerShell")

    cfg = getattr(rt, "cfg", None)
    provider_name = getattr(getattr(cfg, "provider", None), "name", "DeepSeek")
    model_name = getattr(getattr(cfg, "provider", None), "model", "deepseek-v4-pro")
    if "(" in model_name and ")" in model_name:
        model_display = model_name
    elif provider_name and model_name.startswith(provider_name.lower()):
        model_display = model_name
    else:
        model_display = f"{provider_name} ({model_name})"

    # Always reload skills and stats dynamically
    try:
        vault = SkillVault()
        active_skills = vault.get_active_skills()
        core_skills = vault.get_core_skills()
        max_slots = vault.max_active
    except Exception:
        active_skills = []
        core_skills = []
        max_slots = 6

    try:
        stats = compute_all()
    except Exception:
        stats = {}

    top = "╔" + "═" * (W - 2) + "╗"
    bottom = "╚" + "═" * (W - 2) + "╝"
    empty = "║" + " " * (W - 2) + "║"

    def row(content: str) -> str:
        c = content[: W - 6]
        return "║  " + c.ljust(W - 6) + "  ║"

    LOGO_LINES = [
        "▄▄                   ▄▄    ",
        "██                   ██    ",
        "████▄ ██ ██ ████▄ ▄████    ",
        "██ ██ ██ ██ ██ ██ ██ ██    ",
        "██ ██ ▀██▀█ ██ ██ ▀████ ██ ",
    ]

    # Attribute data
    attr_meta = [
        ("clarity", "CLR", "Clarity"),
        ("precision", "PRC", "Precision"),
        ("efficiency", "EFF", "Efficiency"),
        ("endurance", "END", "Endurance"),
        ("mastery", "MAS", "Mastery"),
    ]
    attr_data: list[tuple[str, str, int]] = []
    for key, abbr, name in attr_meta:
        s = stats.get(key, {})
        pct = int(s.get("progress", 0) or 0)
        attr_data.append((abbr, name, pct))

    # Skill and Domain XP data
    all_display_skills = list(active_skills) + [s for s in core_skills if s not in active_skills]
    skill_data: list[tuple[str, str, int]] = []
    try:
        from hund.domains.xp import get_xp
        for s in all_display_skills[:6]:
            s_name = getattr(s, "name", str(s))[:17]
            s_domain = getattr(s, "domain", "") or s_name
            xp_info = get_xp(s_domain)
            if xp_info["xp"] == 0 and s_name != s_domain:
                xp_info = get_xp(s_name)
            skill_data.append((s_name, xp_info["tier"], xp_info["progress_pct"]))
    except Exception:
        for s in all_display_skills[:6]:
            s_name = getattr(s, "name", str(s))[:17]
            skill_data.append((s_name, "Novice", 0))

    total_display_skills = len(all_display_skills[:6])
    skills_header = f"── SKILLS ({total_display_skills}/{max_slots}) ──"

    commands_text = "commands: /skills · /stats · /theme · /model · /clear · /exit"

    lines = [
        top,
        empty,
    ]
    for l_line in LOGO_LINES:
        lines.append(row(l_line))
    lines.extend([
        empty,
        row(f"OS      {os_str}"),
        row(f"HOST    {host_str}"),
        row(f"CPU     {cpu_str}"),
        row(f"RAM     {ram_str}"),
        row(f"GPU     {gpu_str}"),
        row(f"MODEL   {model_display}"),
        empty,
    ])

    # Two column if W >= 72, else single column stacked responsive layout
    if W >= 72:
        col_left = (W - 6 - 4) // 2
        col_right = (W - 6 - 4) - col_left

        def split_row(l: str, r: str) -> str:
            return "║  " + l[:col_left].ljust(col_left) + " │  " + r[:col_right].ljust(col_right) + "  ║"

        lines.append(split_row("── BASE ATTRIBUTES ──", skills_header))
        bar_w = 8 if W < 80 else 10
        max_rows = max(len(attr_data), len(skill_data))
        for i in range(max_rows):
            l_str = ""
            if i < len(attr_data):
                abbr, name, pct = attr_data[i]
                bar = _bar(pct, width=bar_w)
                l_str = f"{abbr} {name:<10} {bar} {pct}%"
            r_str = ""
            if i < len(skill_data):
                sname, stier, pct = skill_data[i]
                bar = _bar(pct, width=bar_w)
                r_str = f"{sname:<17} {bar} {pct}%"
            lines.append(split_row(l_str, r_str))
    else:
        bar_w = max(4, min(8, (W - 28) // 2))
        lines.append(row("── BASE ATTRIBUTES ──"))
        for abbr, name, pct in attr_data:
            bar = _bar(pct, width=bar_w)
            lines.append(row(f"{abbr} {name:<9} {bar} {pct}%"))
        lines.append(empty)
        lines.append(row(skills_header))
        for sname, stier, pct in skill_data[:4]:
            bar = _bar(pct, width=bar_w)
            lines.append(row(f"{sname:<16} {bar} {pct}%"))

    lines.extend([
        empty,
        row(commands_text),
        bottom,
    ])

    return "\n".join(lines)


def render_startup(console: Console, rt, *, force_mascot: bool = False) -> None:
    """Print the startup banner to console."""
    w = console.width if getattr(console, "width", None) else 80
    banner = build_startup_banner(rt, width=w)
    console.print(banner)


def format_diff_block(diff_text: str, filename: str = "", width: int = 70) -> str:
    """Format a diff block for streaming response box per TUI_FACIT.md §9.

    - Header: ── {filename} · changed ────────────────
    - Line numbers shown if >= 3 lines, hidden if < 3 lines.
    - Footer: ────────────────────────────────────────
    """
    w = max(width, 24)
    raw_lines = diff_text.strip("\n").splitlines()

    # Smart filename detection from first line comment if not provided
    if not filename and raw_lines:
        first = raw_lines[0].strip()
        m_fn = re.match(r"^(?:#|//|/\*|--)\s*([\w\-./\\]+\.[a-zA-Z0-9]+)(?:\s*\*/)?$", first)
        if m_fn:
            filename = m_fn.group(1).split("/")[-1].split("\\")[-1]
            raw_lines = raw_lines[1:]

    # Filter out raw diff header noise if present
    content_lines: list[tuple[str, str]] = []
    for raw in raw_lines:
        if raw.startswith("---") or raw.startswith("+++") or raw.startswith("@@"):
            continue
        if raw.startswith("+"):
            content_lines.append(("+", raw[1:]))
        elif raw.startswith("-"):
            content_lines.append(("-", raw[1:]))
        else:
            content_lines.append((" ", raw[1:] if raw.startswith(" ") else raw))

    if not content_lines:
        content_lines = [(" ", l) for l in raw_lines]

    show_line_numbers = len(content_lines) >= 3
    body_lines: list[str] = []

    old_num = 1
    new_num = 1
    for kind, text in content_lines:
        if show_line_numbers:
            if kind == "-":
                body_lines.append(f"- {old_num:<3} {text.rstrip()}")
                old_num += 1
            elif kind == "+":
                body_lines.append(f"+ {new_num:<3} {text.rstrip()}")
                new_num += 1
            else:
                body_lines.append(f"  {new_num:<3} {text.rstrip()}")
                old_num += 1
                new_num += 1
        else:
            if kind == "-":
                body_lines.append(f"- {text.rstrip()}")
            elif kind == "+":
                body_lines.append(f"+ {text.rstrip()}")
            else:
                body_lines.append(f"  {text.rstrip()}")

    if filename:
        title_part = f"── {filename} · changed "
        dashes = max(w - len(title_part), 2)
        header = f"{title_part}{'─' * dashes}"
    else:
        title_part = "── diff "
        dashes = max(w - len(title_part), 2)
        header = f"{title_part}{'─' * dashes}"

    footer = "─" * w
    return "\n".join([header] + body_lines + [footer])


def format_code_block(code: str, language: str = "", filename: str = "", width: int = 70) -> str:
    """Format a code block for streaming response box per TUI_FACIT.md §9.

    - Header: ── {filename/language} ────────────────────
    - Footer: ────────────────────────────────────────
    """
    w = max(width, 24)
    raw_lines = code.strip("\n").splitlines()

    # Smart filename detection from first line comment if not provided
    if not filename and raw_lines:
        first = raw_lines[0].strip()
        m_fn = re.match(r"^(?:#|//|/\*|--)\s*([\w\-./\\]+\.[a-zA-Z0-9]+)(?:\s*\*/)?$", first)
        if m_fn:
            filename = m_fn.group(1).split("/")[-1].split("\\")[-1]
            raw_lines = raw_lines[1:]

    label = filename or language or "code"
    title_part = f"── {label} "
    dashes = max(w - len(title_part), 2)
    header = f"{title_part}{'─' * dashes}"

    body_lines = [f"  {line}" for line in raw_lines]
    footer = "─" * w
    return "\n".join([header] + body_lines + [footer])


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


# -- Response Box Side Rails & Deterministic Word-Wrap ----------------------

import textwrap


def wrap_content(text: str, content_width: int) -> list[str]:
    """Deterministically word-wrap text to content_width using stdlib textwrap.

    Consecutive empty lines are collapsed to at most one empty line.
    Long unbreakable words overflow that single line only (break_long_words=False).
    """
    if not text:
        return []
    cw = max(content_width, 1)
    wrapped: list[str] = []
    prev_empty = False
    for raw_line in text.split("\n"):
        if not raw_line.strip():
            if not prev_empty and wrapped:
                wrapped.append("")
                prev_empty = True
        else:
            prev_empty = False
            lines = textwrap.wrap(
                raw_line,
                width=cw,
                break_long_words=False,
                break_on_hyphens=False,
            )
            if not lines:
                wrapped.append("")
            else:
                wrapped.extend(lines)
    return wrapped


def box_top(width: int = 80) -> str:
    """Render top border for assistant response box."""
    w = max(width, 12)
    return f"┌─ hund {'─' * max(w - 9, 2)}┐"


def box_bottom(width: int = 80, meta: str | None = None) -> str:
    """Render bottom border for assistant response box with optional right-aligned meta."""
    w = max(width, 12)
    if meta is None or not str(meta).strip():
        return f"└{'─' * max(w - 2, 2)}┘"
    meta_str = str(meta).strip()
    dashes = max(w - len(meta_str) - 7, 2)
    return f"└{'─' * dashes} {meta_str} ───┘"


def render_response_box(
    text: str,
    terminal_width: int = 80,
    meta: str | None = None,
) -> str:
    """Render response text inside a full-width geometric box with generous padding.

    - Always spans the full terminal width (fullscreen).
    - 1 top and 1 bottom padding row inside the box.
    - 2-space horizontal padding on both sides (│  content  │).
    - Hard word-wrapped at content_width = terminal_width - 6.
    - Meta is rendered right-aligned in the bottom border (e.g. '└── 2.3s ───┘').
    """
    box_w = max(terminal_width, 24)
    cw = max(box_w - 6, 1)

    clean_text = text.strip("\n")
    wrapped = wrap_content(clean_text, cw)

    if not wrapped:
        return f"{box_top(box_w)}\n{box_bottom(box_w, meta)}"

    lines = [box_top(box_w)]
    # Top padding row (1 row per TUI_FACIT.md §2 and §15)
    lines.append(f"│{' ' * (box_w - 2)}│")

    # Content rows
    for line in wrapped:
        if len(line) <= cw:
            lines.append(f"│  {line:<{cw}}  │")
        else:
            lines.append(f"│  {line}  │")

    # Bottom padding row (1 row)
    lines.append(f"│{' ' * (box_w - 2)}│")
    lines.append(box_bottom(box_w, meta))
    return "\n".join(lines)

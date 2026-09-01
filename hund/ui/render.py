"""Rendering helpers: stats bar (bottom_toolbar), startup banner, separator, character card.

Uses standard single-line box drawing via theme.boxify().
"""
from __future__ import annotations

import re
from typing import Any

from rich.console import Console

from ..paths import hund_home
from ..skills.projection import project_active_skill_xp
from ..stats import compute_all
from ..stats.tiers import render_bar, render_stat
from . import theme
from .unicode_cells import cell_width, sanitize_display_line, slice_cells, wrap_cells

_MASCOT_FLAG = "mascot_seen"


def _bar(progress: int, width: int = theme.BAR_WIDTH) -> str:
    return render_bar(progress, width=width)


def _fit_cell_label(text: str, width: int) -> str:
    """Truncate and pad a display label to an exact terminal-cell width."""
    clean = sanitize_display_line(text)
    if cell_width(clean) > width:
        clipped, _ = slice_cells(clean, max(width - 1, 0))
        clean = f"{clipped}…" if width else ""
    return clean + " " * max(width - cell_width(clean), 0)


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
    from .mascot import MascotMachine

    return MascotMachine().frame()[1]


def mascot() -> str:
    """Public access to pixel mascot art."""
    return _mascot()



def build_startup_banner(rt, width: int = 80, *, db_path=None) -> str:
    """Build the fullscreen startup banner per TUI_FACIT.md §4 with clean telemetry and responsive layout."""
    import re
    from ..doctor import profile_environment
    from ..stats import compute_all
    from ..skills.vault import SkillVault

    W = max(int(width), 24)

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
    ascii_only = getattr(cfg, "ascii_ui", False) is True
    provider_obj = getattr(cfg, "provider", None)
    provider_id = (
        getattr(provider_obj, "provider_id", "")
        or getattr(provider_obj, "credential_id", "")
        or getattr(provider_obj, "name", "")
    )
    provider_names = {
        "openrouter": "OpenRouter",
        "deepseek": "DeepSeek",
        "local": "Local",
        "openai": "OpenAI",
    }
    provider_name = provider_names.get(provider_id.lower(), provider_id if provider_id else "DeepSeek")
    model_name = getattr(provider_obj, "model", "deepseek-v4-flash")
    if "(" in model_name and ")" in model_name:
        model_display = model_name
    elif provider_name and model_name.lower().startswith(provider_name.lower()):
        model_display = model_name
    else:
        model_display = f"{provider_name} ({model_name})"

    # Always reload skills and stats dynamically
    try:
        vault = SkillVault()
        active_skills = vault.get_active_skills(
            workspace=getattr(rt, "workspace", None)
        )
        core_skills = vault.get_core_skills()
    except Exception:
        active_skills = []
        core_skills = []

    try:
        stats = compute_all()
    except Exception:
        stats = {}

    top_left, top_right, bottom_left, bottom_right, horizontal, vertical = (
        ("+", "+", "+", "+", "-", "|") if ascii_only else ("╔", "╗", "╚", "╝", "═", "║")
    )
    column_divider = "|" if ascii_only else "│"
    bottom = bottom_left + horizontal * (W - 2) + bottom_right
    empty = vertical + " " * (W - 2) + vertical

    def display_text(content: str) -> str:
        clean = sanitize_display_line(content)
        return clean.encode("ascii", "replace").decode("ascii") if ascii_only else clean

    def row(content: str) -> str:
        c, cells = slice_cells(display_text(content), W - 6)
        return vertical + "  " + c + " " * (W - 6 - cells) + "  " + vertical

    def fixed_cells(content: str, cells: int) -> str:
        clipped, used = slice_cells(display_text(content), cells)
        return clipped + " " * (cells - used)

    def progress_bar(progress: int, cells: int) -> str:
        if not ascii_only:
            return _bar(progress, width=cells)
        filled = min(cells, max(0, round((progress / 100) * cells)))
        return "#" * filled + "-" * (cells - filled)

    LOGO_LINES = (
        ["hund"]
        if ascii_only
        else [
            "▄▄                   ▄▄",
            "██                   ██",
            "████▄ ██ ██ ████▄ ▄████",
            "██ ██ ██ ██ ██ ██ ██ ██",
            "██ ██ ▀██▀█ ██ ██ ▀████ ██",
        ]
    )

    if W >= 34 and not ascii_only:
        logo_0 = LOGO_LINES[0]
        top = "╔═ " + logo_0 + " " + "═" * (W - 5 - len(logo_0)) + "╗"
        logo_rest = LOGO_LINES[1:]
    else:
        top = top_left + horizontal * (W - 2) + top_right
        logo_rest = LOGO_LINES

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

    # Only audited Skill XP is eligible for atomic-skill proficiency display.
    try:
        skill_data = project_active_skill_xp(
            active_skills,
            db_path=db_path,
            limit=5,
        )
    except Exception:
        skill_data = ()

    rule = "--" if ascii_only else "──"
    skills_header = f"{rule} ACTIVE SKILLS {rule}"
    specialisations_header = f"{rule} SPECIALISATIONS (0/6) {rule}"

    command_separator = " * " if ascii_only else " · "
    commands_text = command_separator.join(("commands: /skills", "/stats", "/theme", "/model", "/clear", "/exit"))

    lines = [
        top,
    ]
    for l_line in logo_rest:
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

    # Two columns need enough room for labels, bars, and percentages.
    if W >= 72:
        col_left = (W - 6 - 4) // 2
        col_right = (W - 6 - 4) - col_left

        def split_row(l: str, r: str) -> str:
            return vertical + "  " + fixed_cells(l, col_left) + f" {column_divider}  " + fixed_cells(r, col_right) + "  " + vertical

        header_fill = "-" if ascii_only else "─"
        left_hdr = f"{rule} BASE STATS " + header_fill * max(2, col_left - len(f"{rule} BASE STATS "))
        right_hdr = f"{rule} ACTIVE SKILLS " + header_fill * max(2, col_right - len(f"{rule} ACTIVE SKILLS "))
        lines.append(split_row(left_hdr, right_hdr))
        bar_w = 10
        display_skills = skill_data[:5]
        max_rows = max(len(attr_data), len(display_skills) if display_skills else 2)
        for i in range(max_rows):
            l_str = ""
            if i < len(attr_data):
                abbr, name, pct = attr_data[i]
                bar = progress_bar(pct, bar_w)
                l_str = f"{abbr} {name:<10} {bar} {pct}%"
            r_str = ""
            if display_skills and i < len(display_skills):
                skill_row = display_skills[i]
                bar = progress_bar(skill_row.progress_percent, bar_w)
                label = _fit_cell_label(skill_row.display_name, 12)
                r_str = f"{label} L{skill_row.level} {bar} {skill_row.progress_percent}%"
            elif not display_skills:
                if i == 0:
                    r_str = "(no active skills)"
                elif i == 1:
                    r_str = "(use /skills to equip)"
            lines.append(split_row(l_str, r_str))
        lines.extend([empty, row(specialisations_header), row("No active specialisations")])
    else:
        # Preserve the wide view's ten-cell XP geometry whenever it fits.
        bar_w = max(4, min(10, W - 27))
        lines.append(row(f"{rule} BASE STATS {rule}"))
        for abbr, name, pct in attr_data:
            bar = progress_bar(pct, bar_w)
            lines.append(row(f"{abbr} {name:<10} {bar} {pct}%"))
        lines.append(empty)
        lines.append(row(skills_header))
        if skill_data:
            for skill_row in skill_data[:5]:
                bar = progress_bar(skill_row.progress_percent, bar_w)
                label = _fit_cell_label(skill_row.display_name, 10)
                lines.append(row(f"{label} L{skill_row.level} {bar} {skill_row.progress_percent}%"))
        else:
            lines.append(row("(no active skills)"))
            lines.append(row("(use /skills to equip)"))
        lines.extend([empty, row(specialisations_header), row("No active specialisations")])

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


def normalize_language_alias(lang: str) -> str:
    """Normalize language name or alias to canonical v1 identifier."""
    raw = (lang or "").strip().lower()
    if raw in ("python", "py"):
        return "python"
    if raw in ("powershell", "pwsh", "ps1"):
        return "powershell"
    if raw in ("json",):
        return "json"
    if raw in ("bash", "sh", "shell"):
        return "bash"
    if raw in ("diff", "patch"):
        return "diff"
    return raw


def _sanitize_block_label(value: str, max_cells: int) -> str:
    """Return provider-controlled block metadata as safe, single-line display text."""
    clean = sanitize_display_line(str(value)).replace("\r", " ").replace("\n", " ").strip()
    clean = " ".join(clean.split())
    return slice_cells(clean, max(max_cells, 0))[0]


def format_diff_block(
    diff_text: str,
    filename: str = "",
    width: int = 70,
    is_open: bool = False,
    is_limited: bool = False,
) -> str:
    """Format a frameless diff artifact for both streaming presentation paths."""
    w = max(width, 24)
    raw_lines = diff_text.strip("\n").splitlines() if diff_text else []

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

    body_lines: list[str] = []

    old_num = 1
    new_num = 1
    for kind, text in content_lines:
        if kind == "-":
            prefix = f"- {old_num:>4} "
            old_num += 1
        elif kind == "+":
            prefix = f"+ {new_num:>4} "
            new_num += 1
        else:
            prefix = f"  {new_num:>4} "
            old_num += 1
            new_num += 1
        content, _ = slice_cells(text.rstrip(), max(w - cell_width(prefix), 0))
        row = prefix + content
        body_lines.append(row + " " * max(w - cell_width(row), 0))

    adds = sum(kind == "+" for kind, _ in content_lines)
    dels = sum(kind == "-" for kind, _ in content_lines)
    counts = f"  (+{adds} -{dels})"
    filename = _sanitize_block_label(filename or "diff", max(w - cell_width("└ ") - cell_width(counts), 1))
    lines = [f"└ {filename}{counts}", *body_lines]
    if is_limited:
        lines.append("… Diff preview limited.")
    return "\n".join(lines)


def repad_diff_block(lines: list[str], width: int) -> list[str]:
    """Re-pad registered diff rows after the terminal width changes."""
    w = max(width, 24)
    return [
        line if index == 0 or line == "… Diff preview limited."
        else slice_cells(line.rstrip(), w)[0] + " " * max(w - cell_width(slice_cells(line.rstrip(), w)[0]), 0)
        for index, line in enumerate(lines)
    ]


def format_code_block(code: str, language: str = "", filename: str = "", width: int = 70, is_open: bool = False) -> str:
    """Format a code block for streaming response box per TUI_FACIT.md §9.

    - Header: ── {filename/language} ────────────────────
    - Footer: ──────────────────────────────────────── (omitted if is_open)
    """
    w = max(width, 24)
    raw_lines = code.strip("\n").splitlines() if code else []

    # Smart filename detection from first line comment if not provided
    if not filename and raw_lines:
        first = raw_lines[0].strip()
        m_fn = re.match(r"^(?:#|//|/\*|--)\s*([\w\-./\\]+\.[a-zA-Z0-9]+)(?:\s*\*/)?$", first)
        if m_fn:
            filename = m_fn.group(1).split("/")[-1].split("\\")[-1]
            raw_lines = raw_lines[1:]

    safe_language = _sanitize_block_label(language, max(w - cell_width("──  ") - 2, 1))
    safe_filename = _sanitize_block_label(filename, max(w - cell_width("──  ") - 2, 1))
    lang_canon = normalize_language_alias(safe_language)
    label = safe_filename or lang_canon or "code"
    label = _sanitize_block_label(label, max(w - cell_width("──  ") - 2, 1)) or "code"
    title_part = f"── {label} "
    title_w = cell_width(title_part)
    dashes = max(w - title_w, 2)
    header = f"{title_part}{'─' * dashes}"

    body_lines = [f"  {line}" for line in raw_lines]
    if is_open:
        return "\n".join([header] + body_lines)
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


def wrap_content(text: str, content_width: int) -> list[str]:
    """Deterministically word-wrap text to content_width using unicode_cells.

    Empty lines are semantic content and are therefore preserved exactly.
    Long unbreakable words are hard-wrapped so the right box rail stays intact.
    """
    return wrap_cells(text, content_width)


def response_padding(width: int) -> int:
    """Return the shared horizontal inset for a response at ``width``."""
    if width >= 72:
        return 3
    if width >= 48:
        return 2
    return 1


def response_content_width(width: int) -> int:
    """Return the exact inner content width for a response box at ``width``."""
    box_w = max(width, 24)
    return max(box_w - 2 - 2 * response_padding(box_w), 1)


def box_top(width: int = 80) -> str:
    """Render the rounded top border for an assistant response."""
    w = max(width, 12)
    return f"╭─ hund {'─' * max(w - 9, 2)}╮"


def box_bottom(width: int = 80, meta: str | None = None) -> str:
    """Render the rounded bottom border with optional right-aligned meta."""
    w = max(width, 12)
    if meta is None or not str(meta).strip():
        return f"╰{'─' * max(w - 2, 2)}╯"
    meta_str = str(meta).strip()
    trailing = min(4, max(w - len(meta_str) - 4, 1))
    leading = max(w - len(meta_str) - trailing - 4, 1)
    return f"╰{'─' * leading} {meta_str} {'─' * trailing}╯"


def render_response_box(
    text: str,
    terminal_width: int = 80,
    meta: str | None = None,
) -> str:
    """Render response text inside a full-width geometric box with generous padding.

    - Always spans the full terminal width (fullscreen).
    - 1 top and 1 bottom padding row inside the box.
    - Responsive horizontal padding: 3 spaces wide, 2 medium, 1 compact.
    - Hard word-wrapped inside the selected padding.
    - Meta is rendered right-aligned in the rounded bottom border.
    """
    box_w = max(terminal_width, 24)
    padding = response_padding(box_w)
    cw = response_content_width(box_w)

    wrapped = wrap_content(text, cw)

    if not wrapped:
        return f"{box_top(box_w)}\n{box_bottom(box_w, meta)}"

    lines = [box_top(box_w)]
    # Top padding row (1 row per TUI_FACIT.md §2 and §15)
    lines.append(f"│{' ' * (box_w - 2)}│")

    # Content rows
    for line in wrapped:
        line_w = cell_width(line)
        diff_pad = max(cw - line_w, 0)
        lines.append(f"│{' ' * padding}{line}{' ' * diff_pad}{' ' * padding}│")

    # Bottom padding row (1 row)
    lines.append(f"│{' ' * (box_w - 2)}│")
    lines.append(box_bottom(box_w, meta))
    return "\n".join(lines)


def render_response_box_from_segments(
    segments: list[Any],
    terminal_width: int = 80,
    meta: str | None = None,
) -> tuple[str, dict[int, tuple[str, str]]]:
    """Render typed semantic segments into a formatted response box and return line metadata map.

    Returns:
      (rendered_box_string, line_segment_map)
      where line_segment_map maps relative_box_line_index -> (segment_type, language)
    """
    box_w = max(terminal_width, 24)
    padding = response_padding(box_w)
    cw = response_content_width(box_w)

    formatted_content_lines: list[tuple[str, str, str]] = []  # (text, segment_type, lang)

    for seg in segments:
        seg_type = getattr(seg, "type", "prose")
        stype_str = seg_type.value if hasattr(seg_type, "value") else str(seg_type)
        lang = _sanitize_block_label(getattr(seg, "language", ""), cw)
        fn = _sanitize_block_label(getattr(seg, "filename", ""), cw)
        is_open = getattr(seg, "is_open", False)
        lines = getattr(seg, "lines", [])

        if stype_str == "code":
            block_str = format_code_block("\n".join(lines), language=lang, filename=fn, width=cw, is_open=is_open)
            for l in block_str.split("\n"):
                formatted_content_lines.append((sanitize_display_line(l), "code", lang))
        elif stype_str == "diff":
            block_str = format_diff_block("\n".join(lines), filename=fn, width=cw, is_open=is_open)
            diff_language = normalize_language_alias(fn.rsplit(".", 1)[-1]) if "." in fn else "diff"
            for l in block_str.split("\n"):
                formatted_content_lines.append((sanitize_display_line(l), "diff", diff_language))
        else:
            prose_text = "\n".join(lines) if isinstance(lines, (list, tuple)) else str(lines)
            wrapped = wrap_cells(prose_text, cw)
            for l in wrapped:
                formatted_content_lines.append((sanitize_display_line(l), "prose", ""))

    lines = [box_top(box_w)]
    line_metadata: dict[int, tuple[str, str]] = {}

    # Line 1 is top padding
    lines.append(f"│{' ' * (box_w - 2)}│")

    current_idx = 2
    for line_text, stype, slang in formatted_content_lines:
        line_w = cell_width(line_text)
        diff_pad = max(cw - line_w, 0)
        lines.append(f"│{' ' * padding}{line_text}{' ' * diff_pad}{' ' * padding}│")
        line_metadata[current_idx] = (stype, slang)
        current_idx += 1

    # Bottom padding row
    lines.append(f"│{' ' * (box_w - 2)}│")
    # Bottom border
    lines.append(box_bottom(box_w, meta))

    return "\n".join(lines), line_metadata

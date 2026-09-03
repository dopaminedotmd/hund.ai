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
    # Full projection (no limit) so specialisation rows can aggregate every
    # equipped member; the ACTIVE SKILLS columns slice top rows below.
    try:
        skill_data = project_active_skill_xp(
            active_skills,
            db_path=db_path,
        )
    except Exception:
        skill_data = ()

    rule = "--" if ascii_only else "──"
    skills_header = f"{rule} ACTIVE SKILLS {rule}"

    # Gate 3 QA: start screen shows the ACTIVE specialisations (equipped
    # domains), same model as the /skills catalog — never a static "(0/6)".
    active_spec_names: dict[str, int] = {}
    for skill in active_skills:
        if skill.domain and skill.domain != "general":
            active_spec_names[skill.domain] = active_spec_names.get(skill.domain, 0) + 1
    spec_names = sorted(active_spec_names)
    specialisations_header = f"{rule} SPECIALISATIONS ({len(spec_names)}/6) {rule}"

    def specialisation_lines() -> list[str]:
        if not spec_names:
            return [row("No active specialisations")]
        # agyD/9 QA: specialisations on the start page get the same level +
        # progress bar visual language as active skills (max member level,
        # mean member progress), reusing the already-computed XP projection.
        projection_by_capability = {
            proj.capability_id: proj for proj in skill_data
        }
        bar_cells = 10 if W >= 72 else max(4, min(10, W - 27))
        # Keep the fixed tail (level+bar+pct) inside the content width so the
        # trailing "%" never gets clipped on narrow screens.
        tail_cells = 11 + bar_cells
        domain_pad = max(4, min(16, (W - 6) - tail_cells))
        out: list[str] = []
        for domain in spec_names[:6]:
            members = [s for s in active_skills if s.domain == domain]
            projections = [
                projection_by_capability[getattr(s, "capability_id", "") or s.name]
                for s in members
                if (getattr(s, "capability_id", "") or s.name) in projection_by_capability
            ]
            if projections:
                level = max(proj.level for proj in projections)
                pct = round(
                    sum(proj.progress_percent for proj in projections) / len(projections)
                )
            else:
                level, pct = 1, 0
            bar = progress_bar(pct, bar_cells)
            out.append(row(f"● {domain:<{domain_pad}} L{level} {bar} {pct:>3}%"))
        return out

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
        lines.extend([empty, row(specialisations_header), *specialisation_lines()])
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
        lines.extend([empty, row(specialisations_header), *specialisation_lines()])

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


from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ToolFlowRow:
    text: str
    kind: str  # "activity", "diff", "error", "summary", "substep"
    language: str = ""


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
    status: str = "",
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

    if status == "created" and not any(r.startswith(("+", "-")) for r in raw_lines):
        content_lines = [("+", l) for l in raw_lines]
    elif not content_lines:
        content_lines = [(" ", l) for l in raw_lines]

    body_lines: list[str] = []

    old_num = 1
    new_num = 1
    for kind, text in content_lines:
        if kind == "-":
            prefix = f"- {old_num:<4} "
            old_num += 1
        elif kind == "+":
            prefix = f"+ {new_num:<4} "
            new_num += 1
        else:
            prefix = f"  {new_num:<4} "
            old_num += 1
            new_num += 1
        content, _ = slice_cells(text.rstrip(), max(w - cell_width(prefix), 0))
        row = prefix + content
        body_lines.append(row + " " * max(w - cell_width(row), 0))

    adds = sum(kind == "+" for kind, _ in content_lines)
    dels = sum(kind == "-" for kind, _ in content_lines)
    counts = f"  (+{adds} -{dels})"

    # Handle narrow terminal formatting (<48 columns) without character clipping
    status_tag = f"[{status}] " if status else ""
    header_base = f"  └ {status_tag}{filename or 'diff'}"
    if w < 48 and (cell_width(header_base) + cell_width(counts)) > w:
        safe_fn, _ = slice_cells(f"{status_tag}{filename or 'diff'}", max(w - cell_width("  └ "), 1))
        lines = [f"  └ {safe_fn}", f"    {counts.strip()}", *body_lines]
    else:
        safe_fn = _sanitize_block_label(f"{status_tag}{filename or 'diff'}", max(w - cell_width("  └ ") - cell_width(counts), 1))
        lines = [f"  └ {safe_fn}{counts}", *body_lines]

    if is_limited:
        lines.append("  … Diff preview limited.")
    return "\n".join(lines)


def format_markdown_table(raw_lines: list[str], max_width: int) -> list[tuple[str, str, str]]:
    """Format markdown table rows with aligned column widths and cell wrapping.

    Falls back to stacked/linear view if max_width is below minimum column width threshold.
    Returns list of (formatted_line, 'table', 'header'|'sep'|'row').
    """
    if not raw_lines:
        return []

    cleaned_lines = [l.replace("\r", "").strip() for l in raw_lines if l.strip()]
    if not cleaned_lines:
        return []

    parsed_rows: list[list[str]] = []
    is_sep_row: list[bool] = []
    for line in cleaned_lines:
        s = line
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        cells = [c.strip() for c in s.split("|")]
        parsed_rows.append(cells)
        sep = bool(cells and all(re.match(r"^:?-+:?$", c) for c in cells if c))
        is_sep_row.append(sep)

    if not parsed_rows:
        return []

    header_cells: list[str] = []
    data_rows: list[list[str]] = []
    if len(parsed_rows) >= 2 and is_sep_row[1]:
        header_cells = parsed_rows[0]
        data_rows = [r for i, r in enumerate(parsed_rows[2:], 2) if not is_sep_row[i]]
    else:
        if is_sep_row[0]:
            data_rows = [r for i, r in enumerate(parsed_rows[1:], 1) if not is_sep_row[i]]
        else:
            if len(parsed_rows) > 1:
                header_cells = parsed_rows[0]
                data_rows = [r for i, r in enumerate(parsed_rows[1:], 1) if not is_sep_row[i]]
            else:
                data_rows = [parsed_rows[0]]

    all_rows = ([header_cells] if header_cells else []) + data_rows
    if not all_rows:
        return []

    num_cols = max(len(r) for r in all_rows)
    if num_cols == 0:
        return []

    for r in all_rows:
        while len(r) < num_cols:
            r.append("")

    min_col_w = 6
    border_overhead = 3 * num_cols + 1
    min_table_w = num_cols * min_col_w + border_overhead

    # Fallback to stacked/linear view if max_width is below min_table_w or narrow (<45)
    if max_width < min_table_w or max_width < 45:
        fallback_rows: list[tuple[str, str, str]] = []
        for row_idx, d_row in enumerate(data_rows):
            if row_idx > 0:
                sep_line = "─" * min(max_width, 36)
                fallback_rows.append((sep_line, "table", "sep"))
            for c_idx, val in enumerate(d_row):
                col_name = header_cells[c_idx] if (header_cells and c_idx < len(header_cells) and header_cells[c_idx]) else f"Col {c_idx + 1}"
                line_str = f"• {col_name}: {val}"
                for w_line in wrap_cells(line_str, max_width):
                    fallback_rows.append((w_line, "table", "row"))
        return fallback_rows

    nat_widths = [max((cell_width(r[c]) for r in all_rows), default=1) for c in range(num_cols)]
    avail_width = max(max_width - border_overhead, num_cols * min_col_w)
    total_nat = sum(nat_widths)

    if total_nat <= avail_width:
        col_widths = list(nat_widths)
    else:
        col_widths = [max(min_col_w, int(avail_width * (w / total_nat))) for w in nat_widths]
        while sum(col_widths) > avail_width:
            max_idx = max(range(num_cols), key=lambda c: col_widths[c])
            if col_widths[max_idx] <= min_col_w:
                break
            col_widths[max_idx] -= 1
        while sum(col_widths) < avail_width:
            min_idx = min(range(num_cols), key=lambda c: col_widths[c])
            col_widths[min_idx] += 1

    def format_row(cells: list[str], row_type: str) -> list[tuple[str, str, str]]:
        wrapped_cols = [wrap_cells(cells[c], col_widths[c]) for c in range(num_cols)]
        max_h = max(len(w) for w in wrapped_cols)
        out_lines: list[tuple[str, str, str]] = []
        for h in range(max_h):
            chunks: list[str] = []
            for c in range(num_cols):
                text = wrapped_cols[c][h] if h < len(wrapped_cols[c]) else ""
                pad = max(col_widths[c] - cell_width(text), 0)
                chunks.append(f" {text}{' ' * pad} ")
            out_lines.append(("|" + "|".join(chunks) + "|", "table", row_type))
        return out_lines

    result: list[tuple[str, str, str]] = []
    if header_cells:
        result.extend(format_row(header_cells, "header"))
        sep_chunks = ["-" * (col_widths[c] + 2) for c in range(num_cols)]
        result.append(("|" + "|".join(sep_chunks) + "|", "table", "sep"))

    for d_row in data_rows:
        result.extend(format_row(d_row, "row"))

    return result


def repad_diff_block(lines: list[str], width: int) -> list[str]:
    """Re-pad registered diff rows after the terminal width changes."""
    w = max(width, 24)
    return [
        line if index == 0 or line.strip() == "… Diff preview limited." or line.strip().startswith("(+")
        else slice_cells(line.rstrip(), w)[0] + " " * max(w - cell_width(slice_cells(line.rstrip(), w)[0]), 0)
        for index, line in enumerate(lines)
    ]


def _fit_tool_line(line: str, width: int) -> str:
    if cell_width(line) <= width:
        return line
    if width <= 1:
        return "…"
    return slice_cells(line, max(width - 1, 0))[0] + "…"


def format_tool_flow(
    events: Iterable[Any],
    width: int = 80,
    *,
    past_intent: str = "",
    ascii_only: bool = False,
) -> tuple[ToolFlowRow, ...]:
    """Shared formatter producing a unified sequence of ToolFlowRow presentation items.

    Invariants:
      - Returns immutable tuple of ToolFlowRow(text, kind, language)
      - kind is strictly one of 'activity', 'diff', 'error', 'summary', 'substep', 'interim_border', 'interim_text'
      - language is set only for 'diff' rows
    """
    ev_list = list(events)
    if not ev_list and not past_intent:
        return ()

    w = max(width, 24)
    rail = "|" if ascii_only else "┊"
    running_sym = "*" if ascii_only else "⟳"
    complete_sym = "+" if ascii_only else "✓"
    error_sym = "x" if ascii_only else "✗"
    summary_branch = "+-" if ascii_only else "╰─"
    top_branch = "+-" if ascii_only else "╭─"
    h_bar = "-" if ascii_only else "─"
    pipe = "|" if ascii_only else "│"

    rows: list[ToolFlowRow] = []

    # Optional intent line
    if past_intent:
        intent_text = past_intent if past_intent.startswith("  ") else f"  {past_intent}"
        rows.append(ToolFlowRow(text=_fit_tool_line(intent_text, w), kind="activity"))

    if not ev_list:
        return tuple(rows)

    # Split ev_list into chunks of ("tools", [ToolActivity, ...]) and ("narration", NarrationActivity)
    chunks: list[tuple[str, Any]] = []
    current_tools: list[Any] = []
    for ev in ev_list:
        if hasattr(ev, "text") and not hasattr(ev, "tool_name"):
            if current_tools:
                chunks.append(("tools", list(current_tools)))
                current_tools.clear()
            chunks.append(("narration", ev))
        else:
            current_tools.append(ev)
    if current_tools:
        chunks.append(("tools", list(current_tools)))

    # Fast-Turn Collapse constraint check (TUI Facit §5.7)
    if len(chunks) == 1 and chunks[0][0] == "tools" and len(chunks[0][1]) == 1 and not past_intent:
        ev = chunks[0][1][0]
        status_val = ev.status.value if hasattr(ev.status, "value") else str(ev.status)
        is_readonly = getattr(ev, "group", "") in {"read", "inspection", "web_read", "search", "web_search"}
        is_safe_complete = status_val == "complete"
        is_fast = getattr(ev, "duration_s", 0.0) <= 0.70
        is_not_verif = getattr(ev, "group", "") != "verification"
        is_not_error = status_val not in {"error", "blocked", "declined"}
        no_confirm = not getattr(ev, "required_confirmation", False)
        is_explicitly_not_security = (getattr(ev, "security_relevant", None) is False)
        no_detail = not getattr(ev, "detail", "")
        no_attached_diff = not getattr(ev, "attached_diff_lines", None)
        no_attached_error = not getattr(ev, "attached_error_lines", None)

        if (
            is_readonly
            and is_safe_complete
            and is_fast
            and is_not_verif
            and is_not_error
            and no_confirm
            and is_explicitly_not_security
            and no_detail
            and no_attached_diff
            and no_attached_error
        ):
            dur = getattr(ev, "duration_s", 0.0)
            dur_str = f"{dur:.1f}s" if dur > 0 else "0.1s"
            desc = getattr(ev, "description", "")
            return (ToolFlowRow(text=_fit_tool_line(f"  hund {desc}.            {dur_str}", w), kind="activity"),)

    for chunk_type, chunk_data in chunks:
        if chunk_type == "narration":
            narr_text = getattr(chunk_data, "text", "")
            if narr_text:
                header_prefix = f"  {top_branch} hund "
                fill_len = max(w - cell_width(header_prefix), 1)
                header_line = header_prefix + (h_bar * fill_len)
                rows.append(ToolFlowRow(text=header_line, kind="interim_border"))

                inner_w = max(w - 4, 10)
                raw_lines = [l.strip() for l in narr_text.strip().splitlines() if l.strip()]
                wrapped_lines: list[str] = []
                for r in raw_lines:
                    wrapped_lines.extend(wrap_cells(r, inner_w))
                if not wrapped_lines:
                    wrapped_lines = [""]
                for ln in wrapped_lines:
                    rows.append(ToolFlowRow(text=f"  {pipe} {ln}", kind="interim_text"))
                rows.append(ToolFlowRow(text=f"  {rail}", kind="activity"))
            continue

        # Process tool events batch
        batch_events = chunk_data
        i = 0
        n = len(batch_events)
        while i < n:
            ev = batch_events[i]
            status_val = ev.status.value if hasattr(ev.status, "value") else str(ev.status)
            group_name = getattr(ev, "group", "")
            depth = getattr(ev, "subagent_depth", 0)
            has_diff = bool(getattr(ev, "attached_diff_lines", None))
            has_err = bool(getattr(ev, "attached_error_lines", None))

            # Group consecutive completed readonly events only if no diffs/errors attached
            if (
                status_val == "complete"
                and group_name in {"read", "inspection", "search", "web_read", "web_search"}
                and not has_diff
                and not has_err
                and depth == 0
            ):
                group_events = [ev]
                j = i + 1
                while j < n:
                    next_ev = batch_events[j]
                    next_status = next_ev.status.value if hasattr(next_ev.status, "value") else str(next_ev.status)
                    if (
                        next_status == "complete"
                        and getattr(next_ev, "group", "") == group_name
                        and not getattr(next_ev, "attached_diff_lines", None)
                        and not getattr(next_ev, "attached_error_lines", None)
                        and getattr(next_ev, "subagent_depth", 0) == 0
                    ):
                        group_events.append(next_ev)
                        j += 1
                    else:
                        break

                if len(group_events) > 1:
                    tot_dur = sum(getattr(e, "duration_s", 0.0) for e in group_events)
                    if group_name in {"read", "inspection"}:
                        desc = f"read relevant files    {len(group_events)} files"
                    elif group_name == "search":
                        desc = f"searched workspace     {len(group_events)} queries"
                    elif group_name == "web_search":
                        desc = f"searched official sources    {len(group_events)} queries"
                    elif group_name == "web_read":
                        desc = f"read relevant pages          {len(group_events)} sources"
                    else:
                        desc = f"inspected {len(group_events)} items"
                    suffix = f" · {tot_dur:.1f}s" if tot_dur > 0 else ""
                    row_text = f"  {rail} {complete_sym} {desc}{suffix}"
                    rows.append(ToolFlowRow(text=_fit_tool_line(row_text, w), kind="activity"))
                    i = j
                    continue

            # Subagent depth handling
            if depth > 2:
                indent = "    "
                row_text = f"{indent}… sub-step"
                rows.append(ToolFlowRow(text=_fit_tool_line(row_text, w), kind="substep"))
                i += 1
                continue

            base_indent_spaces = 2 + (depth * 2)
            indent_str = " " * base_indent_spaces
            kind = "substep" if depth > 0 else "activity"

            if status_val == "running":
                symbol = running_sym
            elif status_val in {"error", "blocked", "declined"}:
                symbol = error_sym
            else:
                symbol = complete_sym

            desc = getattr(ev, "description", "")
            detail = getattr(ev, "detail", "")
            if detail and status_val != "complete":
                desc = f"{desc} — {detail}"

            dur = getattr(ev, "duration_s", 0.0)
            suffix = f" · {dur:.1f}s" if dur > 0 and status_val != "running" else ""
            row_text = f"{indent_str}{rail} {symbol} {desc}{suffix}"
            rows.append(ToolFlowRow(text=_fit_tool_line(row_text, w), kind=kind))

            # Attached diff lines directly below their parent step
            diff_lines = getattr(ev, "attached_diff_lines", None)
            if diff_lines:
                diff_lang = getattr(ev, "attached_diff_language", "") or "diff"
                for d_line in diff_lines:
                    rows.append(ToolFlowRow(text=d_line, kind="diff", language=diff_lang))

            # Attached error lines directly below their parent step
            error_lines = getattr(ev, "attached_error_lines", None)
            if error_lines:
                for e_line in error_lines:
                    err_text = e_line if e_line.startswith("  ") else f"  {e_line}"
                    rows.append(ToolFlowRow(text=_fit_tool_line(err_text, w), kind="error"))

            i += 1

        # Completion summary capsule for this batch
        all_complete = all(
            (e.status.value if hasattr(e.status, "value") else str(e.status)) != "running"
            for e in batch_events
        )
        if batch_events and all_complete:
            statuses = {(e.status.value if hasattr(e.status, "value") else str(e.status)) for e in batch_events}
            total = sum(getattr(e, "duration_s", 0.0) for e in batch_events)
            has_verification = any(getattr(e, "group", "") == "verification" for e in batch_events)
            has_edits = any(getattr(e, "group", "") == "edit" for e in batch_events)
            has_web = any(getattr(e, "group", "") in {"web_search", "web_read"} for e in batch_events)

            if statuses & {"error", "blocked", "declined"}:
                summary_line = f"  {summary_branch} stopped · {total:.1f}s"
            elif has_edits and has_verification:
                summary_line = f"  {summary_branch} change holds · {total:.1f}s"
            elif has_verification:
                summary_line = f"  {summary_branch} clean run · {total:.1f}s"
            elif has_web and len(batch_events) >= 2:
                summary_line = f"  {summary_branch} cross-checked · {total:.1f}s"
            elif len(batch_events) >= 3:
                summary_line = f"  {summary_branch} completed · {len(batch_events)} steps · {total:.1f}s"
            else:
                summary_line = f"  {summary_branch} completed · {len(batch_events)} steps · {total:.1f}s" if (has_edits or statuses == {"complete"}) and len(batch_events) >= 2 else ""

            if summary_line:
                rows.append(ToolFlowRow(text=_fit_tool_line(summary_line, w), kind="summary"))

    return tuple(rows)


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
        elif stype_str == "table":
            table_lines = [l for l in lines]
            table_formatted = format_markdown_table(table_lines, cw)
            for t_line, t_stype, t_slang in table_formatted:
                formatted_content_lines.append((sanitize_display_line(t_line), t_stype, t_slang))
        else:
            prose_lines = lines if isinstance(lines, (list, tuple)) else str(lines).splitlines()
            current_chunk: list[str] = []
            table_chunk: list[str] = []
            for pl in prose_lines:
                s = pl.strip()
                if len(s) >= 2 and s.startswith("|") and s.endswith("|"):
                    if current_chunk:
                        wrapped = wrap_cells("\n".join(current_chunk), cw)
                        for l in wrapped:
                            formatted_content_lines.append((sanitize_display_line(l), "prose", ""))
                        current_chunk = []
                    table_chunk.append(pl)
                else:
                    if table_chunk:
                        table_formatted = format_markdown_table(table_chunk, cw)
                        for t_line, t_stype, t_slang in table_formatted:
                            formatted_content_lines.append((sanitize_display_line(t_line), t_stype, t_slang))
                        table_chunk = []
                    current_chunk.append(pl)
            if table_chunk:
                table_formatted = format_markdown_table(table_chunk, cw)
                for t_line, t_stype, t_slang in table_formatted:
                    formatted_content_lines.append((sanitize_display_line(t_line), t_stype, t_slang))
            if current_chunk:
                wrapped = wrap_cells("\n".join(current_chunk), cw)
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


def render_intermediate_capsule(
    text: str,
    width: int = 80,
    elapsed_s: float | None = None,
    *,
    ascii_only: bool = False,
) -> str:
    """Render an open intermediate narration panel in tree spine alignment."""
    w = max(width, 24)
    top_branch = "+-" if ascii_only else "╭─"
    h_bar = "-" if ascii_only else "─"
    pipe = "|" if ascii_only else "│"
    rail = "|" if ascii_only else "┊"

    header_prefix = f"  {top_branch} hund "
    fill_len = max(w - cell_width(header_prefix), 1)
    header_line = header_prefix + (h_bar * fill_len)

    inner_w = max(w - 4, 10)
    raw_lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    wrapped_lines: list[str] = []
    for r in raw_lines:
        wrapped_lines.extend(wrap_cells(r, inner_w))
    if not wrapped_lines:
        wrapped_lines = [""]

    lines = [header_line]
    for ln in wrapped_lines:
        lines.append(f"  {pipe} {ln}")
    lines.append(f"  {rail}")
    return "\n".join(lines)


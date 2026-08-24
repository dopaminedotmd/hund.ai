"""Pure responsive rendering for all temporary TUI destinations and overlays."""
from __future__ import annotations

import json
import textwrap
from datetime import date, timedelta
from typing import Sequence

from ..providers.catalog import ModelOption, option_ready
from ..stats.tiers import render_bar
from .snapshots import (
    SkillItem,
    SkillsSnapshot,
    StatsSnapshot,
    ToolItem,
    ToolsSnapshot,
    UsageSnapshot,
)


def _clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    return textwrap.wrap(
        text, max(width, 1), replace_whitespace=False, drop_whitespace=True,
        break_long_words=True, break_on_hyphens=False,
    ) or [""]


def _section(title: str, width: int) -> str:
    prefix = f"── {title} "
    return _clip(prefix + "─" * max(0, width - len(prefix)), width)


def _tier_letter(tier: str) -> str:
    return {
        "Novice": "D", "Apprentice": "C", "Adept": "B",
        "Expert": "A", "Master": "S",
    }.get(tier, "—")


def fullscreen_frame(
    title: str,
    lines: Sequence[str],
    *,
    width: int,
    height: int,
    footer: str = "[Esc] Back to chat",
    meta: str = "",
    scroll: int = 0,
    ascii_only: bool = False,
) -> str:
    """Render stable title/footer chrome and a scrollable content viewport."""
    frame_width = max(20, width - 1)
    # Two border cells plus two spaces of padding on each side.
    inner = frame_width - 6
    if ascii_only:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    else:
        tl, tr, bl, br, h, v = "╔", "╗", "╚", "╝", "═", "║"
    title_text = f" {title} "
    meta_text = f" {meta} " if meta else ""
    rail = frame_width - 2 - len(title_text) - len(meta_text)
    top_content = tl + title_text + h * max(rail, 0) + meta_text
    top = top_content[: frame_width - 1].ljust(frame_width - 1, h) + tr

    body_rows = max(height - 2, 1)
    content_rows = max(body_rows - 1, 0)
    expanded: list[str] = []
    for line in lines:
        expanded.extend(_wrap(line, inner))
    maximum = max(0, len(expanded) - content_rows)
    start = min(max(scroll, 0), maximum)
    visible = expanded[start : start + content_rows]
    visible.extend([""] * (content_rows - len(visible)))
    footer_text = _clip(footer, inner)
    rows = [f"{v}  {_clip(line, inner).ljust(inner)}  {v}" for line in visible]
    rows.append(f"{v}  {footer_text.ljust(inner)}  {v}")
    bottom = bl + h * (frame_width - 2) + br
    return "\n".join([top, *rows, bottom])


def modal_frame(
    title: str,
    lines: Sequence[str],
    *,
    width: int,
    terminal_width: int,
    footer: str,
    ascii_only: bool = False,
) -> str:
    modal_width = min(width, max(terminal_width - 3, 30))
    # Two border cells plus two spaces of padding on each side.
    inner = modal_width - 6
    if ascii_only:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    else:
        tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"
    head = f"{tl}{h} {title} "
    top = head + h * max(0, modal_width - len(head) - 1) + tr
    rows = [v + " " * (modal_width - 2) + v]
    for line in lines:
        for wrapped in _wrap(line, inner):
            rows.append(f"{v}  {_clip(wrapped, inner).ljust(inner)}  {v}")
    rows.append(v + " " * (modal_width - 2) + v)
    rows.append(bl + h * (modal_width - 2) + br)
    rows.append(_clip(footer, modal_width))
    return "\n".join([top, *rows])


def stats_lines(snapshot: StatsSnapshot, width: int) -> list[str]:
    inner = max(width - 5, 16)
    stats = []
    for item in snapshot.stats:
        if item.value is None:
            stats.append(f"{item.abbreviation} {item.name.title():<10} No data yet")
        else:
            stats.append(
                f"{item.abbreviation} {item.name.title():<10} "
                f"{render_bar(item.percent, 10)} {item.percent:>3}% ({_tier_letter(item.tier)})"
            )
    specs = []
    for item in snapshot.specializations:
        lock = " LCK" if item.locked else ""
        specs.append(
            f"{item.name:<18} Lv.{item.level} "
            f"[{render_bar(item.percent, 8)}]{lock}"
        )
    if not specs:
        specs = ["No data yet"]

    lines: list[str] = [""]
    if width >= 72:
        left_w = max(31, (inner - 3) // 2)
        right_w = inner - left_w - 3
        lines.append(
            _section("BASE STATS", left_w) + " │ " + _section("SPECIALIZATIONS", right_w)
        )
        count = max(len(stats), len(specs))
        for index in range(count):
            left = stats[index] if index < len(stats) else ""
            right = specs[index] if index < len(specs) else ""
            lines.append(_clip(left, left_w).ljust(left_w) + " │ " + _clip(right, right_w))
    else:
        lines.extend([_section("BASE STATS", inner), *stats, "", _section("SPECIALIZATIONS", inner), *specs])

    lines.extend(["", _section("7-DAY VELOCITY", inner)])
    if snapshot.has_activity:
        maximum = max(snapshot.activity) or 1
        bars = " ".join("█" * max(1, round(value / maximum * 4)) if value else "·" for value in snapshot.activity)
        labels = " ".join(day.strftime("%a")[0] for day in snapshot.activity_dates)
        lines.extend([f"Activity / Day  {bars}", f"                {labels}"])
    else:
        lines.append("Activity / Day  No data yet")
    if snapshot.velocity:
        for name, delta, improving in snapshot.velocity:
            sign = "+" if delta >= 0 else "-"
            lines.append(f"{name.title():<12} {sign}{abs(delta):.1f}%")
    else:
        lines.append("Base Stat Deltas  No data yet")
    return lines


def render_stats(
    snapshot: StatsSnapshot, *, width: int, height: int, scroll: int = 0,
    ascii_only: bool = False,
) -> str:
    return fullscreen_frame(
        "STATS", stats_lines(snapshot, width), width=width, height=height,
        meta=f"v{snapshot.version}", scroll=scroll, ascii_only=ascii_only,
    )


def _skill_row(skill: SkillItem, selected: bool, compact: bool) -> str:
    marker = "❯ ●" if selected else "  ○"
    if compact:
        return f"{marker} {_clip(skill.name, 17):<17} Lv.{skill.level} {skill.percent:>3}%"
    return (
        f"{marker} {_clip(skill.name, 20):<20} {render_bar(skill.percent, 10)} "
        f"{skill.tier:<11} {skill.percent:>3}% [{skill.vault_state}]"
    )


def skills_lines(snapshot: SkillsSnapshot, width: int, selected: int) -> list[str]:
    all_skills = snapshot.equipped + snapshot.parked
    lines = ["", _section(
        f"EQUIPPED SPECIALIZATIONS ({len(snapshot.equipped)}/{snapshot.max_active})",
        max(width - 5, 16),
    )]
    if snapshot.equipped:
        lines.extend(
            _skill_row(skill, index == selected, width < 60)
            for index, skill in enumerate(snapshot.equipped)
        )
    else:
        lines.append("No domain skills equipped.")
    lines.extend(["", _section(f"VAULT · PARKED ({len(snapshot.parked)})", max(width - 5, 16))])
    offset = len(snapshot.equipped)
    if snapshot.parked:
        lines.extend(
            _skill_row(skill, offset + index == selected, width < 60)
            for index, skill in enumerate(snapshot.parked)
        )
    else:
        lines.append("No parked domain skills.")
    return lines


def skill_detail_lines(skill: SkillItem) -> list[str]:
    return [
        "",
        _section(f"SKILL DETAIL · {skill.name}", 68),
        f"Domain: {skill.domain or 'general'}",
        f"Lifecycle: {skill.lifecycle_state} · Vault: {skill.vault_state}",
        f"XP: {skill.xp} · Level {skill.level} · {skill.tier} · {skill.percent}%",
        f"Safety level: {skill.safety_level}",
        f"Triggers: {', '.join(skill.triggers) if skill.triggers else 'None declared'}",
        f"Tools: {', '.join(skill.tools) if skill.tools else 'None declared'}",
        f"Provenance: {', '.join(skill.provenance) if skill.provenance else 'Unavailable'}",
        "",
        skill.when_to_use or "No usage description.",
    ]


def render_skills(
    snapshot: SkillsSnapshot,
    *,
    width: int,
    height: int,
    selected: int = 0,
    scroll: int = 0,
    detail_name: str | None = None,
    status: str = "",
    ascii_only: bool = False,
) -> str:
    all_skills = snapshot.equipped + snapshot.parked
    detail = next((item for item in all_skills if item.name == detail_name), None)
    lines = skill_detail_lines(detail) if detail else skills_lines(snapshot, width, selected)
    if status:
        lines.extend(["", status])
    footer = (
        "[Esc] Back to chat · ↑↓ select · [e] equip · [p] park · Enter inspect"
        if not detail else "[Esc] Back to specializations"
    )
    return fullscreen_frame(
        "SPECIALIZATIONS", lines, width=width, height=height,
        meta=f"[{len(snapshot.equipped)}/{snapshot.max_active} slots]",
        footer=footer, scroll=scroll, ascii_only=ascii_only,
    )


def tool_detail_lines(tool: ToolItem) -> list[str]:
    schema = json.dumps(tool.parameters, indent=2, sort_keys=True)
    return [
        "", _section(f"TOOL DETAIL · {tool.name}", 68),
        tool.description,
        "",
        f"Category: {tool.category or 'Unavailable'}",
        f"Safety level: {tool.safety_level}",
        f"Context mode: {tool.context_mode}",
        f"Dispatch: {tool.dispatch_description or 'Unavailable'}",
        "",
        "Parameter schema:",
        *schema.splitlines(),
    ]


def tools_lines(snapshot: ToolsSnapshot, width: int, selected: int) -> list[str]:
    inner = max(width - 5, 16)
    lines = ["", _section(
        f"MOTOR SKILLS ({len(snapshot.motor_skills)} CONSTITUTIONAL GUARDRAILS)", inner,
    )]
    if width >= 72:
        col = max(18, inner // 3)
        for start in range(0, len(snapshot.motor_skills), 3):
            lines.append(" ".join(_clip(name, col - 1).ljust(col) for name in snapshot.motor_skills[start:start + 3]).rstrip())
    else:
        lines.extend(snapshot.motor_skills)
    lines.extend(["", _section("REGISTERED TOOLS & PERMISSIONS", inner)])
    if width >= 72:
        lines.append("TOOL                 CATEGORY       SAFETY LEVEL      DISPATCH")
    for index, tool in enumerate(snapshot.tools):
        marker = "❯" if index == selected else " "
        if width >= 72:
            lines.append(
                f"{marker} {_clip(tool.name, 19):<19} "
                f"{_clip(tool.category or '—', 13):<13} "
                f"{_clip(tool.safety_level, 17):<17} "
                f"{tool.dispatch_description or '—'}"
            )
        else:
            lines.append(f"{marker} {_clip(tool.name, 18):<18} {tool.safety_level}")
    if not snapshot.tools:
        lines.append("No tools registered.")
    return lines


def render_tools(
    snapshot: ToolsSnapshot,
    *,
    width: int,
    height: int,
    selected: int = 0,
    scroll: int = 0,
    detail_name: str | None = None,
    ascii_only: bool = False,
) -> str:
    detail = next((tool for tool in snapshot.tools if tool.name == detail_name), None)
    lines = tool_detail_lines(detail) if detail else tools_lines(snapshot, width, selected)
    footer = (
        "[Esc] Back to tools" if detail
        else "[Esc] Back to chat · ↑↓ scroll tools · Enter inspect schema"
    )
    return fullscreen_frame(
        "TOOLS", lines, width=width, height=height,
        meta=f"[{len(snapshot.tools)} tools]", footer=footer, scroll=scroll,
        ascii_only=ascii_only,
    )


def _weeks(snapshot: UsageSnapshot) -> list[date]:
    first_sunday = snapshot.first_day - timedelta(days=(snapshot.first_day.weekday() + 1) % 7)
    last_sunday = snapshot.last_day - timedelta(days=(snapshot.last_day.weekday() + 1) % 7)
    result = []
    cursor = first_sunday
    while cursor <= last_sunday:
        result.append(cursor)
        cursor += timedelta(days=7)
    return result


def usage_lines(snapshot: UsageSnapshot, width: int) -> list[str]:
    inner = max(width - 5, 16)
    day_map = {item.day: item for item in snapshot.days}
    weeks = _weeks(snapshot)
    cell_sep = " " if width >= 60 else ""
    max_weeks = max(1, (inner - 4) // (2 if cell_sep else 1))
    weeks = weeks[-max_weeks:]
    glyphs = ("□", "░", "▒", "▓", "█")
    lines = ["", _section("TOKEN ACTIVITY (LAST 7 MONTHS)", inner)]

    month_chars = [" "] * max(1, len(weeks) * (2 if cell_sep else 1))
    previous_month = None
    for index, week in enumerate(weeks):
        if week.month != previous_month:
            label = week.strftime("%b")
            pos = index * (2 if cell_sep else 1)
            for offset, char in enumerate(label):
                if pos + offset < len(month_chars):
                    month_chars[pos + offset] = char
            previous_month = week.month
    lines.append("     " + "".join(month_chars).rstrip())
    for row, label in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
        cells = []
        for week in weeks:
            item = day_map.get(week + timedelta(days=row))
            cells.append(glyphs[item.level if item else 0])
        lines.append(f"{label:>3}  " + cell_sep.join(cells))
    lines.extend(["", "Less  □ ░ ▒ ▓ █  More", "", _section(
        "7-MONTH TOTAL", inner,
    )])
    lines.append(
        f"Prompt: {sum(day.prompt_tokens for day in snapshot.days):,} · "
        f"Output: {sum(day.output_tokens for day in snapshot.days):,} · "
        f"Requests: {sum(day.requests for day in snapshot.days):,}"
    )
    lines.extend(["", _section(
        f"ACTIVE SESSION ({'#' + snapshot.session_id[:8] if snapshot.session_id else 'none'})",
        inner,
    )])
    if snapshot.session.available:
        lines.append(
            f"Prompt: {snapshot.session.prompt_tokens:,} · "
            f"Output: {snapshot.session.output_tokens:,} · "
            f"Requests: {snapshot.session.requests}"
        )
    else:
        lines.append("Session token linkage unavailable.")
    return lines


def render_usage(
    snapshot: UsageSnapshot, *, width: int, height: int, scroll: int = 0,
    ascii_only: bool = False,
) -> str:
    return fullscreen_frame(
        "USAGE", usage_lines(snapshot, width), width=width, height=height,
        scroll=scroll, ascii_only=ascii_only,
    )


THEME_OPTIONS = (
    ("marshmallow", "Clean white & cyan glow"),
)


def render_theme_modal(
    active: str, selected: int, terminal_width: int, *, ascii_only: bool = False,
) -> str:
    lines = []
    for index, (name, description) in enumerate(THEME_OPTIONS):
        marker = "❯ ●" if index == selected else "  ○"
        suffix = " (default)" if name == "marshmallow" else ""
        label = _clip(name + suffix, 21)
        lines.append(
            f"{marker} {label:<21} {_clip(description, 20):<20} [■ ■ ■ ■ ■]"
        )
    lines.extend(["", f"Active: {active} · Saved on selection"])
    return modal_frame(
        "SELECT THEME", lines, width=68, terminal_width=terminal_width,
        footer="[Esc] cancel · ↑↓ browse · Enter select", ascii_only=ascii_only,
    )


def render_model_modal(
    options: Sequence[ModelOption],
    active_model: str,
    selected: int,
    terminal_width: int,
    *,
    ascii_only: bool = False,
    local_ready: bool | None = None,
) -> str:
    lines = []
    active = next((item for item in options if item.model_id == active_model), None)
    for index, option in enumerate(options):
        marker = "❯ ●" if index == selected else "  ○"
        if option.is_local:
            ready = option_ready(option) if local_ready is None else local_ready
            status = "[Ready]" if ready else "[Unavailable]"
        else:
            status = "[Key OK]" if option_ready(option) else "[Key missing]"
        if terminal_width < 48:
            lines.append(f"{marker} {_clip(option.model_id, 16):<16} {status}")
        elif terminal_width < 72:
            lines.append(
                f"{marker} {_clip(option.model_id, 20):<20} {option.context_window // 1000:>3}k · {status}"
            )
        else:
            lines.append(
                f"{marker} {_clip(option.model_id, 24):<24} "
                f"{option.provider_name:<10} · {option.context_window // 1000:>3}k · {status}"
            )
    if active:
        lines.extend([
            "",
            f"Active: {active.provider_name} / {active.model_id}",
            f"Context: {active.context_window:,} tokens",
        ])
    else:
        lines.extend([
            "",
            f"Active: {active_model} · Custom configuration",
        ])
    return modal_frame(
        "CHOOSE ACTIVE MODEL", lines, width=74, terminal_width=terminal_width,
        footer="[Esc] cancel · ↑↓ browse · Enter select · [e] custom · [k] set key",
        ascii_only=ascii_only,
    )


def render_model_custom_modal(
    value: str, terminal_width: int, status: str = "", *, ascii_only: bool = False,
) -> str:
    lines = [
        "Enter: provider | base URL | model ID | context window",
        "",
        f"> {value}",
    ]
    if status:
        lines.extend(["", status])
    return modal_frame(
        "CUSTOM MODEL", lines, width=74, terminal_width=terminal_width,
        footer="[Esc] back · Enter apply", ascii_only=ascii_only,
    )


def render_model_key_modal(
    provider_name: str,
    masked_value: str,
    terminal_width: int,
    status: str = "",
    *,
    ascii_only: bool = False,
) -> str:
    lines = [
        f"Credential for {provider_name}",
        "",
        f"> {masked_value}",
        "",
        "The key is stored in Windows Credential Manager.",
    ]
    if status:
        lines.extend(["", status])
    return modal_frame(
        "SET API KEY", lines, width=68, terminal_width=terminal_width,
        footer="[Esc] back · Enter save", ascii_only=ascii_only,
    )

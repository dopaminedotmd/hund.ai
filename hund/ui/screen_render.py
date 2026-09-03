"""Pure responsive rendering for all temporary TUI destinations and overlays."""
from __future__ import annotations

import json
import textwrap
from datetime import date, timedelta
from typing import Sequence

from ..doctor import DoctorReport
from ..providers.catalog import ModelOption, option_ready
from ..secrets import get_credential_status
from ..stats.environment_snapshot import EnvironmentSnapshot
from ..stats.tiers import render_bar
from .command_spec import get_categorized_commands
from .snapshots import (
    CatalogSpecialisation,
    SkillItem,
    SkillProposalItem,
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
    if footer:
        for f_segment in footer.splitlines():
            for f_line in _wrap(f_segment, modal_width):
                rows.append(_clip(f_line, modal_width))
    return "\n".join([top, *rows])


def _vertical_velocity_chart(activity: Sequence[int], labels: Sequence[Any], width: int) -> list[str]:
    """Three-row vertical column chart + day-letter axis (Gate 3 §2.2)."""
    max_v = max(activity) if activity and max(activity) > 0 else 1
    n = len(activity)
    cell_w = max(2, min(4, width // max(n, 1)))
    rows: list[str] = []
    for level in (3, 2, 1):
        label = str(round(max_v * level / 3))
        cells: list[str] = []
        for value in activity:
            filled = value >= max(1, round(max_v * level / 3))
            cells.append(("█" if filled else " ") * cell_w)
        rows.append(f"{label:>3} ┤ " + " ".join(cells).rstrip())
    axis_label = "".join(str(day.strftime("%a")[0]).ljust(cell_w) for day in labels)
    rows.append(f"   └─" + axis_label)
    return rows


def stats_lines(snapshot: StatsSnapshot, width: int) -> list[str]:
    frame_w = max(20, width - 1)
    inner = max(frame_w - 6, 16)

    def barrow(item: Any) -> str:
        if item.value is None:
            return f"{item.abbreviation} {item.name.title():<9} No data yet"
        return (
            f"{item.abbreviation} {item.name.title():<9} "
            f"{render_bar(item.percent, 10)} {item.percent:>3}%"
        )

    stats = [barrow(item) for item in snapshot.stats]
    # ACTIVE SKILLS column: real domain skills with level + bar (Gate 3 §2.2).
    skills = [
        f"{item.name:<18} L{item.level} {render_bar(item.percent, 8)} {item.percent:>3}%"
        for item in snapshot.specializations
    ]
    if not skills:
        skills = ["No active skills yet"]
    specs = [
        f"{'●' if getattr(item, 'locked', False) else '○'} {item.name:<18} L{item.level} "
        f"{render_bar(item.percent, 8)} {item.percent:>3}%  [active]"
        for item in snapshot.specializations
    ]
    if not specs:
        specs = ["No specialisations yet"]

    lines: list[str] = [""]
    if inner >= 72:
        left_w = max(31, (inner - 3) // 2)
        right_w = max(10, inner - left_w - 3)
        lines.append(
            _section("BASE STATS", left_w) + " │ " + _section("ACTIVE SKILLS", right_w)
        )
        count = max(len(stats), len(skills))
        for index in range(count):
            left = stats[index] if index < len(stats) else ""
            right = skills[index] if index < len(skills) else ""
            lines.append(_clip(left, left_w).ljust(left_w) + " │ " + _clip(right, right_w))
    else:
        lines.extend([_section("BASE STATS", inner), *stats, "", _section("ACTIVE SKILLS", inner), *skills])

    lines.extend(["", _section(f"SPECIALISATIONS ({len(snapshot.specializations)})", inner), *specs])

    if inner >= 72:
        lines.extend(["", _section("7-DAY VELOCITY", left_w) + " │ " + _section("BASE STAT DELTAS", right_w)])
        chart = _vertical_velocity_chart(snapshot.activity, snapshot.activity_dates, left_w)
        deltas = [
            f"{name.title():<11} {'+' if delta >= 0 else '-'}{abs(delta):.1f}%"
            for name, delta, _improving in snapshot.velocity
        ]
        if not deltas:
            deltas = ["No data yet"]
        count = max(len(chart), len(deltas))
        for index in range(count):
            left = chart[index] if index < len(chart) else ""
            right = deltas[index] if index < len(deltas) else ""
            lines.append(_clip(left, left_w).ljust(left_w) + " │ " + _clip(right, right_w))
    else:
        lines.extend(["", _section("7-DAY VELOCITY", inner)])
        if snapshot.has_activity:
            lines.extend(_vertical_velocity_chart(snapshot.activity, snapshot.activity_dates, inner))
        else:
            lines.append("No activity yet")
        lines.append(_section("BASE STAT DELTAS", inner))
        delta_rows = [
            f"{name.title():<11} {'+' if delta >= 0 else '-'}{abs(delta):.1f}%"
            for name, delta, _improving in snapshot.velocity
        ]
        lines.extend(delta_rows or ["No data yet"])
    return lines


def _stat_row_compact(item: Any) -> str:
    if item.value is None:
        return f"{item.abbreviation} {item.name.title():<9} No data yet"
    return (
        f"{item.abbreviation} {item.name.title():<9} "
        f"{render_bar(item.percent, 8)} {item.percent:>3}%"
    )


def render_stats_inline(
    snapshot: StatsSnapshot,
    *,
    width: int,
    ascii_only: bool = False,
) -> str:
    """Gate 3 §2.1: four-quadrant double-frame card printed inline in chat."""
    frame_w = max(20, width - 1)
    inner = max(frame_w - 6, 16)
    half_w = max(18, (inner - 1) // 2)
    v = "|" if ascii_only else "│"

    def col(line: str, w: int) -> str:
        return _clip(line, w).ljust(w)

    # Quadrant 1 — BASE STATS
    q1 = [_stat_row_compact(item) for item in snapshot.stats[:5]]
    # Quadrant 2 — ACTIVE SKILLS (real domain skills; fixed mislabelled column)
    q2: list[str] = []
    for item in snapshot.specializations[:5]:
        marker = "●" if getattr(item, "locked", False) else "○"
        q2.append(
            f"{marker} {col(item.name, 12)} L{item.level} "
            f"{render_bar(item.percent, 6)} {item.percent:>3}%"
        )
    if not q2:
        q2 = ["No active skills yet"]
    # Quadrant 3 — SPECIALISATIONS
    q3: list[str] = []
    for idx, item in enumerate(snapshot.specializations[:4]):
        q3.append(
            f"{'●' if getattr(item, 'locked', False) else '○'} "
            f"{col(item.name, 12)} L{item.level} "
            f"{render_bar(item.percent, 6)} {item.percent:>3}%"
        )
    if not q3:
        q3 = ["No specialisations yet"]
    # Quadrant 4 — TODAY & PROGRESS
    best = max(snapshot.specializations, key=lambda s: s.level, default=None)
    q4 = [f"XP Today:   +{snapshot.xp_today} XP ({snapshot.verified_today} verified)"]
    if best is not None:
        q4.append(f"Current:    {best.name} L{best.level} · {best.percent}%")
    else:
        q4.append("Current:    no skill xp yet")
    sign = "+" if snapshot.velocity_today_pct >= 0 else "-"
    q4.append(f"Velocity:   {sign}{abs(snapshot.velocity_today_pct)}% vs yesterday")

    lines: list[str] = []
    if inner >= 54:
        top_hdr = _section("BASE STATS", half_w) + f" {v} " + _section("ACTIVE SKILLS", half_w)
        bottom_hdr = _section("SPECIALISATIONS", half_w) + f" {v} " + _section("TODAY & PROGRESS", half_w)
        lines.append(top_hdr)
        for i in range(max(len(q1), len(q2))):
            lines.append(
                col(q1[i] if i < len(q1) else "", half_w)
                + f" {v} "
                + col(q2[i] if i < len(q2) else "", half_w)
            )
        lines.append("")
        lines.append(bottom_hdr)
        for i in range(max(len(q3), len(q4))):
            lines.append(
                col(q3[i] if i < len(q3) else "", half_w)
                + f" {v} "
                + col(q4[i] if i < len(q4) else "", half_w)
            )
    else:
        lines.extend(
            [_section("BASE STATS", inner), *q1, "", _section("ACTIVE SKILLS", inner),
             *q2, "", _section("SPECIALISATIONS", inner), *q3, "",
             _section("TODAY & PROGRESS", inner), *q4]
        )

    lines.append("")
    lines.append("commands: /stats full (7-day velocity & deltas) · /skills · /usage")
    return _double_frame_box("STATS", lines, width=width, ascii_only=ascii_only, meta=f"v{snapshot.version}")


def _double_frame_box(title: str, lines: Sequence[str], *, width: int, ascii_only: bool, meta: str = "") -> str:
    """Compact double-frame (╔═╗) card without viewport padding (inline use)."""
    frame_w = max(20, width - 1)
    inner = max(frame_w - 6, 16)
    if ascii_only:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    else:
        tl, tr, bl, br, h, v = "╔", "╗", "╚", "╝", "═", "║"
    title_text = f" {title} "
    meta_text = f" {meta} " if meta else ""
    head_len = 1 + len(title_text) + len(meta_text)
    top = (tl + h + title_text + meta_text + h * max(0, frame_w - 1 - head_len))[: frame_w - 1].ljust(frame_w - 1, h) + tr
    rows = [f"{v}  {_clip(line, inner).ljust(inner)}  {v}" for line in lines]
    bottom = bl + h * (frame_w - 2) + br
    return "\n".join([top, *rows, bottom])


def render_stats(
    snapshot: StatsSnapshot, *, width: int, height: int, scroll: int = 0,
    ascii_only: bool = False,
) -> str:
    footer = (
        "<- Back * [Esc/q] Close * ^v Scroll"
        if ascii_only
        else "[←] Back · [Esc/q] Close · ↑↓ Scroll"
    )
    return fullscreen_frame(
        "STATS · FULL VELOCITY & TRENDS", stats_lines(snapshot, width), width=width, height=height,
        meta=f"v{snapshot.version}", footer=footer,
        scroll=scroll, ascii_only=ascii_only,
    )


def _vault_tag(item: SkillItem) -> str:
    return "active" if item.vault_state == "equipped" else "parked"


def catalog_selectables(snapshot: SkillsSnapshot) -> tuple[tuple[str, int], ...]:
    """Ordered selectable (kind, index) entries for the /skills catalog.

    Shared source of truth between skills_lines (highlighting) and fullscreen
    navigation (count + Enter dispatch) — Gate 3 §2.3. Spec member `└` rows are
    informational and never consume a selectable slot, so they are absent here.
    """
    entries: list[tuple[str, int]] = []
    entries.extend(("skill", index) for index in range(len(snapshot.equipped)))
    entries.extend(("spec", index) for index in range(len(snapshot.specialisations)))
    entries.extend(("vault", index) for index in range(len(snapshot.parked)))
    entries.extend(("proposal", index) for index in range(len(snapshot.proposals)))
    return tuple(entries)


def _catalog_skill_row(skill: SkillItem, selected: bool, compact: bool) -> str:
    marker = "❯ ● " if selected else "  ○ "
    if compact:
        return (
            f"{marker}{_clip(skill.name, 15):<15} "
            f"L{skill.level} {skill.percent:>3}%  [{_vault_tag(skill)}]"
        )
    return (
        f"{marker}{_clip(skill.name, 17):<17} {render_bar(skill.percent, 10)} "
        f"L{skill.level} {skill.percent:>3}%  [{_vault_tag(skill)}]"
    )


def _catalog_spec_row(spec: CatalogSpecialisation, selected: bool, compact: bool) -> str:
    marker = "❯ ● " if selected else "  ○ "
    if compact:
        return (
            f"{marker}{_clip(spec.name, 15):<15} L{spec.level} {spec.percent:>3}%"
        )
    return (
        f"{marker}{_clip(spec.name, 17):<17} L{spec.level} "
        f"{render_bar(spec.percent, 10)} {spec.percent:>3}%  [active]"
    )


def _catalog_proposal_row(proposal: SkillProposalItem, selected: bool) -> str:
    marker = "❯ ● " if selected else "  ○ "
    return f"{marker}{_clip(proposal.name, 18):<18} ◇ {proposal.state}"


def skills_lines(snapshot: SkillsSnapshot, width: int, selected: int) -> list[str]:
    """Gate 3 §2.3: four-group catalog (SKILLS / SPECIALISATIONS / VAULT / PROPOSALS).

    Row order and selectable increments must stay in sync with
    catalog_selectables(): one `cursor` step per selectable row, none for
    section headers, spec `└` member rows, or empty placeholders.
    """
    compact = width < 60
    # Fullscreen frame inner width: frame_w = max(20, width - 1), two border
    # cells plus two spaces of padding on each side -> width - 7 at >= 27 cols.
    inner_w = max(max(20, width - 1) - 6, 16)
    lines: list[str] = []
    cursor = 0

    lines.extend(["", _section(f"SKILLS ({len(snapshot.equipped)})", inner_w)])
    for item in snapshot.equipped:
        lines.append(_catalog_skill_row(item, cursor == selected, compact))
        cursor += 1
    if not snapshot.equipped:
        lines.append("(No active skills equipped.)")

    lines.extend(
        ["", _section(f"SPECIALISATIONS ({len(snapshot.specialisations)})", inner_w)]
    )
    for spec in snapshot.specialisations:
        lines.append(_catalog_spec_row(spec, cursor == selected, compact))
        if spec.members:
            lines.append("      └ " + " · ".join(spec.members))
        cursor += 1
    if not snapshot.specialisations:
        lines.append("(No specialisations yet.)")

    lines.extend(["", _section(f"VAULT ({len(snapshot.parked)})", inner_w)])
    for item in snapshot.parked:
        lines.append(_catalog_skill_row(item, cursor == selected, compact))
        cursor += 1
    if not snapshot.parked:
        lines.append("(No parked skills.)")

    lines.extend(["", _section(f"PROPOSALS ({len(snapshot.proposals)})", inner_w)])
    for proposal in snapshot.proposals:
        lines.append(_catalog_proposal_row(proposal, cursor == selected))
        cursor += 1
    if not snapshot.proposals:
        lines.append("(No skill proposals.)")
    return lines


def skill_definition_text(skill: SkillItem) -> str:
    """Canonical machine-readable skill definition (vault JSON shape).

    Gate 3 §2.5.1: this exact text is what [c] copies and D6's editor validates
    and saves back, so it stays JSON-parseable.
    """
    data = {
        "name": skill.name,
        "domain": skill.domain,
        "scope": skill.scope,
        "version": skill.version,
        "capability_id": skill.capability_id,
        "safety_level": skill.safety_level,
        "lifecycle_state": skill.lifecycle_state,
        "vault_state": skill.vault_state,
        "triggers": list(skill.triggers),
        "tools": list(skill.tools),
        "when_to_use": skill.when_to_use,
        "steps": list(skill.steps),
        "verification": list(skill.verification),
        "limitations": list(skill.limitations),
        "provenance": list(skill.provenance),
        "xp": skill.xp,
        "level": skill.level,
        "tier": skill.tier,
        "progress_percent": skill.percent,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def skill_detail_lines(skill: SkillItem) -> list[str]:
    """Gate 3 §2.5.1: the exact, complete skill definition — no curation."""
    return ["", *skill_definition_text(skill).splitlines()]


def render_skill_editor(
    name: str,
    text: str,
    cursor: int,
    *,
    width: int,
    height: int,
    scroll: int = 0,
    ascii_only: bool = False,
) -> str:
    """Gate 3 §2.5.2: in-place editing view in the same window.

    The buffer is rendered with an insert-block cursor spliced at the current
    offset; the viewport auto-follows so the cursor line stays visible.
    """
    from .skill_editor import offset_to_line_col, split_lines

    content_rows = max(height - 3, 1)
    raw_lines = split_lines(text)
    line, col = offset_to_line_col(text, cursor)
    # One content row is reserved for the cursor/status line.
    capacity = max(content_rows - 1, 1)
    effective = max(0, min(scroll, max(0, len(raw_lines) - capacity)))
    if line < effective:
        effective = line
    elif line >= effective + capacity:
        effective = max(0, line - capacity + 1)

    visible: list[str] = []
    for index in range(effective, min(effective + capacity, len(raw_lines))):
        row_text = raw_lines[index]
        if index == line:
            col = min(col, len(row_text))
            row_text = row_text[:col] + "█" + row_text[col:]
        visible.append(row_text)
    visible.extend([""] * (capacity - len(visible)))
    visible.append(f"[Line {line + 1}, Col {col + 1} · EDIT · Mouse Scroll]")

    footer = (
        "[Ctrl+S] Save * [Esc] Exit * [Ctrl+O] Open in $EDITOR"
        if ascii_only
        else "[Ctrl+S] Save · [Esc] Discard · [Ctrl+O] Open in $EDITOR"
    )
    return fullscreen_frame(
        f"SKILL DETAIL · EDITING · {name}", visible,
        width=width, height=height, meta="[EDIT]",
        footer=footer, scroll=effective, ascii_only=ascii_only,
    )


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
    detail = next(
        (
            item
            for item in snapshot.equipped + snapshot.parked
            if item.name == detail_name
        ),
        None,
    )
    lines = skill_detail_lines(detail) if detail else skills_lines(snapshot, width, selected)
    if status:
        lines.extend(["", status])

    if detail:
        # Gate 3 §2.5.1: dedicated title + meta; [c] copies the definition.
        footer = (
            "<- Back * [c] Copy All * [Esc/q] Close * ^v Scroll"
            if ascii_only
            else "[←] Back · [c] Copy All · [Esc/q] Close · ↑↓ Scroll"
        )
        return fullscreen_frame(
            f"SKILL DETAIL · {detail.name}", lines, width=width, height=height,
            meta=f"L{detail.level} · {detail.percent}%",
            footer=footer, scroll=scroll, ascii_only=ascii_only,
        )
    footer = (
        "<- Back * [Esc/q] Close * ^v Select * Enter Inspect/Manage * [n] New"
        if ascii_only
        else "[←] Back · [Esc/q] Close · ↑↓ Select · Enter Inspect/Manage · [n] New"
    )

    return fullscreen_frame(
        "SKILLS", lines, width=width, height=height,
        meta=f"[{len(snapshot.equipped) + len(snapshot.parked)} skills]",
        footer=footer, scroll=scroll, ascii_only=ascii_only,
    )


def _spec_left_items(
    snapshot: SkillsSnapshot,
) -> tuple[tuple[CatalogSpecialisation, bool], ...]:
    """Left-panel spec list: active specialisations then vaulted ones (Gate 3 §2.4)."""
    return tuple(
        [(item, True) for item in snapshot.specialisations]
        + [(item, False) for item in snapshot.vaulted_specialisations]
    )


def _spec_member_items(
    snapshot: SkillsSnapshot, spec: CatalogSpecialisation
) -> tuple[SkillItem, ...]:
    """Resolve a specialisation's member names to skill rows, equipped first."""
    all_skills = snapshot.equipped + snapshot.parked
    by_name = {item.name: item for item in all_skills}
    present = [by_name[name] for name in spec.members if name in by_name]
    position = {item.name: index for index, item in enumerate(all_skills)}
    present.sort(
        key=lambda item: (
            0 if item.vault_state == "equipped" else 1,
            position[item.name],
        )
    )
    return tuple(present)


def render_specialisation_management(
    snapshot: SkillsSnapshot,
    *,
    spec_cursor: int,
    member_cursor: int,
    focus: str = "left",
    width: int,
    height: int,
    scroll: int = 0,
    ascii_only: bool = False,
) -> str:
    """Gate 3 §2.4: two-pane specialisation window with live member preview.

    Left pane: active + vaulted specialisations and per-spec stats. Right pane:
    the selected spec's member skills (equipped first), updated live as the
    left cursor moves.
    """
    left_items = _spec_left_items(snapshot)
    if not left_items:
        lines = ["", "(No specialisations yet.)"]
        return fullscreen_frame(
            "SPECIALISATION", lines, width=width, height=height,
            footer="[←] Back · [Esc/q] Close", scroll=scroll, ascii_only=ascii_only,
        )
    total = len(left_items)
    spec, active_flag = left_items[spec_cursor % total]
    members = _spec_member_items(snapshot, spec)
    equipped_count = sum(1 for item in members if item.vault_state == "equipped")

    divider = "|" if ascii_only else "│"
    cursor = 0
    left: list[str] = []
    # Active specialisations are selectable first, then vaulted ones.
    left.extend(["", _section(f"SPECIALISATIONS ({len(snapshot.specialisations)})", 30)])
    for item in snapshot.specialisations:
        marker = "❯ ● " if cursor == spec_cursor % total else "  ○ "
        left.append(f"{marker}{_clip(item.name, 16):<16} L{item.level} {item.percent:>3}%")
        cursor += 1
    vaulted_n = len(snapshot.vaulted_specialisations)
    left.extend(["", _section(f"VAULT ({vaulted_n})", 30)])
    for item in snapshot.vaulted_specialisations:
        marker = "❯ ● " if cursor == spec_cursor % total else "  ○ "
        left.append(f"{marker}{_clip(item.name, 16):<16} [parked]")
        cursor += 1
    if not vaulted_n:
        left.append("(No vaulted specialisations)")
    left.extend(["", _section("STATS", 30)])
    if active_flag:
        left.append(f"Level {spec.level} · {spec.percent}% · {len(members)} member skills")
    else:
        left.append(f"Parked · {len(members)} member skills")
    left.append(f"Active {equipped_count} · Parked {len(members) - equipped_count}")

    # Member rows in the right column, two lines per member (bar below).
    right: list[str] = []
    right.append("")
    right.append(_section(f"MEMBER SKILLS ({len(members)})", 30))
    if not members:
        right.append("(No member skills)")
    for index, item in enumerate(members):
        selected = focus == "right" and index == member_cursor % max(len(members), 1)
        sel = "❯ " if selected else "  "
        tag = "" if item.vault_state == "equipped" else "  [parked]"
        right.append(f"{sel}✓ {_clip(item.name, 15):<15} L{item.level}  {item.percent:>3}%{tag}")
        right.append(f"    {render_bar(item.percent, 10)}")

    lines: list[str] = []
    inner = max(max(20, width - 1) - 6, 16)
    if inner >= 56:
        left_w = max(30, (inner - 3) // 2)
        right_w = max(10, inner - left_w - 3)
        count = max(len(left), len(right))
        for index in range(count):
            a = left[index] if index < len(left) else ""
            b = right[index] if index < len(right) else ""
            lines.append(
                _clip(a, left_w).ljust(left_w) + f" {divider} " + _clip(b, right_w)
            )
    else:
        lines.extend(left)
        lines.append("")
        lines.extend(right)

    title = "SPECIALISATION" if focus == "left" else f"SPECIALISATION · {spec.name}"
    meta = f"L{spec.level} · {spec.percent}%" if active_flag else "parked"
    if focus == "left":
        footer = (
            "<- Back * [Esc/q] Close * ^v Browse * Enter Manage Members"
            if ascii_only
            else "[←] Back · [Esc/q] Close · ↑↓ Browse · Enter Manage Members"
        )
    else:
        footer = (
            "[Enter] Toggle active/parked * [r] Park * <- Back to specs"
            if ascii_only
            else "[Enter] Toggle active/parked · [r] Park · [←] Back to specs"
        )
    return fullscreen_frame(
        title, lines, width=width, height=height,
        meta=meta, footer=footer, scroll=scroll, ascii_only=ascii_only,
    )


def render_spec_member_remove_modal(
    skill_name: str, spec_name: str, *, width: int, ascii_only: bool = False
) -> str:
    """Gate 3 §2.4: confirm dialog for parking (removing from active) a member.

    Membership is domain-derived, so removal parks the skill: it leaves the
    spec's active set and moves to Vault while staying a member of the domain.
    """
    return modal_frame(
        "REMOVE MEMBER",
        [
            "",
            f"Park {skill_name}?",
            f"It is currently an active member of {spec_name}.",
            "It will move to the Vault and no longer count as active.",
            "",
            "[y] Yes · [n] No",
        ],
        width=min(52, width),
        terminal_width=width,
        footer="",
        ascii_only=ascii_only,
    )


def tool_detail_lines(tool: ToolItem) -> list[str]:
    schema = json.dumps(tool.parameters, indent=2, sort_keys=True)
    return [
        "", _section(f"TOOL DETAIL · {tool.name}", 68),
        tool.description,
        "",
        f"Category: {tool.category or 'Unavailable'}",
        f"Safety level: [{tool.safety_level}]",
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
        safety_badge = f"[{tool.safety_level}]"
        if width >= 72:
            lines.append(
                f"{marker} {_clip(tool.name, 19):<19} "
                f"{_clip(tool.category or '—', 13):<13} "
                f"{_clip(safety_badge, 17):<17} "
                f"{tool.dispatch_description or '—'}"
            )
        else:
            lines.append(f"{marker} {_clip(tool.name, 18):<18} {safety_badge}")
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
        "[←] Back · [Esc/q] Close"
        if detail
        else "[←] Back · [Esc/q] Close · ↑↓ Select · Enter Inspect Schema"
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
        footer="[←] Back · [Esc/q] Close · ↑↓ Scroll", scroll=scroll, ascii_only=ascii_only,
    )


THEME_OPTIONS = (
    ("marshmallow", "Clean white & cyan"),
    ("dracula", "Dark vampire neon"),
    ("tokyonight", "Cyberpunk midnight"),
    ("nord", "Arctic cold slate"),
    ("monokai", "Classic pro dark"),
    ("gruvbox", "Warm retro groove"),
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
        footer="[←] Back · [Esc/q] Close · ↑↓ Browse · Enter Select", ascii_only=ascii_only,
    )


def _format_modal_ctx(ctx: int) -> str:
    if ctx >= 1_000_000:
        return f"{ctx // 1_000_000}M"
    return f"{ctx // 1000}k"


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
    if options:
        for index, option in enumerate(options):
            marker = "❯ ●" if index == selected else "  ○"
            is_active = (option.model_id == active_model)
            prov_tag = f"{option.provider_name} · Active" if is_active else option.provider_name
            if terminal_width < 50:
                lines.append(f"{marker} {_clip(option.model_id, 16):<16} {_clip(prov_tag, 14)}")
            else:
                lines.append(f"{marker} {_clip(option.model_id, 24):<24} {prov_tag}")
    else:
        lines.append("No configured providers found.")
        lines.append("Press [a] to add a provider.")

    if active_model and not any(o.model_id == active_model for o in options):
        lines.extend([
            "",
            f"Warning: Active model '{active_model}' has no credential.",
        ])

    lines.extend([
        "",
        "Configured providers only",
    ])

    footer = (
        "<- Back * [Esc/q] Close * ^v Browse * Enter Select\n[a] Add provider * [k] Replace selected provider key"
        if ascii_only
        else "[←] Back · [Esc/q] Close · ↑↓ Browse · Enter Select\n[a] Add provider · [k] Replace selected provider key"
    )
    return modal_frame(
        "CHOOSE ACTIVE MODEL", lines, width=74, terminal_width=terminal_width,
        footer=footer, ascii_only=ascii_only,
    )


def render_auth_modal(
    selected: int,
    terminal_width: int,
    *,
    ascii_only: bool = False,
) -> str:
    choices = (
        ("Add provider", "Connect API keys or custom endpoints"),
        ("Manage providers", "View status, replace or remove stored keys"),
    )
    lines = []
    for index, (title, desc) in enumerate(choices):
        marker = "❯ ●" if index == selected else "  ○"
        lines.append(f"{marker} {_clip(title, 20):<20} {_clip(desc, 38)}")
    footer = (
        "<- Back * [Esc/q] Close * ^v Browse * Enter Select"
        if ascii_only
        else "[←] Back · [Esc/q] Close · ↑↓ Browse · Enter Select"
    )
    return modal_frame(
        "AUTHENTICATION & PROVIDERS", lines, width=68, terminal_width=terminal_width,
        footer=footer, ascii_only=ascii_only,
    )


def render_auth_add_modal(
    presets: Sequence[Any],
    selected: int,
    terminal_width: int,
    *,
    ascii_only: bool = False,
) -> str:
    lines = []
    for index, preset in enumerate(presets):
        marker = "❯ ●" if index == selected else "  ○"
        lines.append(f"{marker} {_clip(preset.name, 18):<18} {_clip(preset.description, 40)}")
    footer = (
        "<- Back * [Esc/q] Close * ^v Browse * Enter Continue"
        if ascii_only
        else "[←] Back · [Esc/q] Close · ↑↓ Browse · Enter Continue"
    )
    return modal_frame(
        "ADD PROVIDER", lines, width=72, terminal_width=terminal_width,
        footer=footer, ascii_only=ascii_only,
    )


def render_auth_manage_modal(
    entries: Sequence[tuple[str, str, str, str]],  # (name, model, status, detail)
    selected: int,
    terminal_width: int,
    status: str = "",
    *,
    ascii_only: bool = False,
) -> str:
    lines = []
    for index, (name, model_info, state_badge, detail) in enumerate(entries):
        marker = "❯ ●" if index == selected else "  ○"
        lines.append(f"{marker} {_clip(name, 16):<16} {_clip(model_info, 20):<20} {state_badge}")
    if not entries:
        lines.append("No providers configured.")
    if selected < len(entries):
        curr = entries[selected]
        if curr[3]:  # info detail (e.g. environment variable notice)
            lines.extend(["", curr[3]])
    if status:
        lines.extend(["", status])
    footer = (
        "<- Back * [Esc/q] Close * ^v Browse * [r] Replace * [d] Forget"
        if ascii_only
        else "[←] Back · [Esc/q] Close · ↑↓ Browse · [r] Replace · [d] Forget"
    )
    return modal_frame(
        "MANAGE PROVIDERS", lines, width=72, terminal_width=terminal_width,
        footer=footer, ascii_only=ascii_only,
    )


def render_auth_custom_wizard_modal(
    step: int,
    wizard_data: dict[str, str],
    current_input: str,
    terminal_width: int,
    status: str = "",
    *,
    ascii_only: bool = False,
) -> str:
    step_titles = (
        "Step 1/5 · Provider Name",
        "Step 2/5 · Base URL",
        "Step 3/5 · Model ID",
        "Step 4/5 · Context Window",
        "Step 5/5 · API Key",
    )
    step_prompts = (
        "Enter a display name (e.g. Local vLLM):",
        "Enter HTTP(S) Base URL (e.g. http://localhost:8000/v1):",
        "Enter Model ID (e.g. mistralai/Mistral-7B-Instruct-v0.3):",
        "Enter context window token limit (e.g. 32768):",
        "Paste API Key (required for OpenAICompatibleClient):",
    )
    lines = [
        step_titles[min(step, len(step_titles) - 1)],
        "",
        step_prompts[min(step, len(step_prompts) - 1)],
        "",
    ]
    if step == 4:  # API key step -> masked
        lines.append(f"> {'•' * len(current_input)}")
    else:
        lines.append(f"> {current_input}")

    if status:
        lines.extend(["", status])
    footer = (
        "<- Back * [Esc/q] Close * Enter Next" if step < 4 else "<- Back * [Esc/q] Close * Enter Save"
        if ascii_only
        else "[←] Back · [Esc/q] Close · Enter Next" if step < 4 else "[←] Back · [Esc/q] Close · Enter Save"
    )
    return modal_frame(
        "CUSTOM ENDPOINT WIZARD", lines, width=74, terminal_width=terminal_width,
        footer=footer, ascii_only=ascii_only,
    )


def render_auth_forget_modal(
    provider_name: str,
    terminal_width: int,
    *,
    ascii_only: bool = False,
) -> str:
    lines = [
        f"Are you sure you want to forget credential for {provider_name}?",
        "",
        "The API key will be deleted from Windows Credential Manager.",
    ]
    footer = (
        "<- Back * [Esc/q] Close * [y] Confirm * [n] Cancel"
        if ascii_only
        else "[←] Back · [Esc/q] Close · [y] Confirm · [n] Cancel"
    )
    return modal_frame(
        "CONFIRM FORGET CREDENTIAL", lines, width=68, terminal_width=terminal_width,
        footer=footer, ascii_only=ascii_only,
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
        footer="[←] Back · [Esc/q] Close · Enter Apply", ascii_only=ascii_only,
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
        footer="[←] Back · [Esc/q] Close · Enter Save", ascii_only=ascii_only,
    )


def render_help_inline(
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render canonical inline /help guide with HOW HUND GROWS frame and open categorized list."""
    frame_width = min(max(width - 2, 34), 72)
    inner = frame_width - 4
    if ascii_only:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    else:
        tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"

    title_text = " HOW HUND GROWS "
    top = tl + h + title_text + h * max(0, frame_width - 3 - len(title_text)) + tr
    base_stats_lines = [
        "CLR  Clarity      Clear, focused and usable outcomes",
        "PRC  Precision    Correct work verified against evidence",
        "EFF  Efficiency   Useful results without avoidable waste",
        "END  Endurance    Verified completion of sustained tasks",
        "MAS  Mastery      Breadth and proven reusable capability",
        "",
        "Stats change only from recorded outcomes. Use /stats for",
        "evidence, trends and progression details.",
    ]
    frame_rows = [f"{v} {_clip(line, inner).ljust(inner)} {v}" for line in base_stats_lines]
    bottom = bl + h * (frame_width - 2) + br
    output_lines: list[str] = [top, *frame_rows, bottom, ""]

    categorized = get_categorized_commands()
    for category, specs in categorized.items():
        output_lines.append(f"  {category}")
        for spec in specs:
            name_str = f"/{spec.name}"
            if width >= 60:
                output_lines.append(f"  {name_str:<14} {spec.short_description}")
            else:
                output_lines.append(f"  {name_str}")
                output_lines.append(f"    {spec.short_description}")
        output_lines.append("")

    tip = (
        "  Type a command for details * Tab completes commands"
        if ascii_only
        else "  Type a command for details · Tab completes commands"
    )
    output_lines.append(tip)
    return "\n".join(output_lines)


def render_system(
    snapshot: EnvironmentSnapshot,
    width: int = 80,
    height: int = 24,
    *,
    ascii_only: bool = False,
    changes_only: bool = False,
) -> str:
    """Render known machine and environment snapshot fullscreen screen."""
    lines: list[str] = []
    if changes_only:
        lines.append(_section("ENVIRONMENT CHANGES", width - 6))
        lines.append("")
        for ch in snapshot.changes_since(None):
            lines.append(f"  • {ch}")
        lines.append("")
    else:
        lines.append(_section("HARDWARE", width - 6))
        lines.append(f"CPU      {snapshot.processor}  {snapshot.cpu_count} cores")
        gpu_name = snapshot.gpu_model or "Integrated"
        vram_info = f"{snapshot.gpu_vram_mb} MiB dedicated" if snapshot.gpu_vram_mb else "Integrated/shared"
        lines.append(f"GPU      {gpu_name}")
        lines.append(f"RAM      {snapshot.total_ram_gb:.1f} GiB total")
        lines.append(f"VRAM     {vram_info}")
        lines.append("")

        lines.append(_section("STORAGE", width - 6))
        for vol in snapshot.volumes:
            lines.append(f"{vol.mount_point:<8} {vol.total_gb:.1f} GiB total  {vol.free_gb:.1f} GiB free")
        lines.append("")

        lines.append(_section("ENVIRONMENT", width - 6))
        os_info = snapshot.os_caption or f"{snapshot.os} {snapshot.os_version}"
        tools = [t for t, ok in [("PowerShell", snapshot.has_powershell), ("Python", snapshot.has_python), ("uv", snapshot.has_uv), ("Git", snapshot.has_git), ("Node", snapshot.has_node)] if ok]
        tools_str = " · ".join(tools) if tools else "Standard runtimes"
        lines.append(f"{os_info} · {snapshot.shell}")
        lines.append(f"{tools_str}")

    footer = (
        "<- Back * [Esc/q] Close * [r] Refresh"
        if ascii_only
        else "[←] Back · [Esc/q] Close · [r] Refresh"
    )
    meta = f"observed {snapshot.observation_time_display}"
    return fullscreen_frame(
        "SYSTEM",
        lines,
        width=width,
        height=height,
        footer=footer,
        meta=meta,
        ascii_only=ascii_only,
    )


def render_doctor(
    report: DoctorReport,
    width: int = 80,
    height: int = 24,
    *,
    ascii_only: bool = False,
    review_fixes: bool = False,
) -> str:
    """Render structured read-only diagnostics report fullscreen screen."""
    lines: list[str] = [""]
    for c in report.checks:
        if ascii_only:
            glyph = "[OK]" if c.status == "pass" else ("[X]" if c.status == "fail" else "[!]")
        else:
            glyph = "✓" if c.status == "pass" else ("✗" if c.status == "fail" else "!")
        lines.append(f"  {glyph}  {c.name:<26} {c.detail}")

    lines.append("")
    lines.append(f"  {report.summary_text}")
    lines.append("")

    if review_fixes and report.fix_plan:
        lines.append(_section("RECOMMENDED REPAIR ACTIONS (READ-ONLY)", width - 6))
        lines.append("")
        for item in report.fix_plan:
            lines.append(f"  • {item}")
        lines.append("")
        lines.append("  (Execute proposed commands individually to apply fixes)")

    footer = (
        "<- Back * [Esc/q] Close * [f] Review fixes"
        if ascii_only
        else "[←] Back · [Esc/q] Close · [f] Review fixes"
    )
    return fullscreen_frame(
        "DOCTOR",
        lines,
        width=width,
        height=height,
        footer=footer,
        ascii_only=ascii_only,
    )

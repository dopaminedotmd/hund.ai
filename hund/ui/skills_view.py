"""Skills View — renders the 2-layer fullscreen skills panel & detailed inspection cards.

Adheres strictly to TUI_FACIT.md §12, PLAN_2026-08-23.md §15, and PLAN_2026-08-24_learning_engine.md §8.
Uses identical border and row geometry to build_startup_banner in render.py.
"""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Optional

from hund.domains.xp import get_xp
from hund.skills.lifecycle import (
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_PROVEN,
    SKILL_STATUS_SANDBOX_TESTED,
)
from hund.skills.loader import load_builtins
from hund.skills.model import Skill
from hund.skills.vault import SkillVault
from hund.stats.tiers import render_bar


def _truncate_pad(text: str, length: int) -> str:
    if len(text) > length:
        return text[: length - 1] + "…"
    return text.ljust(length)


def render_skills_panel(
    rt: Any = None,
    vault: Optional[SkillVault] = None,
    width: int | None = None,
    db_path: Path | str | None = None,
) -> str:
    """Render the 2-layer fullscreen skills panel per TUI_FACIT.md §12.

    Top layer: Motor skills (11 builtins, immutable, always on).
    Middle layer: Equipped domain skills with XP bars, tiers, and levels.
    Bottom layer: Vaulted/parked skills with slot capacity.
    """
    term_cols = shutil.get_terminal_size((80, 24)).columns
    W = max(width if width is not None else min(term_cols, 80), 40)
    inner_w = W - 6  # text space inside '║  ...  ║'

    if vault is None:
        vault = SkillVault()

    # 1. Fetch builtins (Motor skills)
    motor_skills = load_builtins()
    motor_names = [s.name for s in motor_skills]

    # 2. Fetch equipped & vaulted domain skills
    if rt and hasattr(rt, "skills") and rt.skills is not None:
        active_skills = [s for s in rt.skills if s.name not in motor_names]
    else:
        active_skills = vault.get_active_skills()

    vaulted_skills = vault.list_vaulted()
    max_slots = vault.max_active
    slot_info = f"[{len(active_skills)}/{max_slots} slots]"

    top = "╔" + "═" * (W - 2) + "╗"
    bottom = "╚" + "═" * (W - 2) + "╝"
    empty = "║" + " " * (W - 2) + "║"

    def row(content: str) -> str:
        c = content[: W - 6]
        return "║  " + c.ljust(W - 6) + "  ║"

    lines: list[str] = [top, empty]

    # Title header line
    header_left = "SKILLS"
    header_line = f"{header_left}{' ' * max(inner_w - len(header_left) - len(slot_info), 2)}{slot_info}"
    lines.append(row(header_line))
    lines.append(empty)

    # Section 1: Motor Skills (Always on, immutable)
    sec1_title = "── MOTOR SKILLS · always on · immutable "
    sec1_dashes = inner_w - len(sec1_title)
    lines.append(row(f"{sec1_title}{'─' * max(sec1_dashes, 2)}"))

    # Format motor skills in 2 columns
    col_w = (inner_w - 2) // 2
    for i in range(0, len(motor_names), 2):
        col1 = motor_names[i]
        col2 = motor_names[i + 1] if (i + 1) < len(motor_names) else ""
        row_str = f"{_truncate_pad(col1, col_w)}  {_truncate_pad(col2, col_w)}"
        lines.append(row(row_str))

    lines.append(empty)

    # Section 2: Domain Skills (Equipped)
    sec2_title = "── DOMAIN SKILLS · equipped "
    sec2_dashes = inner_w - len(sec2_title)
    lines.append(row(f"{sec2_title}{'─' * max(sec2_dashes, 2)}"))

    if not active_skills:
        lines.append(row("(no domain skills equipped — use /skills equip <name>)"))
    else:
        bar_w = 8 if W < 80 else 10
        for s in active_skills:
            dom = s.domain or s.name
            xp_info = get_xp(dom, db_path=db_path)
            tier = xp_info["tier"]
            lvl = xp_info["level"]
            pct = xp_info["progress_pct"]
            bar = render_bar(pct, width=bar_w)

            # Format row
            name_col = _truncate_pad(s.name, 18)
            row_str = f"{name_col} {bar}  {tier:<8} {pct:>3}%  (Lvl {lvl})"
            lines.append(row(row_str))

    lines.append(empty)

    # Section 3: Vault (Parked)
    sec3_title = "── VAULT · parked "
    sec3_dashes = inner_w - len(sec3_title)
    lines.append(row(f"{sec3_title}{'─' * max(sec3_dashes, 2)}"))

    if not vaulted_skills:
        lines.append(row("(vault is empty — all custom skills equipped)"))
    else:
        for s in vaulted_skills:
            dom = s.domain or s.name
            xp_info = get_xp(dom, db_path=db_path)
            tier = xp_info["tier"]
            lvl = xp_info["level"]
            name_col = _truncate_pad(s.name, 18)
            row_str = f"{name_col} {tier:<8} (Lvl {lvl})                       [equip]"
            lines.append(row(row_str))

    lines.append(empty)

    # Footer navigation / commands
    footer_text = "commands: /skills equip <name> · /skills park <name> · /skills info <name>"
    lines.append(row(footer_text))
    lines.append(bottom)

    return "\n".join(lines)


def render_skill_detail(
    skill_name: str,
    rt: Any = None,
    vault: Optional[SkillVault] = None,
    width: int | None = None,
    db_path: Path | str | None = None,
) -> str:
    """Render detailed inspection view for a single skill."""
    term_cols = shutil.get_terminal_size((80, 24)).columns
    W = max(width if width is not None else min(term_cols, 80), 40)
    if vault is None:
        vault = SkillVault()

    # Search for skill in builtins, active, and vaulted
    motor_skills = load_builtins()
    motor_map = {s.name: s for s in motor_skills}

    all_skills = vault.get_all_skills()
    skill_map = {s.name: s for s in all_skills}

    skill: Optional[Skill] = motor_map.get(skill_name) or skill_map.get(skill_name)

    if not skill:
        # Check by domain match or partial name
        for s in list(motor_map.values()) + all_skills:
            if s.domain == skill_name or skill_name.lower() in s.name.lower():
                skill = s
                break

    if not skill:
        return f"Skill '{skill_name}' not found."

    is_motor = skill.name in motor_map
    dom = skill.domain or skill.name
    xp_info = get_xp(dom, db_path=db_path)

    top = "╔" + "═" * (W - 2) + "╗"
    bottom = "╚" + "═" * (W - 2) + "╝"
    empty = "║" + " " * (W - 2) + "║"

    def row(content: str) -> str:
        c = content[: W - 6]
        return "║  " + c.ljust(W - 6) + "  ║"

    lines: list[str] = [top, empty]
    lines.append(row(f"SKILL DETAIL: {skill.name}"))
    lines.append(empty)

    def _add_field(label: str, val: str) -> None:
        lines.append(row(f"{label:<16}: {val}"))

    _add_field("Type", "Motor Instinct (Immutable)" if is_motor else "Domain Skill")
    _add_field("Domain", skill.domain or "core")
    _add_field("Status", skill.status or ("active" if is_motor else "vaulted"))
    _add_field("Safety Level", str(getattr(skill, "safety_level", "low")))

    # XP & Progression
    bar = render_bar(xp_info["progress_pct"], width=12)
    xp_str = f"{bar}  {xp_info['tier']} ({xp_info['progress_pct']}%) · {xp_info['xp']} XP Total (Level {xp_info['level']})"
    _add_field("Mastery / XP", xp_str)

    # Dependencies & Tools
    tools = getattr(skill, "tools", []) or []
    _add_field("Allowed Tools", ", ".join(tools) if tools else "(none - pure instruction)")

    deps = getattr(skill, "deps", {}) or {}
    _add_field("Dependencies", str(deps) if deps else "(no external deps)")

    lines.append(empty)

    # When to use / trigger
    when = (getattr(skill, "when_to_use", "") or "").strip()
    if when:
        _add_field("When to use", when)

    lines.append(empty)
    lines.append(bottom)

    return "\n".join(lines)

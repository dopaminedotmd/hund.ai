"""Pure responsive renderer and focus contract for inline Skill Seed proposals."""
from __future__ import annotations

from ..learning.skill_proposals import SkillSeed
from .unicode_cells import cell_width, slice_cells, wrap_cells


def skill_seed_shortcut_enabled(*, focused: bool, input_text: str) -> bool:
    return focused and not input_text


def _fit(line: str, width: int) -> str:
    return slice_cells(line, max(width, 1))[0] if cell_width(line) > width else line


def render_skill_seed(
    seed: SkillSeed, width: int, *, ascii_only: bool = False
) -> str:
    """Render one quiet inline artifact without borders, IDs or confidence."""
    width = max(24, width)
    compact = width < 60
    indent = "  " if compact else "        "
    rail = "|" if ascii_only else "│"
    end = "`" if ascii_only else "└"
    diamond = "+" if ascii_only else "◆"
    gap = " " if compact else "  "
    prefix = f"{indent}{rail}{gap}"
    body_width = max(12, width - cell_width(prefix))
    lines = [f"{indent}{diamond}{gap}SKILL SEED"]

    def add(text: str = "") -> None:
        wrapped = wrap_cells(text, body_width) if text else [""]
        lines.extend(prefix + part for part in wrapped)

    add(seed.display_name)
    if compact:
        add(seed.evidence_summary)
        research = "research after approval" if seed.research_after_accept else "no web research"
        add(f"{seed.scope.title()} skill · {research}")
    else:
        add(seed.outcome)
        add(seed.evidence_summary)
        add(seed.improvement)
        add("")
        research = "Research after approval" if seed.research_after_accept else "No web research"
        add(f"Scope  {seed.scope.title()}     {research}")
    add("Starts at 0 XP")
    if seed.changed_summary:
        add(f"Changed: {seed.changed_summary}")
    action_text = (
        "[a] Accept · [e] Edit · [d] Decline"
        if compact
        else "[a] Accept     [e] Edit     [d] Decline"
    )
    lines.append(_fit(f"{indent}{end}{gap}{action_text}", width))
    return "\n".join(_fit(line, width) for line in lines)

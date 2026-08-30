"""Read-only display projections backed only by audited Skill XP."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..domains.xp import calculate_level_and_tier
from .model import Skill
from .proficiency import read_skill_xp_records


@dataclass(frozen=True)
class SkillXPProjectionRow:
    """A display-ready atomic-skill proficiency row from the Skill-XP ledger."""

    capability_id: str
    display_name: str
    total_xp: int
    level: int
    tier: str
    progress_percent: int
    xp_into_level: int
    xp_to_next_level: int
    last_used_at: str | None


def project_active_skill_xp(
    skills: Iterable[Skill],
    *,
    db_path: Path | str | None = None,
    limit: int | None = None,
) -> tuple[SkillXPProjectionRow, ...]:
    """Project eligible equipped atomic skills without mutating Skill-XP state."""
    eligible_skills = tuple(
        skill
        for skill in skills
        if skill.lifecycle_state in {"active", "proven"}
        and skill.vault_state == "equipped"
    )
    records = read_skill_xp_records(
        {skill.capability_id for skill in eligible_skills},
        db_path=db_path,
    )
    rows: list[SkillXPProjectionRow] = []
    for skill in eligible_skills:
        record = records.get(skill.capability_id)
        total_xp = record.xp if record is not None else 0
        level, tier, progress_percent, xp_into_level, xp_to_next_level = (
            calculate_level_and_tier(total_xp)
        )
        rows.append(
            SkillXPProjectionRow(
                capability_id=skill.capability_id,
                display_name=skill.name,
                total_xp=total_xp,
                level=level,
                tier=tier,
                progress_percent=progress_percent,
                xp_into_level=xp_into_level,
                xp_to_next_level=xp_to_next_level,
                last_used_at=record.last_used_at if record is not None else None,
            )
        )

    rows.sort(key=lambda row: (-row.total_xp, _descending_timestamp(row.last_used_at), row.display_name.casefold()))
    if limit is not None:
        rows = rows[: max(limit, 0)]
    return tuple(rows)


def _descending_timestamp(timestamp: str | None) -> float:
    """Return an ascending-sort key that ranks valid timestamps newest first."""
    if timestamp is None:
        return float("inf")
    try:
        return -datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")

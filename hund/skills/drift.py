"""Skill drift monitoring, claim freshness, quarantine, and version rollback."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional, Set

from .lifecycle import SKILL_STATUS_QUARANTINED
from .loader import _read_skill_file
from .model import Skill
from .proficiency import SkillXPRecord
from .storage import SkillStorage


@dataclass(frozen=True)
class DriftReport:
    is_stale: bool
    revalidation_required: bool
    quarantine_recommended: bool
    reason: str


def evaluate_skill_health_and_drift(
    skill: Skill,
    proficiency_record: SkillXPRecord,
    registered_tools: Set[str],
    now: Optional[datetime] = None,
) -> DriftReport:
    """Evaluate skill for environmental tool drift, health degradation, or freshness staleness."""
    # 1. Check tool availability
    missing_tools = [t for t in skill.required_tools if t not in registered_tools]
    if missing_tools:
        return DriftReport(
            is_stale=False,
            revalidation_required=True,
            quarantine_recommended=False,
            reason=f"Missing tool dependencies: {', '.join(missing_tools)}",
        )

    # 2. Check health degradation
    if proficiency_record.use_count >= 3 and proficiency_record.health < 0.4:
        return DriftReport(
            is_stale=False,
            revalidation_required=True,
            quarantine_recommended=True,
            reason=f"Severe failure rate detected: health={proficiency_record.health:.2f}",
        )

    if skill.revalidation_required:
        return DriftReport(
            is_stale=False,
            revalidation_required=True,
            quarantine_recommended=False,
            reason="Skill marked for revalidation",
        )

    return DriftReport(
        is_stale=False,
        revalidation_required=False,
        quarantine_recommended=False,
        reason="Skill healthy and current",
    )


def quarantine_skill(
    name: str,
    *,
    home: Optional[Path] = None,
    reason: str = "",
    scope: str = "global",
    workspace_path: Optional[Path] = None,
) -> Optional[Skill]:
    """Quarantine a failing or unsafe skill, transitioning it into the vault."""
    storage = SkillStorage(home=home)
    workspace_key = workspace_path.name if workspace_path and scope == "project" else "global"
    path = storage.get_canonical_path(name, scope, workspace_key=workspace_key)
    if not path.exists():
        return None

    existing = _read_skill_file(path)
    if existing is None:
        return None

    data = existing.to_dict()
    data["lifecycle_state"] = SKILL_STATUS_QUARANTINED
    data["status"] = SKILL_STATUS_QUARANTINED
    data["vault_state"] = "vaulted"
    data["revalidation_required"] = True
    if reason:
        limitations = list(data.get("limitations", []))
        limitations.append(f"Quarantined: {reason}")
        data["limitations"] = limitations

    updated = Skill.from_dict(data)
    storage.write_canonical_atomic(updated, workspace_key=workspace_key)
    return updated


def rollback_skill_version(
    name: str,
    *,
    home: Optional[Path] = None,
    target_version: Optional[str] = None,
    scope: str = "global",
    workspace_path: Optional[Path] = None,
) -> Optional[Skill]:
    """Roll back a skill to its previous historical snapshot."""
    storage = SkillStorage(home=home)
    workspace_key = workspace_path.name if workspace_path and scope == "project" else "global"
    ok, _, restored_skill = storage.rollback_skill(
        name,
        workspace_key=workspace_key,
        target_version=target_version,
        scope=scope,
    )
    return restored_skill if ok else None

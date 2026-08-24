"""Reflection & Learning — generates post-turn learning insights and XP bar.

Adheres strictly to TUI_FACIT.md §8 and PLAN_2026-08-23.md §9.
Max 3 reflection lines per turn.
Priority: level-up > domain-lock > gap-event > xp-gain > tier-up > stat-up > knowledge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from hund.domains.confidence import list_confidence
from hund.domains.xp import get_xp, list_all_xp
from hund.learning.observer import list_gap_events
from hund.learning.redactor import redact_text
from hund.stats import compute_all
from hund.stats.tiers import render_bar


@dataclass
class TurnSnapshot:
    """Snapshot of leveling, confidence, gaps, and stats at turn start."""
    domain_xp: dict[str, dict[str, Any]] = field(default_factory=dict)
    confidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    gap_ids: set[str] = field(default_factory=set)
    base_stats: dict[str, str] = field(default_factory=dict)


def take_snapshot(db_path=None) -> TurnSnapshot:
    """Capture turn start state."""
    # 1. Domain XP
    xp_map: dict[str, dict[str, Any]] = {}
    try:
        for item in list_all_xp(db_path=db_path):
            xp_map[item["domain"]] = item
    except Exception:
        pass

    # 2. Domain Confidence
    conf_map: dict[str, dict[str, Any]] = {}
    try:
        for item in list_confidence(db_path=db_path):
            conf_map[item["domain"]] = item
    except Exception:
        pass

    # 3. Gap events
    gap_ids: set[str] = set()
    try:
        for row in list_gap_events():
            gap_ids.add(row[0])  # id prefix
    except Exception:
        pass

    # 4. Base stats
    stat_map: dict[str, str] = {}
    try:
        stats = compute_all()
        for k, v in stats.items():
            if isinstance(v, dict):
                stat_map[k] = v.get("tier", "—")
    except Exception:
        pass

    return TurnSnapshot(
        domain_xp=xp_map,
        confidence=conf_map,
        gap_ids=gap_ids,
        base_stats=stat_map,
    )


def compute_reflections(
    snapshot: TurnSnapshot,
    db_path=None,
    max_lines: int = 3,
) -> list[str]:
    """Compute post-turn reflection lines based on deltas from snapshot.

    Returns formatted lines with '  · ' prefix.
    Max 3 lines prioritized:
      1. Level-up (⟶ level up!)
      2. Domain-lock (locked {domain} as a specialization)
      3. Gap-event (learned: {redacted_symptom})
      4. XP-gain ({domain} ████░░ +X XP)
      5. Tier-up in confidence (getting confident in {domain})
      6. Stat improved ({stat} improved → {tier})
    """
    level_ups: list[str] = []
    domain_locks: list[str] = []
    gap_events: list[str] = []
    xp_gains: list[str] = []
    confidence_tier_ups: list[str] = []
    stat_ups: list[str] = []

    # 1. Check Domain XP & Level ups
    current_xp = {item["domain"]: item for item in list_all_xp(db_path=db_path)}
    for domain, curr in current_xp.items():
        prev = snapshot.domain_xp.get(domain)
        old_xp = prev["xp"] if prev else 0
        old_level = prev["level"] if prev else 1

        new_xp = curr["xp"]
        new_level = curr["level"]
        new_tier = curr["tier"]
        new_pct = curr["progress_pct"]

        if new_level > old_level:
            level_ups.append(f"{domain} ⟶ level up! ({new_tier})")

        if new_xp > old_xp:
            gain = new_xp - old_xp
            bar = render_bar(new_pct, width=14)
            xp_gains.append(f"{domain:<18} {bar}   +{gain} XP")

    # 2. Check Domain Confidence & Locks
    current_conf = {item["domain"]: item for item in list_confidence(db_path=db_path)}
    for domain, curr in current_conf.items():
        prev = snapshot.confidence.get(domain)
        old_lock = prev.get("is_lockable", False) if prev else False
        old_tier = prev.get("confidence_tier", "candidate") if prev else "candidate"

        new_lock = curr.get("is_lockable", False)
        new_tier = curr.get("confidence_tier", "candidate")

        if new_lock and not old_lock:
            domain_locks.append(f"locked {domain} as a specialization")
        elif new_tier in ("confident", "active") and old_tier == "candidate":
            confidence_tier_ups.append(f"getting confident in {domain}")

    # 3. Check new Gap Events (Privacy: redact symptom)
    try:
        for row in list_gap_events():
            gid, _, domain, symptom, _ = row
            if gid not in snapshot.gap_ids:
                clean_symptom = redact_text(symptom).text.strip()
                if len(clean_symptom) > 45:
                    clean_symptom = clean_symptom[:42] + "..."
                gap_events.append(f"learned: {clean_symptom}")
    except Exception:
        pass

    # 4. Check Base Stats tier upgrades
    try:
        curr_stats = compute_all()
        for k, v in curr_stats.items():
            if isinstance(v, dict):
                old_tier = snapshot.base_stats.get(k, "—")
                new_tier = v.get("tier", "—")
                if old_tier != "—" and new_tier != "—" and old_tier != new_tier:
                    stat_ups.append(f"{k} improved → {new_tier}")
    except Exception:
        pass

    # Assemble in priority order
    candidates: list[str] = (
        level_ups
        + domain_locks
        + gap_events
        + xp_gains
        + confidence_tier_ups
        + stat_ups
    )

    selected = candidates[:max_lines]
    return [f"  · {line}" for line in selected]

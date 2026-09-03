"""Reflection & Learning — generates post-turn deterministic learning insights and XP bar.

Adheres strictly to TUI_FACIT.md §8, PLAN_2026-08-23.md §9, and PLAN_2026-08-24_learning_engine.md §8, §11.
Max 3 reflection lines per turn.
NEVER generates pseudo-introspection or hallucinated thoughts; reflects 100% deterministic state deltas.
Priority:
  1. level-up (⟶ level up!)
  2. validated-rule (validated rule in {domain} (+8 XP))
  3. memory-update (remembered/corrected preference: {summary})
  4. domain-lock (locked {domain} as a specialization)
  5. xp-gain ({domain} ████░░ +X XP)
  6. discovered-rule (discovered rule in {domain})
  7. confidence-tier-up (getting confident in {domain})
  8. stat-up ({stat} improved → {tier})
  9. gap-event (learned: {symptom})
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hund.domains.confidence import list_confidence
from hund.domains.xp import list_all_xp, xp_events_since
from hund.learning.observer import list_gap_events
from hund.learning.redactor import redact_text
from hund.paths import memory_db_path as default_memory_db_path
from hund.stats import compute_all
from hund.stats.tiers import render_bar
from hund.store.sqlite import connect


@dataclass
class TurnSnapshot:
    """Snapshot of leveling, confidence, knowledge, memory, gaps, and stats at turn start."""
    domain_xp: dict[str, dict[str, Any]] = field(default_factory=dict)
    confidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    gap_ids: set[str] = field(default_factory=set)
    base_stats: dict[str, str] = field(default_factory=dict)
    knowledge_audit_count: int = 0
    memory_audit_count: int = 0
    captured_at: str = ""  # agyC/1: ISO-timestamp när snapshotet togs (XP-attribution)


def _get_knowledge_audit_count(home: Optional[Path] = None, db_path: Path | str | None = None) -> int:
    try:
        k_db = (home / "knowledge" / "knowledge.db") if home else db_path
        if k_db and Path(k_db).exists():
            conn = connect(Path(k_db))
            row = conn.execute("SELECT COUNT(*) FROM knowledge_audit").fetchone()
            conn.close()
            return row[0] if row else 0
    except Exception:
        pass
    return 0


def _get_memory_audit_count(home: Optional[Path] = None) -> int:
    try:
        m_db = (home / "memory" / "memory.db") if home else default_memory_db_path()
        if m_db and Path(m_db).exists():
            conn = connect(Path(m_db))
            row = conn.execute("SELECT COUNT(*) FROM memory_audit").fetchone()
            conn.close()
            return row[0] if row else 0
    except Exception:
        pass
    return 0


def take_snapshot(home: Optional[Path] = None, db_path: Path | str | None = None) -> TurnSnapshot:
    """Capture turn start state across all learning subsystems."""
    # 1. Domain XP
    xp_map: dict[str, dict[str, Any]] = {}
    try:
        h_db = (home / "hund.db") if home else db_path
        for item in list_all_xp(db_path=h_db):
            xp_map[item["domain"]] = item
    except Exception:
        pass

    # 2. Domain Confidence
    conf_map: dict[str, dict[str, Any]] = {}
    try:
        h_db = (home / "hund.db") if home else db_path
        for item in list_confidence(db_path=h_db):
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
        stats = compute_all(home=home)
        for k, v in stats.items():
            if isinstance(v, dict):
                stat_map[k] = v.get("tier", "—")
    except Exception:
        pass

    # 5. Knowledge & Memory audit counts
    k_count = _get_knowledge_audit_count(home, db_path)
    m_count = _get_memory_audit_count(home)

    return TurnSnapshot(
        domain_xp=xp_map,
        confidence=conf_map,
        gap_ids=gap_ids,
        base_stats=stat_map,
        knowledge_audit_count=k_count,
        memory_audit_count=m_count,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def compute_reflections(
    snapshot: TurnSnapshot,
    home: Optional[Path] = None,
    db_path: Path | str | None = None,
    max_lines: int = 3,
) -> list[str]:
    """Compute post-turn reflection lines based on deltas from snapshot.

    Returns formatted lines with '  · ' prefix.
    Max 3 lines prioritized deterministically.
    """
    level_ups: list[str] = []
    validated_rules: list[str] = []
    remembered_memories: list[str] = []
    domain_locks: list[str] = []
    xp_gains: list[str] = []
    discovered_rules: list[str] = []
    confidence_tier_ups: list[str] = []
    stat_ups: list[str] = []
    gap_events: list[str] = []

    h_db = (home / "hund.db") if home else db_path

    # 1. Check Domain XP & Level ups — agyC/1 (Spår 14): gains are attributed
    # via audit events since the snapshot, never raw table deltas. A domain
    # whose table grew without any event is shown as external/unattributed.
    current_xp = {item["domain"]: item for item in list_all_xp(db_path=h_db)}
    event_gains = xp_events_since(db_path=h_db, since_iso=snapshot.captured_at or None)
    grown_domains = {
        d
        for d, curr in current_xp.items()
        if snapshot.domain_xp.get(d, {}).get("xp", 0) < curr["xp"]
    }
    external_only = sorted(grown_domains - set(event_gains))
    for domain, curr in current_xp.items():
        gain = event_gains.get(domain, 0)
        if gain <= 0:
            continue
        prev = snapshot.domain_xp.get(domain)
        old_xp = prev["xp"] if prev else 0
        old_level = prev["level"] if prev else 1

        new_level = curr["level"]
        new_tier = curr["tier"]
        new_pct = curr["progress_pct"]

        if new_level > old_level:
            level_ups.append(f"{domain} ⟶ level up! ({new_tier})")

        bar = render_bar(new_pct, width=14)
        xp_gains.append(f"{domain:<18} {bar}   +{gain} XP")

    for domain in external_only:
        xp_gains.append(f"{domain:<18} external/unattributed change")

    # 2. Check Knowledge Audit entries
    try:
        k_db = (home / "knowledge" / "knowledge.db") if home else db_path
        if k_db and Path(k_db).exists():
            conn = connect(Path(k_db))
            rows = conn.execute(
                """SELECT k.domain, a.action, a.new_status, a.reason
                   FROM knowledge_audit a
                   LEFT JOIN knowledge_units k ON a.unit_id = k.id
                   ORDER BY a.rowid ASC"""
            ).fetchall()
            conn.close()

            new_entries = rows[snapshot.knowledge_audit_count :]
            for dom, action, new_status, reason in new_entries:
                dom_name = dom or "core"
                if action == "promote" and new_status == "validated":
                    validated_rules.append(f"validated rule in {dom_name} (+8 XP)")
                elif action in ("create", "insert"):
                    discovered_rules.append(f"discovered rule in {dom_name}")
                elif action in ("deprecate", "degrade"):
                    discovered_rules.append(f"deprecated rule in {dom_name}")
    except Exception:
        pass

    # 3. Check Memory Audit entries
    try:
        m_db = (home / "memory" / "memory.db") if home else default_memory_db_path()
        if m_db and Path(m_db).exists():
            conn = connect(Path(m_db))
            rows = conn.execute(
                """SELECT action, new_value, reason FROM memory_audit
                   ORDER BY rowid ASC"""
            ).fetchall()
            conn.close()

            new_entries = rows[snapshot.memory_audit_count :]
            for action, new_val, reason in new_entries:
                clean_text = redact_text(new_val).text.strip()
                if len(clean_text) > 40:
                    clean_text = clean_text[:37] + "..."
                if action == "supersede":
                    remembered_memories.append(f"corrected preference: {clean_text}")
                elif action in ("insert", "create", "promote"):
                    remembered_memories.append(f"remembered preference: {clean_text}")
    except Exception:
        pass

    # 4. Check Domain Confidence & Locks
    current_conf = {item["domain"]: item for item in list_confidence(db_path=h_db)}
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

    # 5. Check new Gap Events (Privacy: redact symptom)
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

    # 6. Check Base Stats tier upgrades
    try:
        curr_stats = compute_all(home=home)
        for k, v in curr_stats.items():
            if isinstance(v, dict):
                old_tier = snapshot.base_stats.get(k, "—")
                new_tier = v.get("tier", "—")
                if old_tier != "—" and new_tier != "—" and old_tier != new_tier:
                    stat_ups.append(f"{k} improved → {new_tier}")
    except Exception:
        pass

    # Assemble in deterministic priority order
    candidates: list[str] = (
        level_ups
        + validated_rules
        + remembered_memories
        + domain_locks
        + xp_gains
        + discovered_rules
        + confidence_tier_ups
        + stat_ups
        + gap_events
    )

    selected = candidates[:max_lines]
    return [f"  · {line}" for line in selected]

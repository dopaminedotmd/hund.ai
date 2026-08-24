"""Domain XP v2 — knowledge-driven XP engine, deterministic rewards, and audit trail per domain."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Optional
import uuid

from hund.stats.tiers import TIERS, render_bar
from hund.store.sqlite import connect

XP_TABLE = "domain_xp"
XP_EVENTS_TABLE = "domain_xp_events"

CURRENT_XP_ALGORITHM = "v2.0"

# Event types and reward weights (§6)
EVENT_DISCOVERY = "discovery"
EVENT_SAME_TASK_REUSE = "same_task_reuse"
EVENT_CROSS_SESSION_REUSE = "cross_session_reuse"
EVENT_VALIDATION_PROMOTION = "validation_promotion"
EVENT_MANUAL_ADJUST = "manual_adjust"

XP_AMOUNTS: dict[str, int] = {
    EVENT_DISCOVERY: 1,
    EVENT_SAME_TASK_REUSE: 3,
    EVENT_CROSS_SESSION_REUSE: 5,
    EVENT_VALIDATION_PROMOTION: 8,
    EVENT_MANUAL_ADJUST: 0,
}


def _ensure_table(db_path=None) -> None:
    conn = connect(db_path)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {XP_TABLE} (
            domain TEXT PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            tier TEXT DEFAULT 'Novice'
        )"""
    )

    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {XP_EVENTS_TABLE} (
            event_id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            unit_id TEXT,
            xp_amount INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            task_id TEXT,
            session_id TEXT,
            evidence_id TEXT,
            xp_algorithm TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )"""
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_xp_events_domain ON {XP_EVENTS_TABLE}(domain)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_xp_events_unit ON {XP_EVENTS_TABLE}(unit_id)")
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({XP_EVENTS_TABLE})")}
    if "evidence_id" not in columns:
        conn.execute(f"ALTER TABLE {XP_EVENTS_TABLE} ADD COLUMN evidence_id TEXT")

    conn.commit()
    conn.close()


def xp_required(level: int) -> int:
    """XP required to advance from level to level+1.

    Formula: 50 * 2**(level - 1)
    Level 1: 50
    Level 2: 100
    Level 3: 200
    Level 4: 400
    Level 5: 800
    Level 6+: 800
    """
    if level < 1:
        level = 1
    if level <= 5:
        return 50 * (2 ** (level - 1))
    return 800


# Cumulative thresholds to REACH level:
# Level 1: 0 (Novice)
# Level 2: 50 (Apprentice)
# Level 3: 150 (Adept)
# Level 4: 350 (Expert)
# Level 5: 750 (Master)
# Level 6: 1550 (Grandmaster I)
# Level 7: 2350 (Grandmaster II)
# Level 8: 3150 (Grandmaster III - cap)
CUMULATIVE_THRESHOLDS = [0, 50, 150, 350, 750, 1550, 2350, 3150]


def tier_for_level(level: int) -> str:
    """Return tier name for given level.

    1: Novice
    2: Apprentice
    3: Adept
    4: Expert
    5: Master
    6: Grandmaster I
    7: Grandmaster II
    8+: Grandmaster III
    """
    if level <= 0:
        return TIERS[0]
    if level <= 5:
        return TIERS[level - 1]
    if level == 6:
        return "Grandmaster I"
    if level == 7:
        return "Grandmaster II"
    return "Grandmaster III"


def calculate_level_and_tier(total_xp: int) -> tuple[int, str, int, int, int]:
    """Given total_xp >= 0, return (level, tier, progress_pct, xp_into_level, xp_to_next)."""
    xp = max(0, total_xp)

    if xp < 50:
        level = 1
        xp_into = xp
        req = 50
        pct = int((xp_into / req) * 100)
        return 1, "Novice", pct, xp_into, req - xp_into

    if xp < 150:
        level = 2
        xp_into = xp - 50
        req = 100
        pct = int((xp_into / req) * 100)
        return 2, "Apprentice", pct, xp_into, req - xp_into

    if xp < 350:
        level = 3
        xp_into = xp - 150
        req = 200
        pct = int((xp_into / req) * 100)
        return 3, "Adept", pct, xp_into, req - xp_into

    if xp < 750:
        level = 4
        xp_into = xp - 350
        req = 400
        pct = int((xp_into / req) * 100)
        return 4, "Expert", pct, xp_into, req - xp_into

    if xp < 1550:
        level = 5
        xp_into = xp - 750
        req = 800
        pct = int((xp_into / req) * 100)
        return 5, "Master", pct, xp_into, req - xp_into

    if xp < 2350:
        level = 6
        xp_into = xp - 1550
        req = 800
        pct = int((xp_into / req) * 100)
        return 6, "Grandmaster I", pct, xp_into, req - xp_into

    if xp < 3150:
        level = 7
        xp_into = xp - 2350
        req = 800
        pct = int((xp_into / req) * 100)
        return 7, "Grandmaster II", pct, xp_into, req - xp_into

    # Capped at Grandmaster III
    level = 8
    xp_into = xp - 3150
    return 8, "Grandmaster III", 100, xp_into, 0


def get_xp(domain: str, db_path=None) -> dict[str, Any]:
    """Fetch XP data for a domain."""
    _ensure_table(db_path)
    conn = connect(db_path)
    row = conn.execute(f"SELECT xp FROM {XP_TABLE} WHERE domain=?", (domain,)).fetchone()
    conn.close()

    total_xp = row[0] if row else 0
    level, tier, progress_pct, xp_into, xp_to_next = calculate_level_and_tier(total_xp)

    return {
        "domain": domain,
        "xp": total_xp,
        "level": level,
        "tier": tier,
        "progress_pct": progress_pct,
        "xp_into_level": xp_into,
        "xp_to_next": xp_to_next,
    }


def add_xp(domain: str, amount: int, db_path=None) -> tuple[int, str, bool]:
    """Directly add XP to domain without creating an audit event (legacy helper)."""
    if amount <= 0:
        current = get_xp(domain, db_path)
        return current["level"], current["tier"], False

    _ensure_table(db_path)
    conn = connect(db_path)
    row = conn.execute(f"SELECT xp, level FROM {XP_TABLE} WHERE domain=?", (domain,)).fetchone()

    old_xp = row[0] if row else 0
    old_level = row[1] if row else 1

    new_xp = old_xp + amount
    new_level, new_tier, _, _, _ = calculate_level_and_tier(new_xp)
    leveled_up = new_level > old_level

    conn.execute(
        f"""INSERT OR REPLACE INTO {XP_TABLE} (domain, xp, level, tier)
            VALUES (?, ?, ?, ?)""",
        (domain, new_xp, new_level, new_tier),
    )
    conn.commit()
    conn.close()

    return new_level, new_tier, leveled_up


def award_xp(
    domain: str,
    event_type: str,
    amount: Optional[int] = None,
    unit_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    evidence_id: Optional[str] = None,
    event_id: Optional[str] = None,
    xp_algorithm: str = CURRENT_XP_ALGORITHM,
    db_path=None,
) -> tuple[int, str, bool, int]:
    """Award XP deterministically based on knowledge event, with full audit trail logging.

    Returns (new_level, new_tier, leveled_up, xp_awarded).
    """
    xp_val = amount if amount is not None else XP_AMOUNTS.get(event_type, 0)
    if xp_val <= 0:
        current = get_xp(domain, db_path)
        return current["level"], current["tier"], False, 0

    _ensure_table(db_path)
    now = datetime.now(timezone.utc).isoformat()
    if event_id is None and evidence_id:
        fingerprint = "\x1f".join(
            [event_type, domain, unit_id or "", evidence_id or "", task_id or "", session_id or ""]
        )
        event_id = f"xpevt_{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]}"
    elif event_id is None:
        # Legacy callers without evidence represent distinct lifecycle events.
        event_id = f"xpevt_{uuid.uuid4().hex[:12]}"

    conn = connect(db_path)

    existing = conn.execute(
        f"SELECT 1 FROM {XP_EVENTS_TABLE} WHERE event_id = ?", (event_id,)
    ).fetchone()
    if existing:
        conn.rollback()
        conn.close()
        current = get_xp(domain, db_path)
        return current["level"], current["tier"], False, 0

    # 1. Update Domain XP
    row = conn.execute(f"SELECT xp, level FROM {XP_TABLE} WHERE domain=?", (domain,)).fetchone()
    old_xp = row[0] if row else 0
    old_level = row[1] if row else 1

    new_xp = old_xp + xp_val
    new_level, new_tier, _, _, _ = calculate_level_and_tier(new_xp)
    leveled_up = new_level > old_level

    conn.execute(
        f"""INSERT OR REPLACE INTO {XP_TABLE} (domain, xp, level, tier)
            VALUES (?, ?, ?, ?)""",
        (domain, new_xp, new_level, new_tier),
    )

    # 2. Record Event in Audit Trail
    conn.execute(
        f"""INSERT INTO {XP_EVENTS_TABLE} (
            event_id, domain, unit_id, xp_amount, event_type,
            task_id, session_id, evidence_id, xp_algorithm, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            domain,
            unit_id,
            xp_val,
            event_type,
            task_id,
            session_id,
            evidence_id,
            xp_algorithm,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return new_level, new_tier, leveled_up, xp_val


def list_xp_events(
    domain: Optional[str] = None,
    unit_id: Optional[str] = None,
    db_path=None,
) -> list[dict[str, Any]]:
    """List recorded XP audit events."""
    _ensure_table(db_path)
    conn = connect(db_path)

    query = f"""SELECT event_id, domain, unit_id, xp_amount, event_type,
                       task_id, session_id, evidence_id, xp_algorithm, timestamp
                FROM {XP_EVENTS_TABLE} WHERE 1=1"""
    params: list[Any] = []

    if domain:
        query += " AND domain = ?"
        params.append(domain)
    if unit_id:
        query += " AND unit_id = ?"
        params.append(unit_id)

    query += " ORDER BY timestamp ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [
        {
            "event_id": r[0],
            "domain": r[1],
            "unit_id": r[2],
            "xp_amount": r[3],
            "event_type": r[4],
            "task_id": r[5],
            "session_id": r[6],
            "evidence_id": r[7],
            "xp_algorithm": r[8],
            "timestamp": r[9],
        }
        for r in rows
    ]


def recalculate_domain_xp(domain: str, db_path=None) -> int:
    """Deterministically recalculate total XP from raw audit events."""
    _ensure_table(db_path)
    conn = connect(db_path)
    row = conn.execute(
        f"SELECT SUM(xp_amount) FROM {XP_EVENTS_TABLE} WHERE domain = ?", (domain,)
    ).fetchone()
    total_xp = int(row[0] or 0) if row else 0

    new_level, new_tier, _, _, _ = calculate_level_and_tier(total_xp)
    conn.execute(
        f"""INSERT OR REPLACE INTO {XP_TABLE} (domain, xp, level, tier)
            VALUES (?, ?, ?, ?)""",
        (domain, total_xp, new_level, new_tier),
    )
    conn.commit()
    conn.close()
    return total_xp


def list_all_xp(db_path=None) -> list[dict[str, Any]]:
    """List XP progression for all recorded domains ordered by xp DESC."""
    _ensure_table(db_path)
    conn = connect(db_path)
    rows = conn.execute(f"SELECT domain, xp, level, tier FROM {XP_TABLE} ORDER BY xp DESC").fetchall()
    conn.close()

    results = []
    for r in rows:
        domain, total_xp, _, _ = r
        level, tier, progress_pct, xp_into, xp_to_next = calculate_level_and_tier(total_xp)
        results.append({
            "domain": domain,
            "xp": total_xp,
            "level": level,
            "tier": tier,
            "progress_pct": progress_pct,
            "xp_into_level": xp_into,
            "xp_to_next": xp_to_next,
        })
    return results


def migrate_confidence_to_xp(db_path=None) -> int:
    """Migrate existing domain_confidence scores to domain_xp.

    Formula: initial_xp = int(round((score / 100.0) * 1550))
    Only migrates domains that do not already exist in domain_xp (idempotent).
    """
    _ensure_table(db_path)
    conn = connect(db_path)
    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='domain_confidence'"
    ).fetchone()
    if not table_check:
        conn.close()
        return 0

    conf_rows = conn.execute("SELECT domain, score FROM domain_confidence").fetchall()
    existing_domains = {r[0] for r in conn.execute(f"SELECT domain FROM {XP_TABLE}").fetchall()}

    migrated_count = 0
    for domain, score in conf_rows:
        if domain not in existing_domains:
            initial_xp = int(round((float(score or 0.0) / 100.0) * 1550))
            level, tier, _, _, _ = calculate_level_and_tier(initial_xp)
            conn.execute(
                f"""INSERT INTO {XP_TABLE} (domain, xp, level, tier)
                    VALUES (?, ?, ?, ?)""",
                (domain, initial_xp, level, tier),
            )
            migrated_count += 1

    conn.commit()
    conn.close()
    return migrated_count

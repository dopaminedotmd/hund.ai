"""Domain XP — knowledge-driven XP engine and progression tiers per domain."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hund.stats.tiers import TIERS, render_bar
from hund.store.sqlite import connect

XP_TABLE = "domain_xp"


def _ensure_table(db_path=None) -> None:
    conn = connect(db_path)
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {XP_TABLE} (
            domain TEXT PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            tier TEXT DEFAULT 'Novice'
        )"""
    )
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
    """Add XP to domain. Returns (new_level, new_tier, leveled_up)."""
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
    # Check if domain_confidence table exists
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

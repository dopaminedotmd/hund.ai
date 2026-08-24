"""Unit tests for the domain XP engine and progression tiers."""
from pathlib import Path
import tempfile

from hund.domains.xp import (
    XP_TABLE,
    _ensure_table,
    add_xp,
    calculate_level_and_tier,
    get_xp,
    list_all_xp,
    migrate_confidence_to_xp,
    tier_for_level,
    xp_required,
)
from hund.store.sqlite import connect


def test_xp_required_series() -> None:
    assert xp_required(1) == 50
    assert xp_required(2) == 100
    assert xp_required(3) == 200
    assert xp_required(4) == 400
    assert xp_required(5) == 800
    assert xp_required(6) == 800
    assert xp_required(10) == 800


def test_tier_for_level() -> None:
    assert tier_for_level(1) == "Novice"
    assert tier_for_level(2) == "Apprentice"
    assert tier_for_level(3) == "Adept"
    assert tier_for_level(4) == "Expert"
    assert tier_for_level(5) == "Master"
    assert tier_for_level(6) == "Grandmaster I"
    assert tier_for_level(7) == "Grandmaster II"
    assert tier_for_level(8) == "Grandmaster III"
    assert tier_for_level(10) == "Grandmaster III"


def test_calculate_level_and_tier_thresholds_and_progress() -> None:
    # Level 1: 0..49
    lvl, tier, pct, into, to_next = calculate_level_and_tier(0)
    assert (lvl, tier, pct, into, to_next) == (1, "Novice", 0, 0, 50)

    lvl, tier, pct, into, to_next = calculate_level_and_tier(25)
    assert (lvl, tier, pct, into, to_next) == (1, "Novice", 50, 25, 25)

    # Level 2: 50..149
    lvl, tier, pct, into, to_next = calculate_level_and_tier(50)
    assert (lvl, tier, pct, into, to_next) == (2, "Apprentice", 0, 0, 100)

    lvl, tier, pct, into, to_next = calculate_level_and_tier(100)
    assert (lvl, tier, pct, into, to_next) == (2, "Apprentice", 50, 50, 50)

    # Level 3: 150..349
    lvl, tier, pct, into, to_next = calculate_level_and_tier(150)
    assert (lvl, tier, pct, into, to_next) == (3, "Adept", 0, 0, 200)

    # Level 4: 350..749
    lvl, tier, pct, into, to_next = calculate_level_and_tier(350)
    assert (lvl, tier, pct, into, to_next) == (4, "Expert", 0, 0, 400)

    # Level 5: 750..1549 (Master)
    lvl, tier, pct, into, to_next = calculate_level_and_tier(750)
    assert (lvl, tier, pct, into, to_next) == (5, "Master", 0, 0, 800)

    # Level 6: 1550..2349 (Grandmaster I)
    lvl, tier, pct, into, to_next = calculate_level_and_tier(1550)
    assert (lvl, tier, pct, into, to_next) == (6, "Grandmaster I", 0, 0, 800)

    # Level 7: 2350..3149 (Grandmaster II)
    lvl, tier, pct, into, to_next = calculate_level_and_tier(2350)
    assert (lvl, tier, pct, into, to_next) == (7, "Grandmaster II", 0, 0, 800)

    # Level 8: 3150+ (Grandmaster III capped)
    lvl, tier, pct, into, to_next = calculate_level_and_tier(3150)
    assert (lvl, tier, pct, into, to_next) == (8, "Grandmaster III", 100, 0, 0)

    lvl, tier, pct, into, to_next = calculate_level_and_tier(5000)
    assert (lvl, tier, pct, into, to_next) == (8, "Grandmaster III", 100, 1850, 0)


def test_add_xp_and_progression_in_db(tmp_path: Path) -> None:
    db_file = tmp_path / "test_xp.sqlite"

    # Initial state
    res = get_xp("python", db_path=db_file)
    assert res["xp"] == 0
    assert res["level"] == 1
    assert res["tier"] == "Novice"

    # Add 25 XP (still level 1)
    lvl, tier, leveled = add_xp("python", 25, db_path=db_file)
    assert (lvl, tier, leveled) == (1, "Novice", False)

    # Add 25 more XP (50 total -> level up to Apprentice!)
    lvl, tier, leveled = add_xp("python", 25, db_path=db_file)
    assert (lvl, tier, leveled) == (2, "Apprentice", True)

    res = get_xp("python", db_path=db_file)
    assert res["xp"] == 50
    assert res["level"] == 2
    assert res["tier"] == "Apprentice"
    assert res["progress_pct"] == 0

    # Add 100 more XP (150 total -> level up to Adept!)
    lvl, tier, leveled = add_xp("python", 100, db_path=db_file)
    assert (lvl, tier, leveled) == (3, "Adept", True)

    # Add 1400 more XP (1550 total -> level up to Grandmaster I!)
    lvl, tier, leveled = add_xp("python", 1400, db_path=db_file)
    assert (lvl, tier, leveled) == (6, "Grandmaster I", True)

    # List all XP
    add_xp("git", 40, db_path=db_file)
    all_xp = list_all_xp(db_path=db_file)
    assert len(all_xp) == 2
    assert all_xp[0]["domain"] == "python"
    assert all_xp[0]["xp"] == 1550
    assert all_xp[1]["domain"] == "git"
    assert all_xp[1]["xp"] == 40


def test_migrate_confidence_to_xp(tmp_path: Path) -> None:
    db_file = tmp_path / "test_migration.sqlite"
    conn = connect(db_file)
    conn.execute("""CREATE TABLE domain_confidence (
        domain TEXT PRIMARY KEY,
        score REAL,
        signal_count INTEGER,
        unique_sources TEXT,
        first_seen TEXT,
        last_seen TEXT,
        session_count INTEGER,
        confidence_tier TEXT
    )""")
    conn.execute("INSERT INTO domain_confidence VALUES ('python', 100.0, 5, '[]', '', '', 3, 'confident')")
    conn.execute("INSERT INTO domain_confidence VALUES ('rust', 50.0, 2, '[]', '', '', 1, 'active')")
    conn.commit()
    conn.close()

    # First migration
    migrated = migrate_confidence_to_xp(db_path=db_file)
    assert migrated == 2

    py_xp = get_xp("python", db_path=db_file)
    assert py_xp["xp"] == 1550
    assert py_xp["tier"] == "Grandmaster I"

    rust_xp = get_xp("rust", db_path=db_file)
    assert rust_xp["xp"] == int(round(50.0 / 100.0 * 1550))
    assert rust_xp["tier"] == "Master"

    # Idempotent: second migration does nothing
    migrated_again = migrate_confidence_to_xp(db_path=db_file)
    assert migrated_again == 0


def test_tool_use_never_awards_xp() -> None:
    from hund.agent.tool_dispatch import _TURN_TOOL_XP, _log_tool

    _TURN_TOOL_XP.clear()
    turn_id = "test-turn-123"

    for _ in range(7):
        _log_tool("read_file", "safe", "content", success=1, run_id=turn_id)

    assert _TURN_TOOL_XP == {}

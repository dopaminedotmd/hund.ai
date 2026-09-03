"""agyC/1 — Spår 14: XP-attribution via audit events, external/unattributed-label."""
from hund.domains.xp import _ensure_table, add_xp
from hund.learning.reflection import compute_reflections, take_snapshot
from hund.store.sqlite import connect


def test_event_awarded_xp_shows_as_gain(tmp_path):
    db = tmp_path / "hund.db"
    snap = take_snapshot(db_path=db)
    add_xp("python", 50, db_path=db)
    lines = compute_reflections(snap, db_path=db)
    assert any("+50 XP" in ln and "python" in ln for ln in lines)
    assert not any("external/unattributed" in ln for ln in lines)


def test_raw_table_bump_without_event_is_external(tmp_path):
    db = tmp_path / "hund.db"
    snap = take_snapshot(db_path=db)
    # Simulate an external process writing XP directly to the table (no event).
    _ensure_table(db)
    conn = connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO domain_xp (domain, xp, level, tier) VALUES ('rust', 25, 1, 'novice')"
    )
    conn.commit()
    conn.close()
    lines = compute_reflections(snap, db_path=db)
    assert not any("+25 XP" in ln and "rust" in ln for ln in lines)
    assert any("external/unattributed" in ln and "rust" in ln for ln in lines)

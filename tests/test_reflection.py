"""Unit tests for reflection & post-turn learning engine."""
from pathlib import Path

from hund.domains.confidence import CONFIDENCE_DB, _ensure_table as _ensure_conf_table, add_signal
from hund.domains.xp import _ensure_table as _ensure_xp_table, add_xp
from hund.learning.observer import add_gap_event
from hund.learning.reflection import TurnSnapshot, compute_reflections, take_snapshot
from hund.store.sqlite import connect


def test_reflection_level_up_and_xp_gain(tmp_path: Path) -> None:
    db_file = tmp_path / "test_refl.sqlite"
    _ensure_xp_table(db_file)
    _ensure_conf_table(db_file)

    # Initial state (0 XP)
    snap = take_snapshot(db_path=db_file)

    # Add 50 XP to python (Levels up from Novice to Apprentice!)
    add_xp("python", 50, db_path=db_file)

    lines = compute_reflections(snap, db_path=db_file)
    assert len(lines) == 2
    # Level-up line first (highest priority)
    assert "⟶ level up!" in lines[0]
    assert "python" in lines[0]
    assert "Apprentice" in lines[0]
    assert lines[0].startswith("  · ")

    # XP-bar line second
    assert "+50 XP" in lines[1]
    assert "python" in lines[1]
    assert "█" in lines[1] or "░" in lines[1]
    assert lines[1].startswith("  · ")


def test_reflection_domain_lock(tmp_path: Path) -> None:
    db_file = tmp_path / "test_refl_lock.sqlite"
    _ensure_xp_table(db_file)
    _ensure_conf_table(db_file)

    # Seed initial candidate
    add_signal("git", "user_declaration", db_path=db_file)
    snap = take_snapshot(db_path=db_file)

    # Manually make git lockable (score >= 85, >=2 sources, session >= 3)
    conn = connect(db_file)
    conn.execute(
        f"UPDATE {CONFIDENCE_DB} SET score=90.0, unique_sources='[\"a\",\"b\"]', session_count=3 WHERE domain='git'"
    )
    conn.commit()
    conn.close()

    lines = compute_reflections(snap, db_path=db_file)
    assert any("locked git as a specialization" in ln for ln in lines)


def test_reflection_gap_event_and_redaction(tmp_path: Path) -> None:
    db_file = tmp_path / "test_refl_gap.sqlite"
    _ensure_xp_table(db_file)
    _ensure_conf_table(db_file)

    snap = take_snapshot(db_path=db_file)

    # Log gap event with sensitive token
    add_gap_event(symptom="invalid key sk-1234567890123456789012345", domain="api")

    lines = compute_reflections(snap, db_path=db_file)
    assert any("learned:" in ln for ln in lines)
    # Secret must be redacted!
    assert not any("sk-1234567890123456789012345" in ln for ln in lines)
    assert any("[REDACTED:secret]" in ln or "learned:" in ln for ln in lines)


def test_reflection_max_three_lines_priority(tmp_path: Path) -> None:
    db_file = tmp_path / "test_refl_prio.sqlite"
    _ensure_xp_table(db_file)
    _ensure_conf_table(db_file)

    snap = take_snapshot(db_path=db_file)

    # Trigger multiple events: 2 level-ups, 2 XP gains, 1 gap event
    add_xp("python", 50, db_path=db_file)  # Level up + XP
    add_xp("rust", 50, db_path=db_file)    # Level up + XP
    add_gap_event(symptom="missing library", domain="tools")

    lines = compute_reflections(snap, db_path=db_file, max_lines=3)
    # Must be capped at exactly 3 lines
    assert len(lines) == 3
    # First two must be the level-ups (highest priority)
    assert "⟶ level up!" in lines[0]
    assert "⟶ level up!" in lines[1]

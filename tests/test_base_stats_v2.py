"""Tests for Base Stats v2 pure telemetry, epochs, rolling windows, and domain stats."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest

from hund.stats import base_stats
from hund.stats import epochs


@pytest.fixture
def stats_home(tmp_path: Path) -> Path:
    # Setup directories
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "brain" / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)

    # Initialize hund.db
    hund_db = tmp_path / "hund.db"
    epochs.set_epoch(1, "2026-01-01T00:00:00+00:00", db_path=hund_db)

    # Initialize tool_events.db
    tool_db = tmp_path / "logs" / "tool_events.db"
    conn = sqlite3.connect(tool_db)
    conn.execute(
        """CREATE TABLE tool_events (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            tool TEXT,
            risk TEXT,
            outcome TEXT,
            success INTEGER DEFAULT 0
        )"""
    )
    # Insert 3 successes, 1 failure in epoch 1
    conn.execute(
        "INSERT INTO tool_events VALUES ('t1', '2026-01-10T10:00:00+00:00', 'bash', 'low', 'ran', 1)"
    )
    conn.execute(
        "INSERT INTO tool_events VALUES ('t2', '2026-01-10T10:05:00+00:00', 'git', 'low', 'ran', 1)"
    )
    conn.execute(
        "INSERT INTO tool_events VALUES ('t3', '2026-01-10T10:10:00+00:00', 'python', 'low', 'ran', 1)"
    )
    conn.execute(
        "INSERT INTO tool_events VALUES ('t4', '2026-01-10T10:15:00+00:00', 'python', 'low', 'ran', 0)"
    )
    conn.commit()
    conn.close()

    # Initialize requests.db
    req_db = tmp_path / "logs" / "requests.db"
    conn = sqlite3.connect(req_db)
    conn.execute(
        """CREATE TABLE requests (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0
        )"""
    )
    conn.execute("INSERT INTO requests VALUES ('r1', '2026-01-10T10:00:00+00:00', 100, 50)")
    conn.execute("INSERT INTO requests VALUES ('r2', '2026-01-10T10:05:00+00:00', 200, 150)")
    conn.commit()
    conn.close()

    return tmp_path


def test_epoch_advancement(stats_home: Path) -> None:
    hund_db = stats_home / "hund.db"
    ep_num, started_at = epochs.get_current_epoch(hund_db)
    assert ep_num == 1
    assert started_at == "2026-01-01T00:00:00+00:00"

    # Advance epoch
    new_ep, new_started = epochs.advance_epoch(hund_db)
    assert new_ep == 2
    assert new_started > started_at

    ep_check, _ = epochs.get_current_epoch(hund_db)
    assert ep_check == 2


def test_precision_with_epochs(stats_home: Path) -> None:
    # In epoch 1: 3 success / 4 total = 75.0%
    stat = base_stats.compute_precision(home=stats_home)
    assert stat["value"] == 75.0
    assert stat["tier"] == "Expert"

    # Advance epoch to right now
    epochs.advance_epoch(stats_home / "hund.db")

    # In epoch 2, old records are excluded -> rate is None (tier is "—")
    stat_ep2 = base_stats.compute_precision(home=stats_home)
    assert stat_ep2["value"] is None
    assert stat_ep2["tier"] == "—"


def test_mastery_from_knowledge_db(stats_home: Path) -> None:
    from hund.knowledge import db as kdb
    from hund.knowledge.models import KnowledgeUnit, STATUS_VALIDATED, STATUS_CANDIDATE

    know_db = stats_home / "knowledge" / "knowledge.db"
    kdb.ensure_knowledge_tables(know_db)

    # Insert 2 validated units for python, 1 candidate
    kdb.insert_unit(
        KnowledgeUnit(id="k1", domain="python", statement="rule 1", status=STATUS_VALIDATED, confidence=0.9),
        db_path=know_db,
    )
    kdb.insert_unit(
        KnowledgeUnit(id="k2", domain="python", statement="rule 2", status=STATUS_VALIDATED, confidence=0.9),
        db_path=know_db,
    )
    kdb.insert_unit(
        KnowledgeUnit(id="k3", domain="python", statement="rule 3", status=STATUS_CANDIDATE, confidence=0.5),
        db_path=know_db,
    )

    stat = base_stats.compute_mastery(domain="python", home=stats_home)
    assert stat["value"] == 2.0


def test_compute_all_pure_telemetry(stats_home: Path) -> None:
    all_stats = base_stats.compute_all(home=stats_home)
    assert "clarity" in all_stats
    assert "precision" in all_stats
    assert "efficiency" in all_stats
    assert "endurance" in all_stats
    assert "mastery" in all_stats
    # No stat_quality exists anywhere
    assert "stat_quality" not in all_stats

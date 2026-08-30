"""Regression tests for epoch-bound, trace-backed Endurance v3."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from hund.agent import sessions
from hund.stats.base_stats import compute_endurance
from hund.stats.epochs import get_stat_algorithm_boundary, set_epoch
from hund.trace.events import create_event, write_event


def _initialize_v3(home: Path) -> datetime:
    started_at = get_stat_algorithm_boundary(
        "endurance", "v3", db_path=home / "hund.db"
    )
    return datetime.fromisoformat(started_at)


def _add_sustained_session(home: Path) -> str:
    session_id = sessions.create(home=home)
    for role in ("user", "assistant", "user", "assistant"):
        sessions.add_message(session_id, role, "message", home=home)
    return session_id


def _write_event(
    home: Path,
    *,
    session_id: str,
    run_id: str,
    event_type: str,
    created_at: datetime,
    payload: dict[str, object] | None = None,
) -> None:
    event = create_event(
        workspace_id=str(home),
        session_id=session_id,
        run_id=run_id,
        actor="hund",
        event_type=event_type,
        policy_version="test",
        payload_unredacted=payload,
    )
    event.created_at = created_at.isoformat()
    write_event(event, db_path=home / "hund.db")


def _add_verified_run(
    home: Path,
    *,
    session_id: str,
    run_id: str,
    started_at: datetime,
    passed: bool,
    verification_results: tuple[bool, ...] | None = None,
) -> None:
    results = verification_results or (passed,)
    offset = 1
    for result in results:
        _write_event(
            home,
            session_id=session_id,
            run_id=run_id,
            event_type="verification_completed",
            created_at=started_at + timedelta(seconds=offset),
            payload={"passed": result},
        )
        offset += 1
    _write_event(
        home,
        session_id=session_id,
        run_id=run_id,
        event_type="final_claim",
        created_at=started_at + timedelta(seconds=offset),
    )
    _write_event(
        home,
        session_id=session_id,
        run_id=run_id,
        event_type="run_completed",
        created_at=started_at + timedelta(seconds=offset + 1),
    )


def _add_successes(home: Path, started_at: datetime, count: int = 2) -> list[str]:
    session_ids: list[str] = []
    for index in range(count):
        session_id = _add_sustained_session(home)
        session_ids.append(session_id)
        _add_verified_run(
            home,
            session_id=session_id,
            run_id=f"success-{index}",
            started_at=started_at + timedelta(minutes=index),
            passed=True,
        )
    return session_ids


def test_long_sessions_without_trace_verification_do_not_raise_endurance(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    for _ in range(3):
        _add_sustained_session(home)

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["progress"] == 0
    assert stat["status_text"] == "Collecting evidence"


def test_two_verified_successes_are_still_collecting_evidence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["progress"] == 0
    assert stat["status_text"] == "Collecting evidence"


def test_two_successes_and_one_failure_produce_verified_rate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    session_id = _add_sustained_session(home)
    _add_verified_run(
        home,
        session_id=session_id,
        run_id="failure",
        started_at=started_at + timedelta(minutes=3),
        passed=False,
    )

    stat = compute_endurance(home=home)

    assert stat["value"] == 66.7
    assert stat["sample_count"] == 3


def test_latest_passing_verification_before_final_claim_wins(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    session_id = _add_sustained_session(home)
    _add_verified_run(
        home,
        session_id=session_id,
        run_id="resolved",
        started_at=started_at + timedelta(minutes=3),
        passed=True,
        verification_results=(False, True),
    )

    stat = compute_endurance(home=home)

    assert stat["value"] == 100.0
    assert stat["sample_count"] == 3


def test_latest_failing_verification_before_final_claim_wins(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    session_id = _add_sustained_session(home)
    _add_verified_run(
        home,
        session_id=session_id,
        run_id="unresolved",
        started_at=started_at + timedelta(minutes=3),
        passed=False,
        verification_results=(True, False),
    )

    stat = compute_endurance(home=home)

    assert stat["value"] == 66.7


def test_verification_after_final_claim_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    session_id = _add_sustained_session(home)
    run_start = started_at + timedelta(minutes=3)
    _write_event(
        home,
        session_id=session_id,
        run_id="late-pass",
        event_type="verification_completed",
        created_at=run_start + timedelta(seconds=1),
        payload={"passed": False},
    )
    _write_event(
        home,
        session_id=session_id,
        run_id="late-pass",
        event_type="final_claim",
        created_at=run_start + timedelta(seconds=2),
    )
    _write_event(
        home,
        session_id=session_id,
        run_id="late-pass",
        event_type="verification_completed",
        created_at=run_start + timedelta(seconds=3),
        payload={"passed": True},
    )
    _write_event(
        home,
        session_id=session_id,
        run_id="late-pass",
        event_type="run_completed",
        created_at=run_start + timedelta(seconds=4),
    )

    stat = compute_endurance(home=home)

    assert stat["value"] == 66.7


def test_missing_final_claim_or_run_completion_is_ineligible(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    for index, terminal_event in enumerate((None, "final_claim")):
        session_id = _add_sustained_session(home)
        run_start = started_at + timedelta(minutes=3 + index)
        _write_event(
            home,
            session_id=session_id,
            run_id=f"incomplete-{index}",
            event_type="verification_completed",
            created_at=run_start,
            payload={"passed": True},
        )
        if terminal_event:
            _write_event(
                home,
                session_id=session_id,
                run_id=f"incomplete-{index}",
                event_type=terminal_event,
                created_at=run_start + timedelta(seconds=1),
            )

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["status_text"] == "Collecting evidence"


def test_final_claim_without_verification_is_ineligible(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    session_id = _add_sustained_session(home)
    run_start = started_at + timedelta(minutes=3)
    _write_event(
        home,
        session_id=session_id,
        run_id="unverified",
        event_type="final_claim",
        created_at=run_start,
    )
    _write_event(
        home,
        session_id=session_id,
        run_id="unverified",
        event_type="run_completed",
        created_at=run_start + timedelta(seconds=1),
    )

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["status_text"] == "Collecting evidence"


def test_duplicate_events_and_restarts_do_not_double_count_runs(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    session_ids = _add_successes(home, started_at, count=3)
    _add_verified_run(
        home,
        session_id=session_ids[0],
        run_id="success-0",
        started_at=started_at + timedelta(minutes=5),
        passed=True,
    )

    stat = compute_endurance(home=home)

    assert stat["value"] == 100.0
    assert stat["sample_count"] == 3


def test_events_before_v3_and_global_epoch_cutoffs_are_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    v3_started_at = _initialize_v3(home)
    old_session = _add_sustained_session(home)
    _add_verified_run(
        home,
        session_id=old_session,
        run_id="pre-v3",
        started_at=v3_started_at - timedelta(days=1),
        passed=True,
    )
    _add_successes(home, v3_started_at, count=3)
    set_epoch(
        2,
        (v3_started_at + timedelta(minutes=2, seconds=30)).isoformat(),
        db_path=home / "hund.db",
    )

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["status_text"] == "Collecting evidence"


def test_algorithm_boundary_is_stable_and_resets_only_on_version_change(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "hund.db"

    first = get_stat_algorithm_boundary("endurance", "v3", db_path=db_path)
    second = get_stat_algorithm_boundary("endurance", "v3", db_path=db_path)
    _write_event(
        tmp_path,
        session_id="history-session",
        run_id="history-run",
        event_type="run_completed",
        created_at=datetime.fromisoformat(first),
    )
    changed = get_stat_algorithm_boundary("endurance", "v4", db_path=db_path)
    stable_changed = get_stat_algorithm_boundary("endurance", "v4", db_path=db_path)
    connection = sqlite3.connect(db_path)
    metadata = dict(
        connection.execute(
            "SELECT key, value FROM stats_meta WHERE key LIKE 'endurance_%'"
        ).fetchall()
    )
    trace_count = connection.execute(
        "SELECT COUNT(*) FROM trace_events"
    ).fetchone()[0]
    connection.close()

    assert second == first
    assert changed >= first
    assert stable_changed == changed
    assert metadata == {
        "endurance_algorithm": "v4",
        "endurance_started_at": changed,
    }
    assert trace_count == 1


def test_missing_run_identity_is_excluded(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at)
    session_id = _add_sustained_session(home)
    _add_verified_run(
        home,
        session_id=session_id,
        run_id="",
        started_at=started_at + timedelta(minutes=3),
        passed=True,
    )

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["status_text"] == "Collecting evidence"


def test_trace_database_error_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at, count=3)

    with patch(
        "hund.stats.base_stats.connect", side_effect=RuntimeError("db unavailable")
    ):
        stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["progress"] == 0
    assert stat["status_text"] == "Collecting evidence"


def test_malformed_verification_payload_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    started_at = _initialize_v3(home)
    _add_successes(home, started_at, count=3)
    session_id = _add_sustained_session(home)
    _add_verified_run(
        home,
        session_id=session_id,
        run_id="malformed",
        started_at=started_at + timedelta(minutes=4),
        passed=True,
    )
    connection = sqlite3.connect(home / "hund.db")
    connection.execute(
        "UPDATE trace_events SET payload_redacted = ? WHERE run_id = ? "
        "AND event_type = 'verification_completed'",
        ('{"passed": "yes"}', "malformed"),
    )
    connection.commit()
    connection.close()

    stat = compute_endurance(home=home)

    assert stat["value"] is None
    assert stat["progress"] == 0
    assert stat["status_text"] == "Collecting evidence"

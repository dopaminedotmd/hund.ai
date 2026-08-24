"""Unit tests for append-only evidence ledger."""
from pathlib import Path
import sqlite3

from hund.learning.ledger import (
    _ensure_tables,
    append_event,
    get_event,
    list_events,
)
from hund.store.sqlite import connect


def test_append_event_and_get(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ledger.sqlite"

    ev_id = append_event(
        session_id="sess_123",
        turn_id=1,
        event_type="user_prompt",
        source_type="user",
        source_ref="terminal_turn_1",
        workspace_id="ws_abc",
        candidate_domains=["python", "fastapi"],
        payload="def hello(): pass",
        db_path=db_file,
    )

    assert isinstance(ev_id, str) and len(ev_id) > 0

    event = get_event(ev_id, db_path=db_file)
    assert event is not None
    assert event["event_id"] == ev_id
    assert event["session_id"] == "sess_123"
    assert event["turn_id"] == 1
    assert event["event_type"] == "user_prompt"
    assert event["source_type"] == "user"
    assert event["source_ref"] == "terminal_turn_1"
    assert event["workspace_id"] == "ws_abc"
    assert event["candidate_domains"] == ["python", "fastapi"]
    assert event["payload"] == "def hello(): pass"
    # Content hash sha256
    import hashlib
    expected_hash = hashlib.sha256(b"def hello(): pass").hexdigest()
    assert event["content_hash"] == expected_hash


def test_get_nonexistent_event(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ledger.sqlite"
    assert get_event("nonexistent_id", db_path=db_file) is None


def test_list_events_and_pagination(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ledger.sqlite"

    ids = []
    for i in range(5):
        ev_id = append_event(
            session_id="sess_p",
            turn_id=i,
            event_type=f"event_{i}",
            source_type="user",
            payload=f"payload {i}",
            timestamp=f"2026-08-24T00:00:0{i}Z",
            db_path=db_file,
        )
        ids.append(ev_id)

    # List all (limit 10) -> ordered newest first: ids[4], ids[3], ids[2], ids[1], ids[0]
    events = list_events(limit=10, db_path=db_file)
    assert len(events) == 5
    assert [e["event_id"] for e in events] == list(reversed(ids))

    # Pagination: fetch before ids[3] -> should return ids[2], ids[1], ids[0]
    page = list_events(limit=2, before_event_id=ids[3], db_path=db_file)
    assert len(page) == 2
    assert page[0]["event_id"] == ids[2]
    assert page[1]["event_id"] == ids[1]

    # Next page before ids[1] -> should return ids[0]
    page2 = list_events(limit=2, before_event_id=ids[1], db_path=db_file)
    assert len(page2) == 1
    assert page2[0]["event_id"] == ids[0]


def test_list_events_filter_session_and_workspace(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ledger.sqlite"

    append_event(session_id="s1", workspace_id="w1", payload="p1", db_path=db_file)
    append_event(session_id="s1", workspace_id="w2", payload="p2", db_path=db_file)
    append_event(session_id="s2", workspace_id="w1", payload="p3", db_path=db_file)

    s1_events = list_events(session_id="s1", db_path=db_file)
    assert len(s1_events) == 2

    w1_events = list_events(workspace_id="w1", db_path=db_file)
    assert len(w1_events) == 2

    s1_w1_events = list_events(session_id="s1", workspace_id="w1", db_path=db_file)
    assert len(s1_w1_events) == 1
    assert s1_w1_events[0]["payload"] == "p1"


def test_append_only_invariant(tmp_path: Path) -> None:
    """Ensure ledger table exists and module exposes no update/delete functions."""
    import hund.learning.ledger as ledger_mod

    # Verify absence of update/delete public functions
    assert not hasattr(ledger_mod, "update_event")
    assert not hasattr(ledger_mod, "delete_event")
    assert not hasattr(ledger_mod, "modify_event")

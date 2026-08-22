"""Tester för trace schema och SQLite persistence."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pytest

from hund.trace.events import TraceEvent, create_event, write_event, list_events_by_run, list_events_by_session
from hund.store.sqlite import connect


def test_create_event_redacts_and_hashes():
    """Verifierar att create_event räknar ut hash och redakterar payload korrekt."""
    payload = {
        "text": "Användarens API-nyckel är sk-12345678901234567890 och epost är test@domain.com",
        "secret": "ghp_11112222333344445555"
    }
    
    event = create_event(
        workspace_id="ws-test",
        session_id="session-123",
        run_id="run-456",
        actor="hund",
        event_type="tool_call_requested",
        policy_version="1.0.0",
        payload_unredacted=payload
    )
    
    # Hashen ska vara beräknad på oredakterad payload
    assert event.payload_hash is not None
    assert len(event.payload_hash) == 64  # SHA256 length in hex
    
    # Känslig data i payload_redacted ska vara maskerad
    redacted = event.payload_redacted
    assert "sk-1234567890" not in redacted["text"]
    assert "ghp_11112222" not in redacted["secret"]
    assert "[REDACTED:secret]" in redacted["text"]
    assert "[REDACTED:secret]" in redacted["secret"]
    assert "test@domain.com" not in redacted["text"]
    assert "[REDACTED:email]" in redacted["text"]
    
    # Redaction metadata ska indikera att ändringar har skett
    assert event.redaction["applied"] is True
    assert "secret" in event.redaction["fields"]
    assert "email" in event.redaction["fields"]


def test_write_and_read_event(tmp_path):
    """Verifierar att events kan sparas i SQLite och hämtas ut korrekt."""
    db_file = tmp_path / "test_hund.db"
    
    # Skapa tabellen genom att ansluta (initierar schemat)
    connect(db_file).close()
    
    event1 = create_event(
        workspace_id="ws-1",
        session_id="sess-A",
        run_id="run-X",
        actor="user",
        event_type="run_started",
        policy_version="1.0.0",
        payload_unredacted={"goal": "test things"}
    )
    
    event2 = create_event(
        workspace_id="ws-1",
        session_id="sess-A",
        run_id="run-X",
        actor="hund",
        event_type="tool_call_requested",
        policy_version="1.0.0",
        payload_unredacted={"tool": "read_file", "path": "file.txt"},
        tool_name="read_file"
    )
    
    event3 = create_event(
        workspace_id="ws-1",
        session_id="sess-B",
        run_id="run-Y",
        actor="user",
        event_type="run_started",
        policy_version="1.0.0",
        payload_unredacted={"goal": "another test"}
    )
    
    # Skriv till DB
    write_event(event1, db_path=db_file)
    write_event(event2, db_path=db_file)
    write_event(event3, db_path=db_file)
    
    # Hämta på run_id
    run_x_events = list_events_by_run("run-X", db_path=db_file)
    assert len(run_x_events) == 2
    assert run_x_events[0].event_id == event1.event_id
    assert run_x_events[0].event_type == "run_started"
    assert run_x_events[0].payload_redacted == {"goal": "test things"}
    assert run_x_events[1].event_id == event2.event_id
    assert run_x_events[1].tool_name == "read_file"
    
    # Hämta på session_id
    session_b_events = list_events_by_session("sess-B", db_path=db_file)
    assert len(session_b_events) == 1
    assert session_b_events[0].event_id == event3.event_id
    assert session_b_events[0].run_id == "run-Y"


def test_database_migrations_run_id(tmp_path):
    """Verifierar att databasmigreringar lägger till run_id i requests och sessions tabeller."""
    # 1. requests.db migration
    req_db = tmp_path / "requests.db"
    # Skapa tabell UTAN run_id kolumn först
    conn = sqlite3.connect(req_db)
    conn.execute("""
        CREATE TABLE requests (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0
        )
    """)
    conn.close()
    
    # Kör connect_requests (bör köra migratorn)
    from hund.store.sqlite import connect_requests
    conn = connect_requests(req_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
    assert "run_id" in cols
    conn.close()

    # 2. sessions.db migration
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    sess_db = sess_dir / "sessions.db"
    conn = sqlite3.connect(sess_db)
    conn.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            seq INTEGER NOT NULL
        )
    """)
    conn.close()
    
    # Kör sessions._connect
    from hund.agent.sessions import _connect
    conn = _connect(tmp_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    assert "run_id" in cols
    conn.close()



def test_create_event_rejects_unknown_event_type():
    with pytest.raises(ValueError, match="event_type"):
        create_event(
            workspace_id="ws",
            session_id="session",
            run_id="run",
            actor="hund",
            event_type="made_up_event",
            policy_version="1.0.0",
            payload_unredacted={},
        )


def test_list_events_by_type(tmp_path):
    from hund.trace.events import list_events_by_type

    db_file = tmp_path / "test_hund.db"
    first = create_event(
        workspace_id="ws",
        session_id="session",
        run_id="run-1",
        actor="hund",
        event_type="tool_call_completed",
        policy_version="1.0.0",
        payload_unredacted={"ok": True},
    )
    second = create_event(
        workspace_id="ws",
        session_id="session",
        run_id="run-2",
        actor="hund",
        event_type="tool_call_failed",
        policy_version="1.0.0",
        payload_unredacted={"ok": False},
    )
    write_event(first, db_path=db_file)
    write_event(second, db_path=db_file)

    completed = list_events_by_type("tool_call_completed", db_path=db_file)
    assert [event.event_id for event in completed] == [first.event_id]
    assert completed[0].payload_hash_algorithm == "sha256"
    assert completed[0].redactor_version == "1.0.0"

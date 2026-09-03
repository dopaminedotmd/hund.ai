"""agyB/5 — TCB-telemetri: turn-ledger-payload, tool_calls_emitted, tool_events-skrivare.

Unit coverage for the Spår 15/6/22 changes in loop.py + tool_dispatch.py + sqlite.py.
Full turn-level behaviour is covered by Gate B live tests (docs/FAS5.md).
"""
from pathlib import Path
from types import SimpleNamespace

from hund.store.sqlite import connect_requests, connect_tool_events
from hund.agent import loop as loop_mod
from hund.agent.tool_dispatch import _log_tool


def _cols(db_path: Path, table: str, which: str) -> set[str]:
    conn = connect_requests(db_path) if which == "requests" else connect_tool_events(db_path)
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return cols


def test_requests_schema_has_tool_calls_emitted(tmp_path):
    cols = _cols(tmp_path / "requests.db", "requests", "requests")
    assert "tool_calls_emitted" in cols


def test_tool_events_schema_has_telemetry_columns(tmp_path):
    cols = _cols(tmp_path / "tool_events.db", "tool_events", "tool_events")
    for col in ("run_id", "session_id", "latency_ms", "risk_class"):
        assert col in cols


def test_old_tool_events_db_is_migrated(tmp_path):
    """An existing tool_events table without telemetry columns gains them."""
    path = tmp_path / "tool_events.db"
    conn = connect_tool_events(path)
    # Simulate a pre-agyB/5 table by removing the new columns via table copy.
    conn.execute("ALTER TABLE tool_events RENAME TO tool_events_old")
    conn.execute(
        "CREATE TABLE tool_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
        "tool TEXT, risk TEXT, outcome TEXT, success INTEGER DEFAULT 0)"
    )
    conn.execute("INSERT INTO tool_events (id, created_at, tool, outcome, success) VALUES ('old', 'x', 'read_file', 'ran', 1)")
    conn.execute("DROP TABLE tool_events_old")
    conn.commit()
    conn.close()
    cols = _cols(path, "tool_events", "tool_events")
    assert {"run_id", "session_id", "latency_ms", "risk_class"} <= cols
    # Old row survives and new inserts carry the new columns.
    _log_tool("write_file", "safe", "ran", 1, run_id="r2", session_id="s2", latency_ms=7, db_path=path)
    conn = connect_tool_events(path)
    rows = conn.execute("SELECT tool, run_id, session_id, latency_ms FROM tool_events ORDER BY created_at").fetchall()
    conn.close()
    assert ("read_file", None, None, 0) in rows
    assert ("write_file", "r2", "s2", 7) in rows


def test_log_tool_writes_one_row_per_execution(tmp_path):
    path = tmp_path / "tool_events.db"
    _log_tool("read_file", "safe", "ran", 1, run_id="run-1", session_id="sess-1", latency_ms=3, db_path=path)
    _log_tool("terminal", "confirm", "ran", 0, run_id="run-1", session_id="sess-1", latency_ms=9, db_path=path)
    conn = connect_tool_events(path)
    rows = conn.execute(
        "SELECT tool, risk_class, outcome, success, run_id, session_id FROM tool_events ORDER BY created_at"
    ).fetchall()
    conn.close()
    assert rows == [
        ("read_file", "safe", "ran", 1, "run-1", "sess-1"),
        ("terminal", "confirm", "ran", 0, "run-1", "sess-1"),
    ]


def test_log_request_records_tool_calls_emitted(tmp_path):
    cfg = SimpleNamespace(provider=SimpleNamespace(model="deepseek-chat", base_url="http://x"))
    result = SimpleNamespace(
        finish_reason="tool_calls", prompt_tokens=10, completion_tokens=5, latency_ms=42
    )
    loop_mod._log_request(cfg, result, tool_calls=3, run_id="run-1", db_path=tmp_path / "requests.db")
    conn = connect_requests(tmp_path / "requests.db")
    row = conn.execute(
        "SELECT task_class, tool_calls_emitted, run_id FROM requests"
    ).fetchone()
    conn.close()
    assert row == ("tool_call", 3, "run-1")


def test_log_request_records_zero_for_conversation(tmp_path):
    cfg = SimpleNamespace(provider=SimpleNamespace(model="m", base_url="u"))
    result = SimpleNamespace(
        finish_reason="stop", prompt_tokens=5, completion_tokens=2, latency_ms=10
    )
    loop_mod._log_request(cfg, result, tool_calls=0, run_id="run-2", db_path=tmp_path / "requests.db")
    conn = connect_requests(tmp_path / "requests.db")
    row = conn.execute("SELECT task_class, tool_calls_emitted FROM requests").fetchone()
    conn.close()
    assert row == ("conversation", 0)

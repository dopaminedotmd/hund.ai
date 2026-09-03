"""Root conftest isolation — no test may touch the real HundHome profile.

Regression context (2026-09-03): connector/approval tests and `_log_tool`
callers without an explicit db_path wrote test artifacts into the real
%LOCALAPPDATA%/hund profile (approvals connector 'ci-test', sessions
'SaaS Chat', tool_events run_id 'test-turn-123', dummy 'fastapi-envelope'
skills). These tests pin the isolation contract: with the root autouse
fixture active, default-path writes land inside the per-test HUND_HOME.
"""
from __future__ import annotations

import os
from pathlib import Path

from hund.agent.tool_dispatch import _log_tool
from hund.paths import hund_home, tool_events_db_path
from hund.store.sqlite import connect, connect_tool_events


def test_default_home_resolves_from_isolated_env() -> None:
    """hund_home() must follow HUND_HOME, which the root fixture redirects."""
    assert hund_home() == Path(os.environ["HUND_HOME"])
    assert hund_home() != Path(os.environ["LOCALAPPDATA"]) / "hund"


def test_log_tool_without_db_path_writes_into_isolated_home() -> None:
    """_log_tool default path lands in the isolated home, not the real one."""
    _log_tool("read_file", "safe", "content", success=1, run_id="iso-regression")
    conn = connect_tool_events()
    rows = conn.execute(
        "SELECT tool, run_id FROM tool_events WHERE run_id = 'iso-regression'"
    ).fetchall()
    conn.close()
    assert rows == [("read_file", "iso-regression")]


def test_connect_default_lands_inside_hund_home() -> None:
    """connect() without db_path must create hund.db inside the isolated home."""
    conn = connect()
    conn.execute(
        "INSERT INTO gap_events (id, created_at) VALUES ('iso-1', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    assert (hund_home() / "hund.db").exists()
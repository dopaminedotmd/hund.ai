"""Root test isolation — every test runs against a throwaway HundHome.

Regression context (2026-09-03): connector/approval tests and `_log_tool`
callers without an explicit db_path wrote test artifacts into the real user
profile (%LOCALAPPDATA%/hund): approvals with connector 'ci-test', sessions
titled 'SaaS Chat', tool_events rows with run_id 'test-turn-123', and dummy
'fastapi-envelope' skills landed in the production vault and telemetry.

This autouse fixture makes an isolated home the DEFAULT for the whole suite.
Tests that need a specific home still override via their own monkeypatch /
patch calls (env vars set later in the test body win over fixture values).
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_hund_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force every test to use a throwaway HundHome, never the real profile.

    The home lives in the pytest temp root (NOT inside the per-test tmp_path,
    which many tests treat as a pristine workspace and assert on).
    """
    home = tmp_path_factory.mktemp("hund-home", numbered=True)
    monkeypatch.setenv("HUND_HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    return home
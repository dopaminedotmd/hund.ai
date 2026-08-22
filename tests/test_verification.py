"""Tests for verification.py — command classifier and verification event emitter.

Tests are pure: classify_verification needs no DB, no provider, no network.
emit_verification_events tests use tempdir isolation for trace DB.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# --- classify_verification: pure function tests ---

def test_classify_pytest():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("pytest") == VerificationKind.TEST
    assert classify_verification("pytest tests/") == VerificationKind.TEST
    assert classify_verification("pytest -x -q") == VerificationKind.TEST


def test_classify_pytest_via_module():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("python -m pytest") == VerificationKind.TEST
    assert classify_verification("python -m pytest -v") == VerificationKind.TEST


def test_classify_pytest_via_uv():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("uv run pytest") == VerificationKind.TEST
    assert classify_verification("uv run pytest --tb=short") == VerificationKind.TEST


def test_classify_ruff_lint():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("ruff check .") == VerificationKind.LINT
    assert classify_verification("ruff format --check") == VerificationKind.LINT


def test_classify_mypy_typecheck():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("mypy hund/") == VerificationKind.TYPECHECK


def test_classify_npm_build():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("npm run build") == VerificationKind.BUILD


def test_classify_cargo_test():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("cargo test") == VerificationKind.TEST
    assert classify_verification("cargo build") == VerificationKind.BUILD


def test_classify_make_check():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("make check") == VerificationKind.TEST
    assert classify_verification("make test") == VerificationKind.TEST
    assert classify_verification("make build") == VerificationKind.BUILD


def test_classify_none_for_non_verification():
    from hund.agent.verification import classify_verification, VerificationKind

    for cmd in [
        "ls -la",
        "cat README.md",
        "git status",
        "git diff",
        "echo hello",
        "cd /tmp",
        "",
        "   ",
        "pip install foo",
    ]:
        assert classify_verification(cmd) == VerificationKind.NONE, f"failed for: {cmd!r}"


def test_classify_word_boundary_prevents_false_positive():
    """pytestx should NOT match pytest."""
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("pytestx") == VerificationKind.NONE
    assert classify_verification("mypy2") == VerificationKind.NONE
    assert classify_verification("ruffian") == VerificationKind.NONE


def test_classify_echo_pytest_is_not_verification():
    """echo pytest should NOT be classified as a test run."""
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("echo pytest") == VerificationKind.NONE
    assert classify_verification("echo 'running pytest'") == VerificationKind.NONE


def test_classify_strips_multiple_shell_prefixes():
    """python uv run pytest should still classify correctly after stripping."""
    from hund.agent.verification import classify_verification, VerificationKind

    # 'python uv run pytest' -> strip 'python ' -> 'uv run pytest' -> strip 'uv run ' -> 'pytest'
    assert classify_verification("python uv run pytest") == VerificationKind.TEST


# --- emit_verification_events: trace integration tests ---

def _isolate_db(monkeypatch, tmp_path: Path) -> None:
    import hund.paths as paths

    monkeypatch.setattr(paths, "hund_home", lambda: tmp_path)
    monkeypatch.setattr(paths, "db_path", lambda: tmp_path / "hund.db")


def test_emit_verification_events_for_pytest(tmp_path, monkeypatch):
    _isolate_db(monkeypatch, tmp_path)
    from hund.agent.verification import emit_verification_events
    from hund.trace.events import list_events_by_run

    count = emit_verification_events(
        command="pytest tests/test_foo.py",
        exit_code=0,
        stdout_summary="3 passed in 1.2s",
        workspace_id="ws-test",
        session_id="sess-test",
        run_id="run-emit-test",
    )
    assert count == 2  # verification_started + verification_completed

    events = list_events_by_run("run-emit-test")
    types = [e.event_type for e in events]
    assert "verification_started" in types
    assert "verification_completed" in types

    completed = next(e for e in events if e.event_type == "verification_completed")
    assert completed.payload_redacted["verification_kind"] == "test"
    assert completed.payload_redacted["passed"] is True
    assert completed.payload_redacted["exit_code"] == 0
    assert "evidence_hash" in completed.payload_redacted
    assert len(completed.payload_redacted["evidence_hash"]) == 64  # sha256 hex


def test_emit_returns_zero_for_non_verification(tmp_path, monkeypatch):
    _isolate_db(monkeypatch, tmp_path)
    from hund.agent.verification import emit_verification_events

    count = emit_verification_events(
        command="ls -la",
        exit_code=0,
        stdout_summary="",
        workspace_id="ws",
        session_id="sess",
        run_id="run-none",
    )
    assert count == 0


def test_emit_verification_failed_test(tmp_path, monkeypatch):
    _isolate_db(monkeypatch, tmp_path)
    from hund.agent.verification import emit_verification_events
    from hund.trace.events import list_events_by_run

    emit_verification_events(
        command="pytest tests/test_broken.py",
        exit_code=1,
        stdout_summary="1 failed in 0.5s",
        workspace_id="ws",
        session_id="sess",
        run_id="run-fail",
    )
    events = list_events_by_run("run-fail")
    completed = next(e for e in events if e.event_type == "verification_completed")
    assert completed.payload_redacted["passed"] is False
    assert completed.payload_redacted["exit_code"] == 1

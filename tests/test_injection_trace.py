"""Tests for injection_trace.py — isolated wrapper for injection event emission.

These tests verify the wrapper logic WITHOUT requiring prompt_builder or
trace.events integration. They test emit_injection_events and scan_and_emit
in isolation.
"""
from __future__ import annotations

from hund.agent.injection_trace import emit_injection_events, scan_and_emit


def test_emit_returns_zero_for_empty_hits():
    count = emit_injection_events(
        hits=[],
        workspace_id="ws",
        session_id="sess",
        run_id="run",
    )
    assert count == 0


def test_classify_verification_pytest():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("pytest tests/test_foo.py") == VerificationKind.TEST
    assert classify_verification("python -m pytest") == VerificationKind.TEST
    assert classify_verification("uv run pytest -x") == VerificationKind.TEST


def test_classify_verification_lint():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("ruff check src/") == VerificationKind.LINT
    assert classify_verification("flake8 .") == VerificationKind.LINT


def test_classify_verification_typecheck():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("mypy hund/") == VerificationKind.TYPECHECK
    assert classify_verification("tsc --noEmit") == VerificationKind.TYPECHECK


def test_classify_verification_build():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("npm run build") == VerificationKind.BUILD
    assert classify_verification("cargo build --release") == VerificationKind.BUILD


def test_classify_verification_none():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("ls -la") == VerificationKind.NONE
    assert classify_verification("echo pytest") == VerificationKind.NONE
    assert classify_verification("cat README.md") == VerificationKind.NONE
    assert classify_verification("") == VerificationKind.NONE
    assert classify_verification("git status") == VerificationKind.NONE


def test_classify_verification_strips_shell_prefix():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("uv run pytest") == VerificationKind.TEST
    assert classify_verification("python pytest tests/") == VerificationKind.TEST
    assert classify_verification("npx eslint .") == VerificationKind.LINT


def test_classify_verification_word_boundary():
    """Verifier prefix must be followed by space/option/end, not more chars."""
    from hund.agent.verification import classify_verification, VerificationKind

    # 'pytestx' should NOT match as pytest
    assert classify_verification("pytestx") == VerificationKind.NONE
    # 'mypy2' should NOT match as mypy
    assert classify_verification("mypy2") == VerificationKind.NONE


def test_classify_verification_make_check():
    from hund.agent.verification import classify_verification, VerificationKind

    assert classify_verification("make check") == VerificationKind.TEST
    assert classify_verification("make test") == VerificationKind.TEST
    assert classify_verification("make build") == VerificationKind.BUILD

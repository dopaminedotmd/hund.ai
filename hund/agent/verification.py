"""Verification classifier — detects when terminal tool calls are verification actions.

Purpose: The agent loop currently has no concept of "verification". When Hund
runs `pytest`, `ruff`, or `mypy`, it's just another terminal call. This module
classifies terminal commands as verification actions so trace events can
distinguish "agent verified" from "agent claimed".

This is a HEURISTIC, not a guarantee. It pattern-matches command prefixes.
False positives are possible (e.g., `echo pytest`). Mitigation: only classify
when command STARTS with a known verifier (after stripping leading whitespace
and common shell prefixes).

Design: pure functions. No trace side effects in classify(). The emit function
is separate so callers control when trace events are written.

Usage by Codex (recommended integration point):
  In tool_dispatch.py, after tool_call_completed for tool_name == "terminal":

      from .verification import classify_and_emit
      classify_and_emit(
          command=args.get("command", ""),
          exit_code=0 if success else 1,
          stdout=result[:500],
          workspace_id=workspace_id,
          session_id=session_id,
          run_id=run_id,
      )
"""
from __future__ import annotations

import enum
from typing import Any


class VerificationKind(str, enum.Enum):
    """What kind of verification a command represents."""

    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    BUILD = "build"
    NONE = "none"


# Verifier patterns: (prefix_pattern, kind)
# Ordered by specificity. First match wins.
# Patterns are matched against the command after stripping shell prefixes.
_VERIFIERS: list[tuple[str, VerificationKind]] = [
    # Test runners
    ("pytest", VerificationKind.TEST),
    ("-m pytest", VerificationKind.TEST),
    ("-m unittest", VerificationKind.TEST),
    ("python -m pytest", VerificationKind.TEST),
    ("python3 -m pytest", VerificationKind.TEST),
    ("python -m unittest", VerificationKind.TEST),
    ("npm test", VerificationKind.TEST),
    ("npm run test", VerificationKind.TEST),
    ("yarn test", VerificationKind.TEST),
    ("cargo test", VerificationKind.TEST),
    ("go test", VerificationKind.TEST),
    ("make test", VerificationKind.TEST),
    ("make check", VerificationKind.TEST),
    ("tox", VerificationKind.TEST),
    ("nox", VerificationKind.TEST),
    # Linters
    ("ruff", VerificationKind.LINT),
    ("flake8", VerificationKind.LINT),
    ("pylint", VerificationKind.LINT),
    ("eslint", VerificationKind.LINT),
    ("rubocop", VerificationKind.LINT),
    ("shellcheck", VerificationKind.LINT),
    # Type checkers
    ("mypy", VerificationKind.TYPECHECK),
    ("pyright", VerificationKind.TYPECHECK),
    ("tsc", VerificationKind.TYPECHECK),
    ("pyre", VerificationKind.TYPECHECK),
    # Builders
    ("npm run build", VerificationKind.BUILD),
    ("cargo build", VerificationKind.BUILD),
    ("make build", VerificationKind.BUILD),
    ("go build", VerificationKind.BUILD),
    ("cmake", VerificationKind.BUILD),
    ("webpack", VerificationKind.BUILD),
    ("vite build", VerificationKind.BUILD),
]

# Shell prefixes to strip before matching
_SHELL_PREFIXES = (
    "uv run ",
    "python ",
    "python3 ",
    "py ",
    "npx ",
    "yarn ",
    "deno ",
    "bun ",
)


def _normalize_command(command: str) -> str:
    """Strip shell prefixes and leading whitespace for matching."""
    cmd = command.strip()
    changed = True
    while changed:
        changed = False
        for prefix in _SHELL_PREFIXES:
            if cmd.startswith(prefix):
                cmd = cmd[len(prefix):].strip()
                changed = True
                break
    return cmd


def classify_verification(command: str) -> VerificationKind:
    """Classify a terminal command as verification or not.

    Returns VerificationKind.NONE if the command is not a recognized
    verification action.

    This is heuristic. It matches the START of the normalized command
    against known verifier prefixes. This avoids false positives from
    verifier names appearing mid-command (e.g., `echo pytest`).
    """
    if not command or not command.strip():
        return VerificationKind.NONE

    normalized = _normalize_command(command)

    for pattern, kind in _VERIFIERS:
        if normalized.startswith(pattern):
            # Ensure it's a word boundary: next char should be space, end, or option
            rest = normalized[len(pattern):]
            if not rest or rest[0] in (" ", "-", "\t", "\n", "&", "|", ";"):
                return kind
    return VerificationKind.NONE


def emit_verification_events(
    *,
    command: str,
    exit_code: int,
    stdout_summary: str,
    workspace_id: str,
    session_id: str,
    run_id: str,
    policy_version: str = "1.0.0",
    turn_id: str | None = None,
    tool_name: str = "terminal",
) -> int:
    """Emit verification_started + verification_completed trace events.

    Only emits if the command is classified as verification. Returns 0
    if not verification, 2 if both events emitted successfully.

    Best-effort: trace failure does not raise.
    """
    kind = classify_verification(command)
    if kind == VerificationKind.NONE:
        return 0

    from ..trace.events import record_event

    emitted = 0
    try:
        import hashlib

        evidence_hash = hashlib.sha256(
            (command + "\n" + str(exit_code) + "\n" + stdout_summary).encode("utf-8")
        ).hexdigest()

        record_event(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            turn_id=turn_id,
            actor="hund",
            event_type="verification_started",
            policy_version=policy_version,
            payload_unredacted={
                "verification_kind": kind.value,
                "command": command,
            },
            tool_name=tool_name,
        )
        emitted += 1

        record_event(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            turn_id=turn_id,
            actor="hund",
            event_type="verification_completed",
            policy_version=policy_version,
            payload_unredacted={
                "verification_kind": kind.value,
                "command": command,
                "exit_code": exit_code,
                "passed": exit_code == 0,
                "stdout_redacted_summary": stdout_summary[:200],
                "evidence_hash": evidence_hash,
                "evidence_hash_algorithm": "sha256",
                "evidence_hash_input": "command + newline + str(exit_code) + newline + redacted_stdout",
            },
            tool_name=tool_name,
        )
        emitted += 1
    except Exception:
        pass

    return emitted


def classify_and_emit(
    *,
    command: str,
    exit_code: int,
    stdout_summary: str,
    workspace_id: str,
    session_id: str,
    run_id: str,
    policy_version: str = "1.0.0",
    turn_id: str | None = None,
    tool_name: str = "terminal",
) -> int:
    """Convenience: classify + emit in one call. Returns events emitted count."""
    return emit_verification_events(
        command=command,
        exit_code=exit_code,
        stdout_summary=stdout_summary,
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        policy_version=policy_version,
        turn_id=turn_id,
        tool_name=tool_name,
    )

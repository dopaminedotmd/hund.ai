"""Security specification for workspace auto-write classification."""
from __future__ import annotations

import pytest

from hund.agent.safety import PermissionEngine, RiskLevel


def test_ordinary_workspace_write_is_safe(tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "write_file",
        {"path": "src/app.py", "content": "print('ok')\n"},
    )

    assert decision.risk is RiskLevel.SAFE
    assert decision.allowed is True


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.example",
        "credentials.json",
        "private.key",
        ".github/workflows/release.yml",
    ],
)
def test_sensitive_write_path_requires_confirmation(path: str, tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "write_file",
        {"path": path, "content": "PLACEHOLDER=value\n"},
    )

    assert decision.risk is RiskLevel.CONFIRM
    assert decision.allowed is False
    assert decision.session_allowable is False


@pytest.mark.parametrize(
    "content",
    [
        "api_key=synthetic-secret-value",
        "token: synthetic-token-value",
        "-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----",
    ],
)
def test_plaintext_credentials_are_blocked(content: str, tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "write_file",
        {"path": "notes.txt", "content": content},
    )

    assert decision.risk is RiskLevel.BLOCKED
    assert decision.allowed is False


def test_missing_write_content_fails_closed(tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "write_file", {"path": "notes.txt"}
    )

    assert decision.risk is RiskLevel.BLOCKED
    assert decision.allowed is False


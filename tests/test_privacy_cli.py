"""Privacy CLI — offline preview av redaction."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from hund.main import app


def test_privacy_check_redacts_text_option():
    secret = "s" + "k-" + ("d" * 32)
    result = CliRunner().invoke(app, ["privacy", "check", "--text", f"token {secret}"])
    assert result.exit_code == 0
    assert secret not in result.output
    assert "[REDACTED:secret]" in result.output
    assert "risk: review_required" in result.output


def test_privacy_check_requires_input():
    result = CliRunner().invoke(app, ["privacy", "check"])
    assert result.exit_code != 0
    assert "ange --text eller --file" in result.output.lower()


def test_privacy_preview_export_is_structured_only_json():
    secret = "s" + "k-" + ("f" * 32)
    result = CliRunner().invoke(app, ["privacy", "preview-export", "--text", f"token {secret}"])
    assert result.exit_code == 0
    assert secret not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["contains_text"] is False
    assert payload["risk_level"] == "review_required"
    assert "secret" in payload["blocked_fields"]

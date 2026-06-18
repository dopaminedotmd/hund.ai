"""Redactor TCB — deterministisk privacy-sanitizer före export/upload."""
from __future__ import annotations

from hund_cli.learning.redactor import build_export_preview, redact_text


def test_redacts_common_secret_shapes():
    openai_like = "s" + "k-" + ("a" * 32)
    github_like = "g" + "hp_" + ("b" * 36)
    raw = f"api_key={openai_like} and token={github_like}"
    result = redact_text(raw)
    assert openai_like not in result.text
    assert github_like not in result.text
    assert "[REDACTED:secret]" in result.text
    assert "secret" in result.blocked_fields
    assert result.risk_level in {"review_required", "blocked"}


def test_redacts_email_and_windows_paths():
    raw = r"Mail william@example.com ligger i C:\Users\willi\Desktop\kund\secret.txt"
    result = redact_text(raw)
    assert "william@example.com" not in result.text
    assert r"C:\Users\willi" not in result.text
    assert "[REDACTED:email]" in result.text
    assert "[REDACTED:path]" in result.text
    assert set(result.blocked_fields) >= {"email", "path"}


def test_truncates_long_raw_output():
    raw = "x" * 6000
    result = redact_text(raw, max_chars=1000)
    assert len(result.text) < 1200
    assert result.text.endswith("[TRUNCATED]")
    assert "long_text" in result.blocked_fields


def test_safe_text_stays_safe():
    raw = "tool call failed because pytest was missing"
    result = redact_text(raw)
    assert result.text == raw
    assert result.blocked_fields == []
    assert result.risk_level == "safe"


def test_export_preview_is_structured_only():
    secret = "s" + "k-" + ("e" * 32)
    raw = f"user text {secret} william@example.com"
    payload = build_export_preview(raw, source="test")
    rendered = str(payload)
    assert secret not in rendered
    assert "william@example.com" not in rendered
    assert "[REDACTED:secret]" not in rendered
    assert payload["schema_version"] == 1
    assert payload["source"] == "test"
    assert payload["risk_level"] == "review_required"
    assert set(payload["blocked_fields"]) >= {"secret", "email"}
    assert payload["contains_text"] is False

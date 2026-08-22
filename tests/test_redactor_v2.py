"""Tests for Redactor v2 — extended patterns and RedactableConfig."""

from __future__ import annotations

from hund.learning.redactor_v2 import redact_text_v2, RedactableConfig


# ── V2 patterns ────────────────────────────────────────────────────


def test_redacts_ipv4():
    result = redact_text_v2("Server: 192.168.1.1")
    assert "[REDACTED:ip]" in result.text
    assert "ip_addresses" in result.blocked_fields


def test_redacts_ipv6():
    result = redact_text_v2("IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334")
    assert "[REDACTED:ip]" in result.text
    assert "ip_addresses" in result.blocked_fields


def test_redacts_phone():
    result = redact_text_v2("Call +46 70 123 45 67")
    assert "[REDACTED:phone]" in result.text
    assert "phone_numbers" in result.blocked_fields


def test_redacts_uuid():
    result = redact_text_v2("ID: 550e8400-e29b-41d4-a716-446655440000")
    assert "[REDACTED:uuid]" in result.text
    assert "uuids" in result.blocked_fields


def test_redacts_swedish_ssn():
    result = redact_text_v2("SSN: 19900101-1234")
    assert "[REDACTED:personnummer]" in result.text
    assert "swedish_ssn" in result.blocked_fields


def test_redacts_access_key():
    result = redact_text_v2("AWS: AKIAIOSFODNN7EXAMPLE")
    assert "[REDACTED:access_key]" in result.text
    assert "access_keys" in result.blocked_fields


def test_redacts_date_path():
    result = redact_text_v2("Path: /logs/2024-01-15/events")
    assert "[REDACTED:date]" in result.text
    assert "date_paths" in result.blocked_fields


def test_redacts_base64():
    b64 = "SGVsbG8gV29ybGQgVGhpcyBpcyBhIGxvbmcgYmFzZTY0IHRlc3Qgc3RyaW5n"
    result = redact_text_v2(f"Data: {b64}")
    assert "[REDACTED:base64]" in result.text
    assert "base64_strings" in result.blocked_fields


def test_redacts_url_query_params():
    result = redact_text_v2("URL: https://example.com/api?key=abc123&token=secret")
    assert "[REDACTED:query]" in result.text
    assert "url_query" in result.blocked_fields
    assert "https://example.com" in result.text  # base URL preserved


# ── Config control ─────────────────────────────────────────────────


def test_config_disables_ip():
    config = RedactableConfig(ip_addresses=False)
    result = redact_text_v2("IP: 192.168.1.1", config=config)
    assert "[REDACTED:ip]" not in result.text


def test_config_disables_phone():
    config = RedactableConfig(phone_numbers=False)
    result = redact_text_v2("Phone: +46 70 123 45 67", config=config)
    assert "[REDACTED:phone]" not in result.text


def test_config_disables_uuid():
    config = RedactableConfig(uuids=False)
    result = redact_text_v2("UUID: 550e8400-e29b-41d4-a716-446655440000", config=config)
    assert "[REDACTED:uuid]" not in result.text


def test_config_disables_ssn():
    config = RedactableConfig(swedish_ssn=False)
    result = redact_text_v2("SSN: 19900101-1234", config=config)
    assert "[REDACTED:personnummer]" not in result.text


# ── V1 compatibility ───────────────────────────────────────────────


def test_v1_secrets_still_active():
    """V1 secrets patterns should still be redacted."""
    result = redact_text_v2("Key: sk-my-long-enough-secret-key-for-v1")
    assert "[REDACTED:secret]" in result.text
    assert "secret" in result.blocked_fields


def test_v1_email_still_active():
    result = redact_text_v2("Email: user@example.com")
    assert "[REDACTED:email]" in result.text


def test_v1_windows_path_still_active():
    result = redact_text_v2("Path: C:\\Users\\test\\file.txt")
    assert "[REDACTED:path]" in result.text


# ── Risk levels ────────────────────────────────────────────────────


def test_risk_safe_on_clean_text():
    result = redact_text_v2("Hello world, nothing sensitive here.")
    assert result.risk_level == "safe"
    assert result.blocked_fields == []


def test_risk_blocked_for_high_risk_patterns():
    """Access keys and base64 trigger 'blocked' risk level."""
    result = redact_text_v2("AWS: AKIAIOSFODNN7EXAMPLE")
    assert result.risk_level == "blocked"


def test_risk_review_required_for_medium():
    result = redact_text_v2("Contact: user@example.com, 192.168.1.1")
    assert result.risk_level == "review_required"


# ── Edge cases ─────────────────────────────────────────────────────


def test_empty_text():
    result = redact_text_v2("")
    assert result.text == ""
    assert result.risk_level == "safe"


def test_no_false_positives():
    """Common safe patterns should not be redacted."""
    result = redact_text_v2("Version 1.2.3-alpha build 2024")
    assert result.risk_level == "safe"


def test_redactable_config_default_all_enabled():
    config = RedactableConfig()
    assert config.ip_addresses is True
    assert config.phone_numbers is True
    assert config.uuids is True

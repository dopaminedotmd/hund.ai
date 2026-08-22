"""Tests for auth envelope — HMAC signing, verify, replay protection."""

from pathlib import Path
import pytest

from hund.connector.auth import (
    sign,
    verify,
    VerifyResult,
    ReplayCache,
    generate_secret,
    save_secret,
    load_secret,
)
from hund.connector.intent import IntentRequest


def _make_intent(**kwargs) -> IntentRequest:
    """Create an IntentRequest with current timestamp for testing."""
    from datetime import datetime, timezone

    defaults = dict(
        workspace_id="ws1",
        connector_id="c1",
        intent_type="tool_call",
        tool_name="read_file",
        nonce="fixed-nonce",
        timestamp=datetime.now(timezone.utc).isoformat(),
        expires_at="",
    )
    defaults.update(kwargs)
    return IntentRequest(**defaults)


def test_sign_and_verify_roundtrip():
    secret = "test-secret-123"
    intent = _make_intent()
    intent.signature = sign(intent, secret)
    result = verify(intent, secret)
    assert result.valid is True


def test_verify_fails_on_wrong_secret():
    secret = "test-secret-123"
    wrong = "wrong-secret"
    intent = _make_intent()
    intent.signature = sign(intent, secret)
    result = verify(intent, wrong)
    assert result.valid is False
    assert "signature mismatch" in result.reason


def test_verify_fails_on_missing_signature():
    intent = _make_intent()
    result = verify(intent, "secret")
    assert result.valid is False
    assert "missing signature" in result.reason


def test_verify_fails_on_tampered_intent():
    secret = "test-secret"
    intent = _make_intent(tool_name="read_file")
    intent.signature = sign(intent, secret)
    # Tamper: change tool_name after signing
    intent.tool_name = "write_file"
    result = verify(intent, secret)
    assert result.valid is False
    assert "signature mismatch" in result.reason


def test_verify_fails_on_stale_timestamp():
    secret = "test-secret"
    intent = _make_intent(
        timestamp="2020-01-01T00:00:00+00:00"  # 6+ years ago
    )
    intent.signature = sign(intent, secret)
    result = verify(intent, secret)
    assert result.valid is False
    assert "timestamp" in result.reason


def test_verify_fails_on_expired_intent():
    """expires_at in the past should fail."""
    import time
    from datetime import datetime, timezone

    past = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    secret = "test-secret"
    intent = _make_intent(expires_at=past)
    intent.signature = sign(intent, secret)
    result = verify(intent, secret)
    assert result.valid is False
    assert "expired" in result.reason


def test_replay_cache_detects_duplicate_nonce():
    secret = "test-secret"
    cache = ReplayCache()
    intent = _make_intent(nonce="unique-nonce-1")
    intent.signature = sign(intent, secret)

    # First use: valid
    result1 = verify(intent, secret, replay_cache=cache)
    assert result1.valid is True

    # Second use: rejected as replay
    result2 = verify(intent, secret, replay_cache=cache)
    assert result2.valid is False
    assert "replayed" in result2.reason


def test_replay_cache_without_cache_allows_reuse():
    """Without replay cache, same nonce is allowed."""
    secret = "test-secret"
    intent = _make_intent(nonce="same-nonce")
    intent.signature = sign(intent, secret)

    result1 = verify(intent, secret)
    assert result1.valid is True
    result2 = verify(intent, secret)
    assert result2.valid is True


def test_replay_cache_capacity():
    cache = ReplayCache(max_size=3)
    cache.add("a")
    cache.add("b")
    cache.add("c")
    # 4th should trigger clear (len >= max_size)
    cache.add("d")
    # After clear, "a" should NOT be in cache anymore
    assert "a" not in cache
    assert "d" in cache


def test_generate_secret_length():
    s = generate_secret()
    assert len(s) == 64  # SHA256 hex = 64 chars


def test_save_and_load_secret(tmp_path):
    secret = "my-test-secret"
    path = tmp_path / "connector" / "key.json"
    save_secret(secret, path)
    assert path.exists()
    loaded = load_secret(path)
    assert loaded == secret


def test_load_secret_missing(tmp_path):
    path = tmp_path / "nonexistent.json"
    loaded = load_secret(path)
    assert loaded is None

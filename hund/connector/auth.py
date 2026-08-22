"""Auth envelope — HMAC signing, nonce verification, replay protection."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .intent import IntentRequest

_TIMESTAMP_WINDOW_S = 60  # ±60 seconds


@dataclass
class VerifyResult:
    valid: bool
    reason: str = ""


def canonical_bytes(intent: IntentRequest) -> bytes:
    """Canonical UTF-8 bytes for HMAC signing."""
    return intent.canonical_signing_string().encode("utf-8")


def sign(intent: IntentRequest, secret: str) -> str:
    """HMAC-SHA256 sign intent. Returns hex digest."""
    return hmac.new(
        secret.encode("utf-8"),
        canonical_bytes(intent),
        hashlib.sha256,
    ).hexdigest()


def _parse_timestamp(ts: str) -> float:
    """Parse ISO8601 timestamp to Unix epoch float. Returns 0 on failure."""
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def verify(
    intent: IntentRequest,
    secret: str,
    replay_cache: set[str] | None = None,
) -> VerifyResult:
    """Verify intent signature + nonce freshness + timestamp window.

    Args:
        intent: Signed IntentRequest.
        secret: Shared HMAC secret.
        replay_cache: Optional set of seen nonces. If provided, nonce
                      uniqueness is checked.

    Returns:
        VerifyResult with valid flag + reason on failure.
    """
    # 1. Verify signature exists
    if not intent.signature:
        return VerifyResult(False, "missing signature")

    # 2. Verify timestamp window
    ts = _parse_timestamp(intent.timestamp)
    now = time.time()
    if abs(now - ts) > _TIMESTAMP_WINDOW_S:
        return VerifyResult(False, "timestamp outside ±60s window")

    # 3. Verify expiration
    if intent.expires_at:
        exp = _parse_timestamp(intent.expires_at)
        if exp > 0 and now > exp:
            return VerifyResult(False, "intent expired")

    # 4. Verify nonce uniqueness (replay protection)
    if replay_cache is not None and intent.nonce in replay_cache:
        return VerifyResult(False, "nonce replayed")
    if replay_cache is not None:
        replay_cache.add(intent.nonce)

    # 5. Verify HMAC signature
    expected = sign(intent, secret)
    if not hmac.compare_digest(intent.signature, expected):
        return VerifyResult(False, "signature mismatch")

    return VerifyResult(True)


class ReplayCache:
    """In-memory replay cache with capacity limit.

    Nonces live until explicitly cleared or until the cache is full.
    Not persistent across process restarts (acceptable for Phase 4).
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self._seen: set[str] = set()
        self._max_size = max_size

    def contains(self, nonce: str) -> bool:
        return nonce in self._seen

    def add(self, nonce: str) -> None:
        if len(self._seen) >= self._max_size:
            self._seen.clear()
        self._seen.add(nonce)

    def __contains__(self, nonce: str) -> bool:
        return self.contains(nonce)


def generate_secret() -> str:
    """Generate a new random HMAC secret (64 hex chars = 256 bits)."""
    return hashlib.sha256(str(__import__("uuid").uuid4()).encode()).hexdigest()


def save_secret(secret: str, path: Path) -> None:
    """Save secret to OS-protected file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"secret": secret}), encoding="utf-8")
    # Best-effort file permissions (Windows ACL not managed here)
    try:
        path.chmod(0o600)
    except Exception:
        pass


def load_secret(path: Path) -> str | None:
    """Load secret from file. Return None if missing."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("secret", ""))
    except (json.JSONDecodeError, OSError):
        return None

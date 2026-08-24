"""Deterministic pre-filter gate for evidence before LLM evaluation.

Drops exact duplicates, noise, and trivial outputs with 0 LLM tokens.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence


def _compute_hash(text: str) -> str:
    """Compute sha256 hash of normalized text."""
    normalized = " ".join(text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Trivial noise patterns that should never be evaluated as knowledge
TRIVIAL_NOISE_PATTERNS = [
    r"^(ok|yes|no|done|thanks|tack|bra|ja|nej)\.?$",
    r"^(\d+\s*files?\s*changed|\d+\s*insertions?|\d+\s*deletions?)$",
    r"^(exit\s*status\s*0|success|completed\s*successfully)$",
    r"^ls\s*-la|cd\s+.*|pwd|dir$",
]


def is_trivial_noise(text: str) -> bool:
    """Check if the text represents trivial ephemeral command noise."""
    t = text.strip()
    if len(t) < 4:
        return True
    t_lower = t.lower()
    for pat in TRIVIAL_NOISE_PATTERNS:
        if re.search(pat, t_lower):
            return True
    return False


def prefilter_evidence(
    events: Sequence[Any],
    existing_rules: Sequence[str] | None = None,
) -> tuple[list[Any], list[str]]:
    """Filter evidence events before LLM evaluation.

    Returns (accepted_events, rejected_reasons).
    """
    accepted: list[Any] = []
    reasons: list[str] = []

    # Build lookup of existing rule hashes
    existing_hashes: set[str] = set()
    if existing_rules:
        for r in existing_rules:
            existing_hashes.add(_compute_hash(r))

    seen_hashes: set[str] = set()

    for evt in events:
        # Extract payload or text
        if hasattr(evt, "payload"):
            payload = evt.payload
        elif isinstance(evt, dict):
            payload = evt.get("payload", "")
        else:
            payload = str(evt)

        # 1. Noise check
        if is_trivial_noise(payload):
            reasons.append(f"rejected: trivial noise '{payload[:30]}...'")
            continue

        h = _compute_hash(payload)

        # 2. Existing knowledge exact duplicate check
        if h in existing_hashes:
            reasons.append(f"rejected: exact duplicate of existing knowledge '{payload[:30]}...'")
            continue

        # 3. Within-batch duplicate check
        if h in seen_hashes:
            reasons.append(f"rejected: duplicate within current turn batch '{payload[:30]}...'")
            continue

        seen_hashes.add(h)
        accepted.append(evt)

    return accepted, reasons

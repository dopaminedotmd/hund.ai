"""Deterministic source tiering, source reputation, and multi-source corroboration gates."""
from __future__ import annotations

from enum import Enum
from urllib.parse import urlparse
from typing import Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from .research_packet import ResearchSourceRecord


class SourceTier(str, Enum):
    TIER_1_OFFICIAL = "tier_1_official"
    TIER_2_REPUTABLE = "tier_2_reputable"
    TIER_3_OPEN_SOURCE = "tier_3_open_source"
    TIER_4_COMMUNITY = "tier_4_community"


_OFFICIAL_DOMAINS = {
    "docs.python.org",
    "developer.mozilla.org",
    "docs.microsoft.com",
    "learn.microsoft.com",
    "cloud.google.com",
    "aws.amazon.com",
    "nodejs.org",
    "react.dev",
    "rust-lang.org",
    "go.dev",
    "w3.org",
    "ietf.org",
    "peps.python.org",
    "pytest.org",
    "pypi.org",
}

_REPUTABLE_DOMAINS = {
    "arxiv.org",
    "realpython.com",
    "martinfowler.com",
    "acm.org",
    "ieee.org",
    "oreilly.com",
    "digitalocean.com",
    "kernel.org",
    "towardsdatascience.com",
}

_OPEN_SOURCE_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    "crates.io",
    "npmjs.com",
}


def classify_source_tier(url: str, metadata: dict | None = None) -> SourceTier:
    """Classify external source URL into deterministic quality tier."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    for official in _OFFICIAL_DOMAINS:
        if host == official or host.endswith("." + official):
            return SourceTier.TIER_1_OFFICIAL

    for reputable in _REPUTABLE_DOMAINS:
        if host == reputable or host.endswith("." + reputable):
            return SourceTier.TIER_2_REPUTABLE

    for oss in _OPEN_SOURCE_DOMAINS:
        if host == oss or host.endswith("." + oss):
            return SourceTier.TIER_3_OPEN_SOURCE

    return SourceTier.TIER_4_COMMUNITY


def evaluate_corroboration(sources: Sequence[ResearchSourceRecord]) -> bool:
    """Evaluate whether candidate evidence meets multi-source corroboration requirement.

    Requires at least two independent source domains in Tier 1, 2, or 3.
    """
    valid_domains = set()
    for s in sources:
        tier_val = getattr(s, "source_tier", "")
        if isinstance(tier_val, SourceTier):
            tier_val = tier_val.value
        if tier_val in {
            SourceTier.TIER_1_OFFICIAL.value,
            SourceTier.TIER_2_REPUTABLE.value,
            SourceTier.TIER_3_OPEN_SOURCE.value,
        }:
            if s.domain:
                valid_domains.add(s.domain.lower())

    return len(valid_domains) >= 2

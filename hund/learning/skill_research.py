"""Bounded, privacy-safe research packet construction and query synthesis."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Callable, Optional
from urllib.parse import urlparse

from .injection_guard import sanitize_to_inert_claims, scan_untrusted_content
from .research_packet import (
    ResearchClaim,
    ResearchPacket,
    ResearchPacketStore,
    ResearchSourceRecord,
)
from .source_hierarchy import classify_source_tier, evaluate_corroboration

_URL_PATTERN = re.compile(r"https?://[^\s\"'>]+")
_PRIVATE_DATA_PATTERNS = [
    re.compile(r"[A-Za-z]:\\[^\s]+"),  # Windows paths
    re.compile(r"/(?:Users|home|root)/[^\s]+"),  # POSIX user paths
    re.compile(r"\b(?:sk-[a-zA-Z0-9_\-]{16,}|ghp_[a-zA-Z0-9]{16,}|bearer\s+[a-zA-Z0-9_\-\.]+)\b", re.I),
    re.compile(r"\b(?:william|admin|root|password|secret|private)\b", re.I),
]


def build_canonical_queries(domain: str, intent: str) -> list[str]:
    """Generate sanitized, canonical search queries without private paths, names or tokens."""
    clean_intent = intent
    for pat in _PRIVATE_DATA_PATTERNS:
        clean_intent = pat.sub(" ", clean_intent)

    words = re.findall(r"[a-zA-Z0-9_\-]+", clean_intent)
    stopwords = {"from", "with", "for", "and", "the", "this", "that", "every", "time", "turn", "run", "again"}
    filtered_words = [w.lower() for w in words if w.lower() not in stopwords and len(w) > 2]
    intent_summary = " ".join(filtered_words[:6]) or "best practices"

    queries = [
        f"{domain} {intent_summary} official guidance workflow",
        f"{domain} {intent_summary} best practices current",
    ]
    return queries


def perform_skill_research(
    need_id: str,
    capability_id: str,
    domain: str,
    intent: str,
    *,
    search_fn: Optional[Callable[[dict], str]] = None,
    db_path: Path | str | None = None,
    now: Optional[datetime] = None,
) -> ResearchPacket:
    """Execute bounded external research, scan for safety, and produce a ResearchPacket."""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    queries = build_canonical_queries(domain, intent)

    sources: list[ResearchSourceRecord] = []
    claims: list[ResearchClaim] = []
    safety_passed = True

    if search_fn is not None:
        for q in queries:
            try:
                raw_result = search_fn({"query": q})
            except Exception:
                continue

            scan = scan_untrusted_content(raw_result)
            if not scan.safe:
                safety_passed = False

            # Extract URLs and source records
            found_urls = _URL_PATTERN.findall(raw_result)
            for url in found_urls:
                clean_url = url.rstrip(".,);>")
                parsed = urlparse(clean_url)
                host = (parsed.hostname or "").lower()
                if not host:
                    continue

                tier = classify_source_tier(clean_url)
                content_hash = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()[:16]
                source_record = ResearchSourceRecord(
                    url=clean_url,
                    domain=host,
                    title=f"Source on {domain}",
                    retrieved_at=ts,
                    source_tier=tier.value,
                    content_hash=content_hash,
                )
                if not any(s.url == clean_url for s in sources):
                    sources.append(source_record)
                    # Extract claims
                    extracted = sanitize_to_inert_claims(raw_result, source_record)
                    claims.extend(extracted)

    is_corroborated = evaluate_corroboration(sources)
    status = "corroborated" if is_corroborated and safety_passed else "unresearched"

    packet_id = f"packet_{hashlib.sha256((need_id + capability_id + ts).encode('utf-8')).hexdigest()[:16]}"
    packet = ResearchPacket(
        packet_id=packet_id,
        need_id=need_id,
        capability_id=capability_id,
        domain=domain,
        canonical_queries=tuple(queries),
        sources=tuple(sources),
        claims=tuple(claims),
        conflicts=(),
        freshness_window_days=90,
        coverage_score=0.9 if is_corroborated else 0.5,
        safety_scan_passed=safety_passed,
        status=status,
    )

    if db_path is not None:
        store = ResearchPacketStore(db_path)
        store.save_packet(packet)

    return packet

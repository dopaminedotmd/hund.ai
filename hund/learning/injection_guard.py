"""Untrusted-content isolation, prompt injection scanning, and claim sanitization."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from .research_packet import ResearchClaim, ResearchSourceRecord


_INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts)", re.I), "prompt_injection"),
    (re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.I), "prompt_injection"),
    (re.compile(r"system\s*instruction\s*:", re.I), "prompt_injection"),
    (re.compile(r"<\s*script[^>]*>", re.I), "script_tag"),
    (re.compile(r"eval\s*\(", re.I), "code_execution_payload"),
    (re.compile(r"exec\s*\(", re.I), "code_execution_payload"),
    (re.compile(r"__import__\s*\(", re.I), "code_execution_payload"),
    (re.compile(r"os\.system\s*\(", re.I), "code_execution_payload"),
    (re.compile(r"subprocess\.(?:Popen|run|call)", re.I), "code_execution_payload"),
    (re.compile(r"rm\s+-rf\s+[/~]", re.I), "destructive_shell_payload"),
]


@dataclass(frozen=True)
class SafetyScanResult:
    safe: bool
    flags: tuple[str, ...]
    details: str = ""


def scan_untrusted_content(text: str) -> SafetyScanResult:
    """Scan external content for prompt injection, script execution, and exploit attempts."""
    flags = []
    for pattern, flag in _INJECTION_PATTERNS:
        if pattern.search(text):
            flags.append(flag)

    flags_tuple = tuple(sorted(set(flags)))
    return SafetyScanResult(
        safe=len(flags_tuple) == 0,
        flags=flags_tuple,
        details=f"Flags detected: {', '.join(flags_tuple)}" if flags_tuple else "Clean",
    )


def sanitize_to_inert_claims(raw_text: str, source: ResearchSourceRecord) -> list[ResearchClaim]:
    """Parse raw external text into inert, sanitized procedural and factual claims.

    Removes code execution payloads, strips prompt injections, and abstracts actionable steps.
    """
    from .research_packet import ResearchClaim

    claims: list[ResearchClaim] = []
    # Split text into candidate sentences or bullet points
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    for line in lines:
        # Split line by sentences/clauses
        segments = re.split(r"(?<=[.!?])\s+", line)
        for seg in segments:
            seg_clean = seg.strip()
            if not seg_clean:
                continue

            # Strip script tags
            seg_clean = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", seg_clean, flags=re.I)
            # Remove any dangerous code execution calls entirely
            seg_clean = re.sub(
                r"(?:eval|exec|__import__|os\.system|subprocess\.\w+)\s*\([^)]*(?:\([^)]*\))*[^)]*\)",
                "",
                seg_clean,
                flags=re.I,
            )
            # Remove any trailing dangling quotes or unmatched calls
            seg_clean = re.sub(r"\b(?:eval|exec|system|subprocess)\b\s*\([^)]*\)", "", seg_clean, flags=re.I)
            seg_clean = " ".join(seg_clean.split()).strip(" .,:;")

            if len(seg_clean) < 15:
                continue

            scan = scan_untrusted_content(seg_clean)
            if not scan.safe:
                continue

            claim_hash = hashlib.sha256((source.url + "\x1f" + seg_clean).encode("utf-8")).hexdigest()[:16]
            claims.append(
                ResearchClaim(
                    claim_id=f"claim_{claim_hash}",
                    text=seg_clean,
                    source_urls=(source.url,),
                    corroboration_count=1,
                    confidence=0.85,
                    freshness_timestamp=source.retrieved_at,
                    is_procedural=bool(re.search(r"\b(?:step|configure|set|initialize|use|run|apply|create|verify)\b", seg_clean, re.I)),
                )
            )

    return claims

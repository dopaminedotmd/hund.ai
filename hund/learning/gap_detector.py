"""Deterministic epistemic-gap signals; no model guessing."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from ..tools.types import ToolResult, ToolStatus


@dataclass(frozen=True)
class EvidenceGap:
    kind: str
    study_target: str
    source: str


_VERSION = re.compile(
    r"\b(latest|current|senaste|version|deprecated(?: in)?|rekommenderad version)\b",
    re.IGNORECASE,
)
_SYMBOL = re.compile(r"\b(?:import|from|symbol|class|function)\s+([A-Za-z_][\w.]*)")


def detect_evidence_gaps(
    user_message: str,
    *,
    tool_results: Iterable[ToolResult] = (),
    local_search_failed: bool = False,
    dependency_versions_known: bool = True,
    contradictory_evidence: bool = False,
) -> tuple[EvidenceGap, ...]:
    gaps: list[EvidenceGap] = []
    if _VERSION.search(user_message):
        gaps.append(EvidenceGap("version_volatility", "official current source", "prompt"))
    symbol = _SYMBOL.search(user_message)
    if symbol and local_search_failed:
        gaps.append(EvidenceGap("unknown_symbol", symbol.group(1)[:120], "local_search"))
    if not dependency_versions_known:
        gaps.append(EvidenceGap("unknown_dependency_version", "dependency manifest", "workspace"))
    if contradictory_evidence:
        gaps.append(EvidenceGap("contradictory_evidence", "fresh workspace state", "resolver"))
    watched = {
        ToolStatus.NOT_FOUND, ToolStatus.EMPTY, ToolStatus.UNSUPPORTED_CONTENT,
    }
    for result in tool_results:
        if result.status in watched:
            gaps.append(EvidenceGap("insufficient_tool_evidence", result.status.value, "tool"))
    unique = {(gap.kind, gap.study_target, gap.source): gap for gap in gaps}
    return tuple(unique.values())


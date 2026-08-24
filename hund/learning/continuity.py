"""Pure, bounded continuity planning for references to earlier work."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_CUES = (
    "vi gjorde", "som förra gången", "fortsätt", "den där", "vår ",
    "förra gången", "last time", "we decided", "continue", "that parser",
)
_WORDS = re.compile(r"[A-Za-zÅÄÖåäö0-9_+.#/-]{3,}")
_STOP = {
    "gjorde", "gången", "fortsätt", "fortsatta", "snackade", "igår", "denna",
    "där", "förra", "last", "time", "decided", "continue", "that", "with",
    "what", "were", "från", "som", "och", "the", "vår", "our", "we",
}


@dataclass(frozen=True)
class ContinuityPlan:
    detected: bool
    content_nouns: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    max_results_per_query: int = 3
    max_total_chars: int = 1500


class ContinuityResolver:
    def plan(
        self, user_message: str, current_context: dict[str, Any] | None = None
    ) -> ContinuityPlan:
        lower = user_message.casefold()
        detected = any(cue in lower for cue in _CUES)
        if not detected:
            return ContinuityPlan(False)
        nouns: list[str] = []
        for word in _WORDS.findall(user_message):
            normalized = word.casefold().strip("./")
            if normalized in _STOP or normalized.isdigit() or normalized in nouns:
                continue
            nouns.append(normalized)
        nouns = nouns[:6]
        queries: list[str] = []
        if nouns:
            queries.append(" ".join(nouns[:4]))
        project_hint = str((current_context or {}).get("project", "")).strip()
        if project_hint and len(queries) < 2:
            queries.append(f"{project_hint} {' '.join(nouns[:2])}".strip())
        return ContinuityPlan(
            True, tuple(nouns), tuple(queries[:2]),
        )


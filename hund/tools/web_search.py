"""DuckDuckGo search with typed results and session URL provenance."""
from __future__ import annotations
import re
import time
from typing import Any
from ddgs import DDGS
from .types import (
    ToolCallContext, ToolKind, ToolStatus,
    create_error_result, create_success_result,
)

MAX_RESULTS = 15
_BACKOFF_SECONDS = 1.0


def _simplified_query(query: str) -> str:
    """Fallback variant of the query with quote/parenthetical noise removed."""
    cleaned = re.sub(r"[\"'()\[\]{}]+", " ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned and cleaned != query else ""


def search_web(args: dict) -> str:
    """Legacy string API retained for direct callers."""
    return search_web_typed(args, None).to_llm_text()


def search_web_typed(args: dict[str, Any], context: ToolCallContext | None):
    """Search and register returned URLs in the current session."""
    query = args.get("query", "")
    if not query:
        return create_error_result(
            status=ToolStatus.ERROR, kind=ToolKind.SEARCH,
            raw_error="query saknas", public_error="query saknas",
            metadata={"result_count": 0},
        )

    # Attempt the original query, then a simplified variant as fallback
    # (complex quoting/parentheses are a common DDGS parser failure mode).
    attempt_queries = [query]
    simplified = _simplified_query(query)
    if simplified:
        attempt_queries.append(simplified)

    results = None
    last_error: Exception | None = None
    degraded = False
    for attempt_query in attempt_queries:
        for attempt in range(2):
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(attempt_query, max_results=MAX_RESULTS))
                break
            except Exception as e:
                last_error = e
                degraded = True
                if attempt == 0 and _BACKOFF_SECONDS > 0:
                    time.sleep(_BACKOFF_SECONDS)
        if results is not None:
            break

    if results is None:
        return create_error_result(
            status=ToolStatus.NETWORK_ERROR, kind=ToolKind.SEARCH,
            raw_error=last_error or "sökningen misslyckades",
            public_error="sökningen misslyckades — försök igen, eventuellt med annan formulering",
            metadata={"result_count": 0},
        )

    if not results:
        return create_error_result(
            status=ToolStatus.EMPTY, kind=ToolKind.SEARCH,
            raw_error="inga resultat",
            public_error="inga resultat — bredda eller förenkla sökfrågan",
            metadata={"result_count": 0},
        )

    matched = results[:MAX_RESULTS]
    lines = []
    if degraded:
        lines.append(
            "[note: first search attempt failed; results recovered via retry "
            "with a simplified query — verify coverage before relying on them]"
        )
    if len(matched) < 4:
        lines.append(f"[sparsamt resultat: {len(matched)} träffar — överväg breddad sökning]")

    for item in matched:
        title = item.get("title", "?")
        href = item.get("href", "?")
        body = item.get("body", "")
        if context is not None and context.url_provenance is not None:
            context.url_provenance.register_url(href, source="web_search")
        lines.append(f"{title}\n  {href}\n  {body}")

    return create_success_result(
        kind=ToolKind.SEARCH,
        payload="\n\n".join(lines),
        metadata={"result_count": len(matched), "degraded": degraded},
    )

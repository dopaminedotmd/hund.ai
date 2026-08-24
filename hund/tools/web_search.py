"""DuckDuckGo search with typed results and session URL provenance."""
from __future__ import annotations
from typing import Any
from ddgs import DDGS
from .types import (
    ToolCallContext, ToolKind, ToolStatus,
    create_error_result, create_success_result,
)

MAX_RESULTS = 10

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
        )
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=MAX_RESULTS))
    except Exception as e:
        return create_error_result(
            status=ToolStatus.NETWORK_ERROR, kind=ToolKind.SEARCH,
            raw_error=e, public_error="webbsökningen misslyckades",
        )
    if not results:
        return create_error_result(
            status=ToolStatus.EMPTY, kind=ToolKind.SEARCH,
            raw_error="inga resultat", public_error="inga resultat",
        )
    lines = []
    for item in results[:MAX_RESULTS]:
        title = item.get("title", "?")
        href = item.get("href", "?")
        body = item.get("body", "")
        if context is not None and context.url_provenance is not None:
            context.url_provenance.register_url(href, source="web_search")
        lines.append(f"{title}\n  {href}\n  {body}")
    return create_success_result(
        kind=ToolKind.SEARCH, payload="\n\n".join(lines),
        metadata={"result_count": min(len(results), MAX_RESULTS)},
    )

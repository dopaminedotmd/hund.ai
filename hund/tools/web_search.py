"""web_search tool via DuckDuckGo (gratis, ingen API-nyckel)."""
from __future__ import annotations
from duckduckgo_search import DDGS

MAX_RESULTS = 10

def search_web(args: dict) -> str:
    query = args.get("query", "")
    if not query:
        return "[error] query saknas"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=MAX_RESULTS))
    except Exception as e:
        return f"[error] {e}"
    if not results:
        return "inga resultat"
    lines = []
    for item in results[:MAX_RESULTS]:
        title = item.get("title", "?")
        href = item.get("href", "?")
        body = item.get("body", "")
        lines.append(f"{title}\n  {href}\n  {body}")
    return "\n\n".join(lines)

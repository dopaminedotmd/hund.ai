"""web_search tool via Brave Search API."""
from __future__ import annotations
import os
import httpx

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

def search_web(args: dict) -> str:
    query = args.get("query", "")
    if not query:
        return "[error] query saknas"
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return "[error] BRAVE_API_KEY saknas i miljovariabler"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    try:
        r = httpx.get(BRAVE_API_URL, headers=headers, params={"q": query, "count": 10}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        return f"[error] HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return f"[error] {e}"
    results = data.get("web", {}).get("results", [])
    if not results:
        return "inga resultat"
    lines = []
    for item in results[:10]:
        title = item.get("title", "?")
        url = item.get("url", "?")
        desc = item.get("description", "")
        lines.append(f"{title}\n  {url}\n  {desc}")
    return "\n\n".join(lines)

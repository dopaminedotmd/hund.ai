"""session_search tool — sok i tidigare sessionshistorik via FTS5."""
from __future__ import annotations

def search_sessions(args: dict) -> str:
    query = args.get("query", "")
    mode = args.get("mode", "search")  # "search" eller "list"
    limit = min(args.get("limit", 5), 20)
    from ..agent import sessions as S
    if mode == "list":
        rows = S.list_sessions(limit=limit)
        if not rows:
            return "(inga sessioner)"
        lines = []
        for sid, created, title, count, active in rows:
            mark = "*" if active else " "
            t = title[:40] if title else "(ingen titel)"
            lines.append(f"{mark} #{sid[:8]} ({count} msg) {t} — {created}")
        return "\n".join(lines)
    # mode="search"
    if not query.strip():
        return "[error] 'query' kravs for search mode"
    rows = S.search(query)
    if not rows:
        return f"(inga traffar for '{query}')"
    lines = []
    for sid, role, snippet, created in rows:
        lines.append(f"#{sid[:8]} [{role}] {snippet} — {created}")
    return "\n".join(lines[:limit])

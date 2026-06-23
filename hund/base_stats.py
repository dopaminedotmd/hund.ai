"""Base stats — 3 råa mätetal UR loggarna. Inga fejkade coverage-%.

Token Efficiency (tokens/turn, lägre=bättre), Speed (avg latency, lägre=bättre),
Tool Judgment (tool success rate, högre=bättre). Grov nivå: strong/ok/weak/n-a.
"""
from __future__ import annotations

from .store.sqlite import connect_requests, connect_tool_events


def _level_higher_better(val, great, ok) -> str:
    if val is None:
        return "n/a"
    if val >= great:
        return "strong"
    if val >= ok:
        return "ok"
    return "weak"


def _level_lower_better(val, great, ok) -> str:
    if val <= great:
        return "strong"
    if val <= ok:
        return "ok"
    return "weak"


def compute() -> dict:
    conn = connect_requests()
    r = conn.execute(
        """SELECT COUNT(*),
                  COALESCE(SUM(prompt_tokens + completion_tokens), 0),
                  COALESCE(SUM(latency_ms), 0)
           FROM requests"""
    ).fetchone()
    n, total_tokens, total_lat = r
    conn.close()

    conn = connect_tool_events()
    te = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(success), 0) FROM tool_events WHERE outcome='ran'"
    ).fetchone()
    runs, ok = te
    conn.close()

    tokens_per_turn = (total_tokens / n) if n else None
    avg_latency = (total_lat / n) if n else None
    tool_rate = (ok / runs) if runs else None

    return {
        "token_efficiency": {
            "tokens_per_turn": round(tokens_per_turn) if tokens_per_turn else None,
            "level": _level_lower_better(tokens_per_turn, 500, 2000) if tokens_per_turn else "n/a",
        },
        "speed": {
            "avg_latency_ms": round(avg_latency) if avg_latency else None,
            "level": _level_lower_better(avg_latency, 2000, 6000) if avg_latency else "n/a",
        },
        "tool_judgment": {
            "success_rate_pct": round(tool_rate * 100) if tool_rate is not None else None,
            "level": _level_higher_better(tool_rate, 0.9, 0.7) if tool_rate is not None else "n/a",
        },
    }

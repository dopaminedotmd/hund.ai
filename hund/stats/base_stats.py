"""Base Stats v2 — compute 5 stats from local databases."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..paths import hund_home
from ..store.sqlite import connect, connect_requests, connect_tool_events
from .tiers import build_stat


def _completed_tasks(conn=None) -> int:
    """Count completed tasks: assistant messages without tool_calls."""
    from ..agent import sessions as S
    try:
        c = S._connect()
        row = c.execute(
            "SELECT COUNT(*) FROM messages WHERE role='assistant' AND tool_calls IS NULL AND content != ''"
        ).fetchone()
        c.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _user_messages(conn=None) -> int:
    from ..agent import sessions as S
    try:
        c = S._connect()
        row = c.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()
        c.close()
        return row[0] if row else 0
    except Exception:
        return 0


def compute_clarity() -> dict[str, Any]:
    """Turns Per Task (TPT). Lower is better."""
    tasks = _completed_tasks()
    users = _user_messages()
    tpt = users / tasks if tasks > 0 else None
    return build_stat("clarity", tpt, thresholds=[5.0, 3.0, 2.0, 1.2], higher_better=False)


def compute_precision() -> dict[str, Any]:
    """Tool success rate. Higher is better."""
    try:
        conn = connect_tool_events()
        total = conn.execute("SELECT COUNT(*) FROM tool_events WHERE outcome='ran'").fetchone()[0]
        successful = conn.execute("SELECT COUNT(*) FROM tool_events WHERE outcome='ran' AND success=1").fetchone()[0]
        conn.close()
        rate = (successful / total * 100) if total > 0 else None
    except Exception:
        rate = None
    return build_stat("precision", rate, thresholds=[40, 60, 75, 90], higher_better=True)


def compute_efficiency() -> dict[str, Any]:
    """Tokens per task. Lower is better."""
    tasks = _completed_tasks()
    try:
        conn = connect_requests()
        total_tokens = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) FROM requests"
        ).fetchone()[0]
        conn.close()
        tpt = total_tokens / tasks if tasks > 0 else None
    except Exception:
        tpt = None
    return build_stat("efficiency", tpt, thresholds=[5000, 2000, 800, 300], higher_better=False)


def compute_endurance() -> dict[str, Any]:
    """Turns before compression. Higher is better."""
    from ..agent import sessions as S
    try:
        c = S._connect()
        rows = c.execute(
            "SELECT session_id, COUNT(*) as msg_count FROM messages WHERE role IN ('user','assistant') GROUP BY session_id"
        ).fetchall()
        c.close()
        avg_turns = sum(r[1] for r in rows) / len(rows) if rows else None
    except Exception:
        avg_turns = None
    return build_stat("endurance", avg_turns, thresholds=[6, 12, 20, 30], higher_better=True)


def compute_mastery() -> dict[str, Any]:
    """Forge-verified skills/knowledge plus legacy verified knowledge units."""
    knowledge_dir = hund_home() / "brain" / "knowledge"
    total_verified: float = 0
    total_units = 0
    if knowledge_dir.exists():
        for f in knowledge_dir.glob("*.json"):
            if f.name.endswith("-scope.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                units = data.get("units", [])
                total_units += len(units)
                total_verified += sum(1 for u in units if u.get("success_count", 0) > 0)
            except Exception:
                pass
    try:
        conn = connect()
        rows = conn.execute(
            """
            SELECT source, COUNT(*)
            FROM forge_artifacts
            WHERE forge_verdict='approved'
              AND artifact_type IN ('tenant-local-skill', 'tenant-local-knowledge')
              AND state IN ('staged', 'promoted', 'active')
            GROUP BY source
            """
        ).fetchall()
        conn.close()
        for source, count in rows:
            total_verified += count * (0.2 if source == "simulation" else 1.0)
    except Exception:
        pass
    return build_stat("mastery", total_verified, thresholds=[3, 10, 25, 50], higher_better=True)


def compute_all() -> dict[str, dict[str, Any]]:
    return {
        "clarity": compute_clarity(),
        "precision": compute_precision(),
        "efficiency": compute_efficiency(),
        "endurance": compute_endurance(),
        "mastery": compute_mastery(),
    }

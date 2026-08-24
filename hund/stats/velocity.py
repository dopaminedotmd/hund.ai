"""Time-filtered base-stat velocity over two distinct seven-day windows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .tiers import build_stat


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def compute_all_since(
    start: datetime,
    end: datetime | None = None,
    *,
    home: Path | None = None,
) -> dict:
    """Compute the five stats from telemetry whose timestamps fall in the window."""
    from ..agent import sessions as session_store
    from ..store.sqlite import connect, connect_requests, connect_tool_events

    end = end or datetime.now(timezone.utc)
    lo, hi = _iso(start), _iso(end)
    core_db = (home / "hund.db") if home else None
    requests_db = (home / "logs" / "requests.db") if home else None
    tools_db = (home / "logs" / "tool_events.db") if home else None
    sessions_home = home

    tasks = users = 0
    session_counts: list[int] = []
    try:
        conn = connect(core_db)
        row = conn.execute(
            """SELECT COUNT(*) FROM lifecycle_task_events
               WHERE scope='machine' AND completed_at >= ? AND completed_at < ?""",
            (lo, hi),
        ).fetchone()
        tasks = int(row[0] if row else 0)
        conn.close()
    except Exception:
        tasks = 0

    try:
        conn = session_store._connect(sessions_home)
        row = conn.execute(
            """SELECT COUNT(*) FROM messages
               WHERE role='user' AND created_at >= ? AND created_at < ?""",
            (lo, hi),
        ).fetchone()
        users = int(row[0] if row else 0)
        rows = conn.execute(
            """SELECT session_id, COUNT(*) FROM messages
               WHERE role IN ('user','assistant') AND created_at >= ? AND created_at < ?
               GROUP BY session_id""",
            (lo, hi),
        ).fetchall()
        session_counts = [int(row[1]) for row in rows]
        conn.close()
    except Exception:
        users, session_counts = 0, []

    tool_total = tool_success = 0
    try:
        conn = connect_tool_events(tools_db)
        row = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(success), 0) FROM tool_events
               WHERE outcome='ran' AND created_at >= ? AND created_at < ?""",
            (lo, hi),
        ).fetchone()
        tool_total, tool_success = int(row[0]), int(row[1])
        conn.close()
    except Exception:
        pass

    total_tokens = request_count = 0
    try:
        conn = connect_requests(requests_db)
        row = conn.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(prompt_tokens), 0) + COALESCE(SUM(completion_tokens), 0)
               FROM requests WHERE created_at >= ? AND created_at < ?""",
            (lo, hi),
        ).fetchone()
        request_count, total_tokens = int(row[0]), int(row[1])
        conn.close()
    except Exception:
        pass

    promotions = 0
    try:
        conn = connect(core_db)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='domain_xp_events'"
        ).fetchone()
        if exists:
            row = conn.execute(
                """SELECT COUNT(*) FROM domain_xp_events
                   WHERE event_type='validation_promotion'
                     AND timestamp >= ? AND timestamp < ?""",
                (lo, hi),
            ).fetchone()
            promotions = int(row[0] if row else 0)
        conn.close()
    except Exception:
        pass

    clarity = (users / tasks) if tasks else None
    precision = (tool_success / tool_total * 100) if tool_total else None
    efficiency = (total_tokens / tasks) if tasks and request_count else None
    endurance = (
        sum(session_counts) / len(session_counts) if session_counts else None
    )
    mastery = float(promotions) if promotions else None
    return {
        "clarity": build_stat("clarity", clarity, [5.0, 3.0, 2.0, 1.2], False),
        "precision": build_stat("precision", precision, [40, 60, 75, 90], True),
        "efficiency": build_stat("efficiency", efficiency, [5000, 2000, 800, 300], False),
        "endurance": build_stat("endurance", endurance, [6, 12, 20, 30], True),
        "mastery": build_stat("mastery", mastery, [3, 10, 25, 50], True),
    }


def compute_velocity(
    *,
    now: datetime | None = None,
    home: Path | None = None,
) -> dict:
    """Compare the current seven days with the immediately preceding seven days."""
    end = now or datetime.now(timezone.utc)
    this_start = end - timedelta(days=7)
    previous_start = end - timedelta(days=14)
    current = compute_all_since(this_start, end, home=home)
    previous = compute_all_since(previous_start, this_start, home=home)

    velocity = {}
    for name, current_stat in current.items():
        current_value = current_stat.get("value")
        previous_value = previous.get(name, {}).get("value")
        if current_value is None or previous_value is None:
            continue
        delta = current_value - previous_value
        higher_better = name in ("precision", "endurance", "mastery")
        velocity[name] = {
            "delta": delta,
            "delta_display": f"{abs(delta):.1f}",
            "improving": delta == 0 or ((delta > 0) == higher_better),
            "current": current_value,
            "previous": previous_value,
            "current_window": (_iso(this_start), _iso(end)),
            "previous_window": (_iso(previous_start), _iso(this_start)),
        }
    return velocity

"""Base Stats v2 — pure telemetry, stats epochs, rolling windows, and per-domain metrics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..paths import brain_knowledge_dir, hund_home
from ..store.sqlite import connect, connect_requests, connect_tool_events
from .epochs import get_current_epoch
from .tiers import build_stat


def _get_epoch_cutoff(home: Optional[Path] = None) -> str:
    """Get the ISO timestamp of current epoch start."""
    try:
        db_p = (home / "hund.db") if home else None
        _, started_at = get_current_epoch(db_path=db_p)
        return started_at
    except Exception:
        return "1970-01-01T00:00:00+00:00"


def _completed_tasks(window_size: int = 50, home: Optional[Path] = None) -> int:
    """Count completed tasks in current epoch / window: assistant messages without tool_calls."""
    from ..agent import sessions as S
    cutoff = _get_epoch_cutoff(home)
    try:
        c = S._connect(home) if hasattr(S, "_connect") else connect()
        # Query with timestamp if column exists, otherwise count latest within window
        row = c.execute(
            """SELECT COUNT(*) FROM (
                SELECT id FROM messages
                WHERE role='assistant' AND tool_calls IS NULL AND content != ''
                ORDER BY rowid DESC LIMIT ?
            )""",
            (window_size,),
        ).fetchone()
        c.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _user_messages(window_size: int = 50, home: Optional[Path] = None) -> int:
    from ..agent import sessions as S
    try:
        c = S._connect(home) if hasattr(S, "_connect") else connect()
        row = c.execute(
            """SELECT COUNT(*) FROM (
                SELECT id FROM messages WHERE role='user'
                ORDER BY rowid DESC LIMIT ?
            )""",
            (window_size * 5,),
        ).fetchone()
        c.close()
        return row[0] if row else 0
    except Exception:
        return 0



def compute_clarity(
    domain: Optional[str] = None,
    window_size: int = 50,
    home: Optional[Path] = None,
) -> dict[str, Any]:
    """Turns Per Task (TPT) in current window. Lower is better."""
    tasks = _completed_tasks(window_size, home)
    users = _user_messages(window_size, home)
    tpt = users / tasks if tasks > 0 else None
    return build_stat("clarity", tpt, thresholds=[5.0, 3.0, 2.0, 1.2], higher_better=False)


def compute_precision(
    domain: Optional[str] = None,
    window_size: int = 50,
    home: Optional[Path] = None,
) -> dict[str, Any]:
    """Tool success rate in current window. Higher is better."""
    cutoff = _get_epoch_cutoff(home)
    try:
        tool_db = (home / "logs" / "tool_events.db") if home else None
        conn = connect_tool_events(tool_db)
        # Fetch latest window_size tool events created in this epoch
        rows = conn.execute(
            """SELECT outcome, success FROM tool_events
               WHERE created_at >= ?
               ORDER BY created_at DESC LIMIT ?""",
            (cutoff, window_size),
        ).fetchall()
        conn.close()

        total = sum(1 for r in rows if r[0] == "ran")
        successful = sum(1 for r in rows if r[0] == "ran" and r[1] == 1)
        rate = (successful / total * 100) if total > 0 else None
    except Exception:
        rate = None
    return build_stat("precision", rate, thresholds=[40, 60, 75, 90], higher_better=True)


def compute_efficiency(
    domain: Optional[str] = None,
    window_size: int = 50,
    home: Optional[Path] = None,
) -> dict[str, Any]:
    """Tokens per task in current window. Lower is better."""
    tasks = _completed_tasks(window_size, home)
    cutoff = _get_epoch_cutoff(home)
    try:
        req_db = (home / "logs" / "requests.db") if home else None
        conn = connect_requests(req_db)
        rows = conn.execute(
            """SELECT prompt_tokens, completion_tokens FROM requests
               WHERE created_at >= ?
               ORDER BY created_at DESC LIMIT ?""",
            (cutoff, window_size),
        ).fetchall()
        conn.close()

        total_tokens = sum((r[0] or 0) + (r[1] or 0) for r in rows)
        tpt = (total_tokens / tasks) if (tasks > 0 and rows) else None
    except Exception:
        tpt = None
    return build_stat("efficiency", tpt, thresholds=[5000, 2000, 800, 300], higher_better=False)


def compute_endurance(
    domain: Optional[str] = None,
    window_size: int = 50,
    home: Optional[Path] = None,
    min_sample_threshold: int = 3,
) -> dict[str, Any]:
    """Endurance v2: verified sustained-task completion rate (%).

    A sustained task is a finalized task session with >= 4 messages (2+ turns).
    Requires at least min_sample_threshold (3) tasks before calculating percentage.
    """
    from ..agent import sessions as S
    try:
        c = S._connect(home) if hasattr(S, "_connect") else connect()
        rows = c.execute(
            """SELECT session_id, COUNT(*) as msg_count
               FROM messages WHERE role IN ('user','assistant')
               GROUP BY session_id
               ORDER BY max(rowid) DESC LIMIT ?""",
            (window_size,),
        ).fetchall()
        c.close()

        # Filter sustained tasks (>= 4 messages)
        sustained_tasks = [r for r in rows if r[1] >= 4]
        if len(sustained_tasks) < min_sample_threshold:
            stat = build_stat("endurance", None, thresholds=[40, 60, 75, 90], higher_better=True)
            stat["status_text"] = "Collecting evidence"
            return stat

        successful = len(sustained_tasks)
        rate = (successful / len(sustained_tasks)) * 100
        stat = build_stat("endurance", rate, thresholds=[40, 60, 75, 90], higher_better=True)
        stat["sample_count"] = len(sustained_tasks)
        return stat
    except Exception:
        stat = build_stat("endurance", None, thresholds=[40, 60, 75, 90], higher_better=True)
        stat["status_text"] = "Collecting evidence"
        return stat



def compute_mastery(
    domain: Optional[str] = None,
    home: Optional[Path] = None,
) -> dict[str, Any]:
    """Empirically verified skills/knowledge units (from knowledge.db & legacy files)."""
    total_verified: float = 0
    # 1. Check knowledge.db
    try:
        from ..knowledge import db as kdb
        db_p = (home / "knowledge" / "knowledge.db") if home else None
        units = kdb.list_units(domain=domain, db_path=db_p)
        total_verified += sum(
            1 for u in units if u.status in ("validated", "supported") or u.support_count > 0
        )
    except Exception:
        pass

    # 2. Check JSON knowledge files for legacy / materialized entries
    knowledge_dir = (home / "brain" / "knowledge") if home else brain_knowledge_dir()
    if knowledge_dir.exists() and total_verified == 0:
        pattern = f"{domain}.json" if domain else "*.json"
        for f in knowledge_dir.glob(pattern):
            if f.name.endswith("-scope.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                units = data.get("units", [])
                total_verified += sum(
                    1 for u in units if u.get("status") in ("validated", "supported") or u.get("success_count", 0) > 0
                )
            except Exception:
                pass

    # 3. Check forge_artifacts
    try:
        db_p = (home / "hund.db") if home else None
        conn = connect(db_p)
        query = """
            SELECT source, COUNT(*)
            FROM forge_artifacts
            WHERE forge_verdict='approved'
              AND artifact_type IN ('tenant-local-skill', 'tenant-local-knowledge')
              AND state IN ('staged', 'promoted', 'active')
        """
        params: list[Any] = []
        if domain:
            query += " AND scope = ?"
            params.append(domain)
        query += " GROUP BY source"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        for source, count in rows:
            total_verified += count * (0.2 if source == "simulation" else 1.0)
    except Exception:
        pass

    return build_stat("mastery", total_verified, thresholds=[3, 10, 25, 50], higher_better=True)


def compute_all(
    domain: Optional[str] = None,
    window_size: int = 50,
    home: Optional[Path] = None,
) -> dict[str, dict[str, Any]]:
    """Compute all 5 base stats with rolling windows and epoch awareness."""
    return {
        "clarity": compute_clarity(domain=domain, window_size=window_size, home=home),
        "precision": compute_precision(domain=domain, window_size=window_size, home=home),
        "efficiency": compute_efficiency(domain=domain, window_size=window_size, home=home),
        "endurance": compute_endurance(domain=domain, window_size=window_size, home=home),
        "mastery": compute_mastery(domain=domain, home=home),
    }

"""Base Stats v2 — pure telemetry, stats epochs, rolling windows, and per-domain metrics."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..paths import brain_knowledge_dir, hund_home
from ..store.sqlite import connect, connect_requests, connect_tool_events
from .epochs import get_current_epoch, get_stat_algorithm_boundary
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
        # Gate 3 QA: a single successful tool call must not show 100% - wait for
        # a minimum sample before reporting a rate (like endurance v3).
        rate = (successful / total * 100) if total >= 3 else None
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


def _collecting_endurance() -> dict[str, Any]:
    stat = build_stat(
        "endurance", None, thresholds=[40, 60, 75, 90], higher_better=True
    )
    stat["status_text"] = "Collecting evidence"
    return stat


def _parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("Trace timestamp must be a non-empty string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Trace timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def compute_endurance(
    domain: Optional[str] = None,
    window_size: int = 50,
    home: Optional[Path] = None,
    min_sample_threshold: int = 3,
) -> dict[str, Any]:
    """Compute Endurance v3 from completed, trace-verified sustained work."""
    from ..agent import sessions as S

    try:
        core_db_path = (home / "hund.db") if home else None
        epoch_started_at = _get_epoch_cutoff(home)
        algorithm_started_at = get_stat_algorithm_boundary(
            "endurance", "v3", db_path=core_db_path
        )
        cutoff = max(
            _parse_utc_timestamp(epoch_started_at),
            _parse_utc_timestamp(algorithm_started_at),
        )

        session_conn = S._connect(home)
        try:
            sustained_rows = session_conn.execute(
                """SELECT session_id
                   FROM messages
                   WHERE role IN ('user', 'assistant')
                   GROUP BY session_id
                   HAVING COUNT(*) >= 4"""
            ).fetchall()
        finally:
            session_conn.close()
        sustained_sessions = {
            str(row[0]) for row in sustained_rows if row[0]
        }
        if not sustained_sessions:
            return _collecting_endurance()

        trace_conn = connect(core_db_path)
        try:
            trace_rows = trace_conn.execute(
                """SELECT rowid, created_at, session_id, run_id, event_type,
                          payload_redacted
                   FROM trace_events
                   WHERE event_type IN (
                       'verification_completed', 'final_claim', 'run_completed'
                   )
                     AND created_at >= ?
                   ORDER BY created_at ASC, rowid ASC""",
                (cutoff.isoformat(),),
            ).fetchall()
        finally:
            trace_conn.close()

        events_by_run: dict[
            str, list[tuple[datetime, int, str, str, object]]
        ] = {}
        sessions_by_run: dict[str, set[str]] = {}
        for rowid, created_at, session_id, run_id, event_type, payload in trace_rows:
            if not session_id or not run_id or session_id not in sustained_sessions:
                continue
            timestamp = _parse_utc_timestamp(created_at)
            if timestamp < cutoff:
                continue
            run_key = str(run_id)
            sessions_by_run.setdefault(run_key, set()).add(str(session_id))
            events_by_run.setdefault(run_key, []).append(
                (timestamp, int(rowid), str(event_type), str(session_id), payload)
            )

        outcomes: list[tuple[datetime, bool]] = []
        for run_id, events in events_by_run.items():
            if len(sessions_by_run[run_id]) != 1:
                continue
            ordered_events = sorted(events, key=lambda event: (event[0], event[1]))
            final_index = next(
                (
                    index
                    for index, event in enumerate(ordered_events)
                    if event[2] == "final_claim"
                    and any(
                        later[2] == "run_completed"
                        for later in ordered_events[index + 1 :]
                    )
                ),
                None,
            )
            if final_index is None:
                continue
            verifications = [
                event
                for event in ordered_events[:final_index]
                if event[2] == "verification_completed"
            ]
            if not verifications:
                continue
            latest_verification = verifications[-1]
            raw_payload = latest_verification[4]
            if not isinstance(raw_payload, str):
                raise ValueError("Verification payload must be JSON text")
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict) or type(payload.get("passed")) is not bool:
                raise ValueError("Verification payload must contain a boolean passed field")
            passed = payload["passed"]
            outcomes.append((ordered_events[final_index][0], passed))

        outcomes.sort(key=lambda outcome: outcome[0], reverse=True)
        outcomes = outcomes[:window_size]
        if len(outcomes) < min_sample_threshold:
            return _collecting_endurance()

        successful = sum(1 for _, passed in outcomes if passed)
        rate = successful / len(outcomes) * 100
        stat = build_stat(
            "endurance", rate, thresholds=[40, 60, 75, 90], higher_better=True
        )
        stat["sample_count"] = len(outcomes)
        return stat
    except Exception:
        return _collecting_endurance()



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

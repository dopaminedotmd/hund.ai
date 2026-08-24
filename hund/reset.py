"""Reset logic — resets all learned progression, XP, confidence, gap events, knowledge units, logs, and skills."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional

from hund.paths import (
    brain_knowledge_dir,
    brain_skills_dir,
    db_path as default_db_path,
    hund_home,
    requests_db_path as default_requests_path,
    sessions_db_path as default_sessions_path,
    tool_events_db_path as default_tool_events_path,
)


def _clear_db_tables(db_file: Path, tables: list[str]) -> list[str]:
    cleared = []
    if not db_file.exists():
        return cleared
    try:
        conn = sqlite3.connect(db_file)
        for tbl in tables:
            try:
                table_check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
                ).fetchone()
                if table_check:
                    cur = conn.execute(f"DELETE FROM {tbl}")
                    if cur.rowcount > 0:
                        cleared.append(f"Cleared {cur.rowcount} row(s) from {db_file.name} [{tbl}]")
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass
    return cleared


def reset_all_progress(home: Optional[Path] = None) -> list[str]:
    """Wipe all learned data, XP, confidence, gap events, knowledge units, logs, and skills.

    Returns list of human-readable strings describing what was cleared.
    Preserves: config.json, model selection, motor skills (builtins).
    """
    cleared: list[str] = []
    base = home if home is not None else hund_home()

    db_file = base / "hund.db" if home is not None else default_db_path()
    req_file = base / "logs" / "requests.db" if home is not None else default_requests_path()
    tool_file = base / "logs" / "tool_events.db" if home is not None else default_tool_events_path()
    sess_file = base / "sessions" / "sessions.db" if home is not None else default_sessions_path()

    # 1. Clear core tables in hund.db
    cleared.extend(
        _clear_db_tables(
            db_file,
            [
                "domain_xp",
                "domain_xp_events",
                "domain_confidence",
                "gap_events",
                "knowledge_units",
                "forge_artifacts",
            ],
        )
    )

    # 2. Clear telemetry and performance logs (resets base stats)
    cleared.extend(_clear_db_tables(req_file, ["requests"]))
    cleared.extend(_clear_db_tables(tool_file, ["tool_events"]))
    cleared.extend(_clear_db_tables(sess_file, ["messages", "sessions"]))

    # 3. Clear brain/knowledge/*.json files
    k_dir = base / "brain" / "knowledge" if home is not None else brain_knowledge_dir()
    if k_dir.exists():
        k_count = 0
        for f in k_dir.glob("*.json"):
            try:
                f.unlink()
                k_count += 1
            except Exception:
                pass
        if k_count > 0:
            cleared.append(f"Removed {k_count} knowledge unit file(s)")

    # 4. Clear brain/skills/*.json (custom domain skills) and brain/skill_state.json
    s_dir = base / "brain" / "skills" if home is not None else brain_skills_dir()
    if s_dir.exists():
        s_count = 0
        for f in s_dir.glob("*.json"):
            try:
                f.unlink()
                s_count += 1
            except Exception:
                pass
        if s_count > 0:
            cleared.append(f"Removed {s_count} custom skill file(s)")

    skill_state = base / "brain" / "skill_state.json"
    if skill_state.exists():
        try:
            skill_state.unlink()
            cleared.append("Reset skill vault state")
        except Exception:
            pass

    if cleared:
        try:
            from .stats.epochs import advance_epoch
            advance_epoch(db_file)
            cleared.append("Advanced telemetry stats epoch")
        except Exception:
            pass
    else:
        cleared.append("Already clean — no progression or log data to remove")

    return cleared

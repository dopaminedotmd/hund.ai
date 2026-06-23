"""Migrering v1 → v2 — monolit hund.db → brain/ + logs/ struktur.

Fas 9.5 Del C. Idempotent — säker att köra flera gånger (slår ihop per id, flyttar
bara filer som ligger på gamla platsen). Vid tom HundHome: no-op som ändå säkerställer
att brain/-strukturen existerar.

Gör (om förekommer):
  - knowledge_units (SQLite) → brain/knowledge/<domain>.json (merge per id)
  - HundHome/skills/*.json   → brain/skills/
  - HundHome/policy.json     → brain/policy.json
  - requests/tool_events i gammal hund.db → logs/requests.db / logs/tool_events.db
  - backup: backups/hund.db.<ts>.bak

Return: rapport-dict {domains, units, skills, policy, backup, migrated}.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..paths import (
    brain_knowledge_dir,
    brain_policy_path,
    brain_skills_dir,
    hund_home,
    requests_db_path,
    tool_events_db_path,
)


def _migrate_knowledge(old_db: Path, home: Optional[Path] = None) -> tuple[int, int]:
    """Läs knowledge_units ur gammal DB, merge per domän till JSON. Return (domains, units)."""
    if not old_db.exists():
        return 0, 0
    try:
        conn = sqlite3.connect(old_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "knowledge_units" not in tables:
            conn.close()
            return 0, 0
        rows = conn.execute("SELECT * FROM knowledge_units").fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM knowledge_units LIMIT 0").description]
        conn.close()
    except sqlite3.Error:
        return 0, 0

    kdir = brain_knowledge_dir() if home is None else (home / "brain" / "knowledge")
    kdir.mkdir(parents=True, exist_ok=True)
    by_domain: dict[str, list[dict]] = {}
    for r in rows:
        rec = dict(zip(cols, r))
        dom = rec.get("domain") or "general"
        by_domain.setdefault(dom, []).append(rec)

    total_units = 0
    for dom, units in by_domain.items():
        path = kdir / f"{dom}.json"
        existing = {"domain": dom, "version": 1, "units": []}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        seen = {u.get("id") for u in existing["units"]}
        for u in units:
            if u.get("id") and u["id"] not in seen:
                existing["units"].append(u)
                seen.add(u["id"])
                total_units += 1
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return len(by_domain), total_units


def _move_dir_contents(src: Path, dst: Path) -> int:
    """Flytt *.json från src till dst (skip om redan i dst). Return antal flyttade."""
    if not src.exists() or src.resolve() == dst.resolve():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src.glob("*.json")):
        target = dst / f.name
        if target.exists():
            continue
        shutil.move(str(f), str(target))
        n += 1
    return n


def _move_file(src: Path, dst: Path) -> bool:
    if not src.exists() or src.resolve() == dst.resolve():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    shutil.move(str(src), str(dst))
    return True


def _migrate_logs(old_db: Path, home: Optional[Path] = None) -> tuple[int, int]:
    """Kopiera requests/tool_events från gammal hund.db till logs/*.db. Return (req, tool)."""
    if not old_db.exists():
        return 0, 0
    try:
        conn = sqlite3.connect(old_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        n_req = n_tool = 0
        if "requests" in tables:
            req_path = requests_db_path() if home is None else (home / "logs" / "requests.db")
            req_path.parent.mkdir(parents=True, exist_ok=True)
            rconn = sqlite3.connect(req_path)
            rconn.execute("""CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, created_at TEXT, task_class TEXT,
                model_requested TEXT, model_actual TEXT, provider TEXT,
                finish_reason TEXT, prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0, latency_ms INTEGER DEFAULT 0)""")
            cols = [d[0] for d in conn.execute("SELECT * FROM requests LIMIT 0").description]
            rows = conn.execute("SELECT * FROM requests").fetchall()
            for r in rows:
                rec = dict(zip(cols, r))
                rconn.execute(
                    "INSERT OR IGNORE INTO requests (id, created_at, task_class, "
                    "model_requested, model_actual, provider, finish_reason, "
                    "prompt_tokens, completion_tokens, latency_ms) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (rec.get("id"), rec.get("created_at"), rec.get("task_class"),
                     rec.get("model_requested"), rec.get("model_actual"),
                     rec.get("provider"), rec.get("finish_reason"),
                     rec.get("prompt_tokens", 0), rec.get("completion_tokens", 0),
                     rec.get("latency_ms", 0)),
                )
            rconn.commit()
            n_req = rconn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
            rconn.close()
        if "tool_events" in tables:
            te_path = tool_events_db_path() if home is None else (home / "logs" / "tool_events.db")
            te_path.parent.mkdir(parents=True, exist_ok=True)
            tconn = sqlite3.connect(te_path)
            tconn.execute("""CREATE TABLE IF NOT EXISTS tool_events (
                id TEXT PRIMARY KEY, created_at TEXT, tool TEXT, risk TEXT,
                outcome TEXT, success INTEGER DEFAULT 0)""")
            cols = [d[0] for d in conn.execute("SELECT * FROM tool_events LIMIT 0").description]
            rows = conn.execute("SELECT * FROM tool_events").fetchall()
            for r in rows:
                rec = dict(zip(cols, r))
                tconn.execute(
                    "INSERT OR IGNORE INTO tool_events "
                    "(id, created_at, tool, risk, outcome, success) VALUES (?,?,?,?,?,?)",
                    (rec.get("id"), rec.get("created_at"), rec.get("tool"),
                     rec.get("risk"), rec.get("outcome"), rec.get("success", 0)),
                )
            tconn.commit()
            n_tool = tconn.execute("SELECT COUNT(*) FROM tool_events").fetchone()[0]
            tconn.close()
        conn.close()
        return n_req, n_tool
    except sqlite3.Error:
        return 0, 0


def migrate(home: Optional[Path] = None) -> dict:
    """Kör full v1→v2-migrering. Idempotent. Return rapport."""
    base = home if home is not None else hund_home()
    old_db = base / "hund.db"

    # Säkerställ brain/-struktur
    (base / "brain" / "skills").mkdir(parents=True, exist_ok=True)
    (base / "brain" / "knowledge").mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(parents=True, exist_ok=True)
    (base / "backups").mkdir(parents=True, exist_ok=True)

    domains_n, units_n = _migrate_knowledge(old_db, home)
    skills_n = _move_dir_contents(
        base / "skills",
        base / "brain" / "skills" if home else brain_skills_dir(),
    )
    policy_moved = _move_file(
        base / "policy.json",
        base / "brain" / "policy.json" if home else brain_policy_path(),
    )
    req_n, tool_n = _migrate_logs(old_db, home)

    backup = None
    if old_db.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = base / "backups" / f"hund.db.v1.{ts}.bak"
        shutil.copy2(old_db, bak)
        backup = str(bak.relative_to(base))

    migrated = old_db.exists()
    return {
        "domains": domains_n,
        "units": units_n,
        "skills": skills_n,
        "policy": policy_moved,
        "requests": req_n,
        "tool_events": tool_n,
        "backup": backup,
        "migrated": migrated,
    }

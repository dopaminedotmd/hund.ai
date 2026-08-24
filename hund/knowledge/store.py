"""Knowledge store — lokala kunskapsenheter med LFU/MRU-retrieval.

Fas 9.5 Del C: lagring flyttad från SQLite (knowledge_units-tabell) till
JSON-filer per domän under brain/knowledge/<domain>.json. Editbar i filsystemet,
inga dubbletter i en soppa, enkel migrering/backup.

API:t (add/list_units/top_k/bump_usage/domains) bevarat — callers oförändrade.
`home`-param tillåter testisolation (tmp-HundHome).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..paths import brain_knowledge_dir, hund_home


def _dir(home: Optional[Path] = None) -> Path:
    base = home if home is not None else hund_home()
    d = base / "brain" / "knowledge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _domain_path(domain: str, home: Optional[Path] = None) -> Path:
    return _dir(home) / f"{domain}.json"


def _load(domain: str, home: Optional[Path] = None) -> dict:
    p = _domain_path(domain, home)
    if not p.exists():
        return {"domain": domain, "version": 1, "units": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"domain": domain, "version": 1, "units": []}


def _save(data: dict, home: Optional[Path] = None) -> None:
    p = _domain_path(data["domain"], home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _all_domain_files(home: Optional[Path] = None) -> list[Path]:
    d = _dir(home)
    return sorted(p for p in d.glob("*.json") if not p.name.endswith("-scope.json"))


def add(domain: str, trigger: str, rule: str, source: str = "manual",
        home: Optional[Path] = None) -> str:
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data = _load(domain, home)
    data["units"].append({
        "id": uid,
        "created_at": now,
        "trigger": trigger,
        "rule": rule,
        "frequency": 0,
        "last_used": None,
        "success_count": 0,
        "fail_count": 0,
        "source": source,
    })
    _save(data, home)
    try:
        from . import db as kdb
        from .models import KnowledgeUnit, STATUS_CANDIDATE
        db_path = (home / "knowledge" / "knowledge.db") if home else None
        kdb.insert_unit(
            KnowledgeUnit(
                id=uid,
                domain=domain,
                statement=rule,
                trigger=trigger,
                status=STATUS_CANDIDATE,
                confidence=0.6,
                created_at=now,
            ),
            reason=f"added via store.add source={source}",
            db_path=db_path,
        )
    except Exception:
        pass

    try:
        from hund.domains.xp import add_xp
        add_xp(domain, 3)
    except Exception:
        pass
    return uid


def list_units(domain: str | None = None, home: Optional[Path] = None) -> list[tuple]:
    """Returnera (uid8, domain, trigger, rule, frequency, success_count) LFU-ordnat."""
    rows: list[tuple] = []
    for p in _all_domain_files(home):
        data = _load(p.stem, home)
        if domain and data["domain"] != domain:
            continue
        for u in data["units"]:
            rows.append((
                u["id"][:8], data["domain"], u.get("trigger", ""),
                u.get("rule", ""), u.get("frequency", 0), u.get("success_count", 0),
            ))
    rows.sort(key=lambda r: r[4], reverse=True)  # frequency DESC
    return rows


def top_k(domain: str, k: int = 5, home: Optional[Path] = None) -> list[tuple]:
    """LFU/MRU hybrid: frekvens först, sen aktualitet. Top-K per domain."""
    data = _load(domain, home)
    units = sorted(
        data["units"],
        key=lambda u: (-u.get("frequency", 0), u.get("last_used") or ""),
    )
    return [(u.get("trigger", ""), u.get("rule", "")) for u in units[:k]]


def bump_usage(uid_prefix: str, success: bool = True, home: Optional[Path] = None) -> int:
    """Bump frequency + success/fail + last_used för unit(s) med id-prefix."""
    now = datetime.now(timezone.utc).isoformat()
    col = "success_count" if success else "fail_count"
    n = 0
    for p in _all_domain_files(home):
        data = _load(p.stem, home)
        changed = False
        for u in data["units"]:
            if u["id"].startswith(uid_prefix):
                u["frequency"] = u.get("frequency", 0) + 1
                u[col] = u.get(col, 0) + 1
                u["last_used"] = now
                changed = True
                n += 1
        if changed:
            _save(data, home)
    return n


def domains(home: Optional[Path] = None) -> list[str]:
    return [p.stem for p in _all_domain_files(home)]


def unit_count(home: Optional[Path] = None) -> int:
    """Totalt antal units över alla domäner (för base stats / mastery)."""
    return sum(len(_load(p.stem, home)["units"]) for p in _all_domain_files(home))

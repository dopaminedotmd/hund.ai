"""KnowledgeScope — save/load knowledge scope for a domain."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import hund_home


@dataclass
class KnowledgeScope:
    domain: str
    total_estimated_units: int
    categories: list[dict]
    sources: list[str]
    difficulty: str
    notes: str = ""
    research_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def save(self) -> Path:
        target = hund_home() / "brain" / "knowledge" / f"{self.domain}-scope.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    @classmethod
    def load_by_domain(cls, domain: str) -> "KnowledgeScope | None":
        target = hund_home() / "brain" / "knowledge" / f"{domain}-scope.json"
        if not target.exists():
            return None
        try:
            return cls(**json.loads(target.read_text(encoding="utf-8")))
        except Exception:
            return None

    @classmethod
    def load_by_domain(cls, domain: str) -> "KnowledgeScope | None":
        target = hund_home() / "brain" / "knowledge" / f"{domain}-scope.json"
        if not target.exists():
            return None
        try:
            return cls(**json.loads(target.read_text(encoding="utf-8")))
        except Exception:
            return None


def load_knowledge_units(domain: str) -> list[dict]:
    """Load knowledge units for a domain from JSON files."""
    knowledge_dir = hund_home() / "brain" / "knowledge"
    units = []
    if knowledge_dir.exists():
        for f in sorted(knowledge_dir.glob("*.json")):
            if f.name.endswith("-scope.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                file_units = data.get("units", [])
                units.extend(u for u in file_units if u.get("domain", "").lower() == domain.lower())
            except Exception:
                pass
    return units


def calculate_progress(domain: str) -> dict[str, Any]:
    """Calculate progress against a researched scope."""
    scope = KnowledgeScope.load_by_domain(domain)
    if scope is None:
        return {"error": f"Ingen scope for {domain} — kor 'hund research {domain}' forst"}

    units = load_knowledge_units(domain)
    current = len(units)
    total = scope.total_estimated_units
    pct = round(current / total * 100, 1) if total > 0 else 0

    cat_progress = {}
    for cat in scope.categories:
        cat_name = cat.get("name", "")
        cat_total = cat.get("estimated_units", 100)
        cat_current = sum(1 for u in units if cat_name.lower() in str(u.get("tags", [])).lower())
        cat_pct = round(cat_current / cat_total * 100, 1) if cat_total > 0 else 0
        cat_progress[cat_name] = {"current": cat_current, "total": cat_total, "percentage": cat_pct}

    def _tier(p: float) -> str:
        if p >= 80: return "functional mastery"
        if p >= 50: return "competent"
        if p >= 20: return "learning"
        return "novice"

    return {
        "domain": domain,
        "current": current,
        "total": total,
        "percentage": pct,
        "tier": _tier(pct),
        "categories": cat_progress,
    }

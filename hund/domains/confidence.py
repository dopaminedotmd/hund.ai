"""DomainConfidence — track confidence scores for domain locking."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..store.sqlite import connect

SIGNAL_WEIGHTS = {
    "user_declaration": 10,
    "manifest": 8,
    "manual_override": 10,
    "filetype_majority": 6,
    "time_spent_minutes": 5,
    "commands_run": 4,
    "gap_event": 2,
    "knowledge_unit_added": 3,
}

CONFIDENCE_DB = "domain_confidence"


def _ensure_table(db_path=None):
    conn = connect(db_path)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {CONFIDENCE_DB} (
        domain TEXT PRIMARY KEY,
        score REAL DEFAULT 0.0,
        signal_count INTEGER DEFAULT 0,
        unique_sources TEXT DEFAULT '[]',
        first_seen TEXT,
        last_seen TEXT,
        session_count INTEGER DEFAULT 0,
        confidence_tier TEXT DEFAULT 'candidate'
    )""")
    conn.commit()
    conn.close()


@dataclass
class DomainConfidence:
    domain: str
    score: float = 0.0
    signal_count: int = 0
    unique_sources: set = field(default_factory=set)
    first_seen: str = ""
    last_seen: str = ""
    session_count: int = 0
    confidence_tier: str = "candidate"

    @property
    def percentage(self) -> int:
        return min(round(self.score), 100)

    @property
    def is_lockable(self) -> bool:
        return (self.percentage >= 85 and len(self.unique_sources) >= 2 and self.session_count >= 3)


def get_confidence(domain: str, db_path=None) -> DomainConfidence | None:
    _ensure_table(db_path)
    conn = connect(db_path)
    row = conn.execute(f"SELECT * FROM {CONFIDENCE_DB} WHERE domain=?", (domain,)).fetchone()
    conn.close()
    if row is None:
        return None
    import json
    return DomainConfidence(
        domain=row[0], score=row[1], signal_count=row[2],
        unique_sources=set(json.loads(row[3])),
        first_seen=row[4] or "", last_seen=row[5] or "",
        session_count=row[6] or 0, confidence_tier=row[7] or "candidate",
    )


def add_signal(domain: str, signal_type: str, db_path=None) -> DomainConfidence:
    _ensure_table(db_path)
    weight = SIGNAL_WEIGHTS.get(signal_type, 1)
    now = datetime.now(timezone.utc).isoformat()
    existing = get_confidence(domain, db_path)

    if existing:
        tracker = existing
        tracker.signal_count += 1
        effective_weight = weight * (1.0 / (1.0 + 0.1 * tracker.signal_count))
        tracker.score = (tracker.score * 0.8) + (effective_weight * 10 * 0.2)
        tracker.score = min(tracker.score, 100.0)
        tracker.unique_sources.add(signal_type)
        tracker.last_seen = now
        tracker.session_count += 1
        if tracker.percentage >= 85 and len(tracker.unique_sources) >= 2:
            tracker.confidence_tier = "confident"
        elif tracker.percentage >= 50:
            tracker.confidence_tier = "active"
    else:
        tracker = DomainConfidence(
            domain=domain, score=min(weight * 10 * 0.2, 100.0),
            signal_count=1, unique_sources={signal_type},
            first_seen=now, last_seen=now, session_count=1,
            confidence_tier="candidate",
        )

    _save_confidence(tracker, db_path)
    return tracker


def _save_confidence(tc: DomainConfidence, db_path=None):
    import json
    conn = connect(db_path)
    conn.execute(f"""INSERT OR REPLACE INTO {CONFIDENCE_DB}
        (domain, score, signal_count, unique_sources, first_seen, last_seen, session_count, confidence_tier)
        VALUES (?,?,?,?,?,?,?,?)""",
        (tc.domain, tc.score, tc.signal_count, json.dumps(list(tc.unique_sources)),
         tc.first_seen, tc.last_seen, tc.session_count, tc.confidence_tier))
    conn.commit()
    conn.close()


def list_confidence(db_path=None) -> list[dict[str, Any]]:
    _ensure_table(db_path)
    conn = connect(db_path)
    rows = conn.execute(f"SELECT * FROM {CONFIDENCE_DB} ORDER BY score DESC").fetchall()
    conn.close()
    import json
    result = []
    for r in rows:
        result.append({
            "domain": r[0], "score": r[1], "signal_count": r[2],
            "unique_sources": json.loads(r[3]) if r[3] else [],
            "first_seen": r[4], "last_seen": r[5],
            "session_count": r[6], "confidence_tier": r[7] or "candidate",
            "is_lockable": r[1] >= 85 and len(json.loads(r[3]) if r[3] else []) >= 2 and (r[6] or 0) >= 3,
        })
    return result

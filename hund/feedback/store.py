"""SQLite-lagring för beteendelärdomar.

Tabell: behavior_lessons — lagrar komprimerade lärdomar med domän- och
workspace-kontext. Använder befintlig connect() från hund/store/sqlite.py.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


_BEHAVIOR_LESSONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS behavior_lessons (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    lesson_category TEXT NOT NULL,
    lesson_text TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    seen_count INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_behavior_lessons_domain_ws
    ON behavior_lessons(domain, workspace_id);
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Skapa behavior_lessons-tabellen om den inte finns."""
    conn.executescript(_BEHAVIOR_LESSONS_SCHEMA)
    conn.commit()


class FeedbackStore:
    """Lagrar och hämtar beteendelärdomar från SQLite."""

    def __init__(self, db_path: Path | None = None):
        from ..store.sqlite import connect

        self._conn = connect(db_path)
        _ensure_table(self._conn)

    def store_lessons(self, lessons: list[dict]) -> int:
        """Lagra en lista av lärdomar. Uppdaterar confidence/seen_count vid dup.

        Varje lärdom: {lesson_text, category, confidence, domain, ...}
        Returnerar antal lagrade lärdomar.
        """
        import uuid

        now = datetime.now(timezone.utc).isoformat()
        stored = 0
        for lesson in lessons:
            try:
                lesson_text = lesson.get("lesson_text", "")
                category = lesson.get("category", "unknown")
                confidence = lesson.get("confidence", 0.5)
                domain = lesson.get("domain", "general")
                session_id = lesson.get("session_id", "")
                workspace_id = lesson.get("workspace_id", "")

                # Kolla om liknande lärdom redan finns
                existing = self._find_similar(lesson_text, domain, workspace_id)
                if existing:
                    # Uppdatera confidence och seen_count
                    new_conf = min(1.0, (existing[0] + confidence) / 2 + 0.05)
                    new_count = existing[1] + 1
                    self._conn.execute(
                        """UPDATE behavior_lessons
                           SET confidence = ?, seen_count = ?, last_seen_at = ?
                           WHERE id = ?""",
                        (new_conf, new_count, now, existing[2]),
                    )
                else:
                    lid = str(uuid.uuid4())
                    self._conn.execute(
                        """INSERT INTO behavior_lessons
                           (id, session_id, workspace_id, domain, lesson_category,
                            lesson_text, confidence, seen_count, created_at, last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                        (
                            lid,
                            session_id,
                            workspace_id,
                            domain,
                            category,
                            lesson_text,
                            confidence,
                            now,
                            now,
                        ),
                    )
                stored += 1
            except Exception:
                continue
        self._conn.commit()
        return stored

    def _find_similar(
        self, text: str, domain: str, workspace_id: str
    ) -> tuple | None:
        """Hitta liknande lärdom. Returnerar (confidence, seen_count, id) eller None."""
        rows = self._conn.execute(
            """SELECT confidence, seen_count, id, lesson_text
               FROM behavior_lessons
               WHERE domain = ? AND workspace_id = ?""",
            (domain, workspace_id),
        ).fetchall()
        for conf, cnt, rid, existing_text in rows:
            if _similarity(text, existing_text) > 0.7:
                return (conf, cnt, rid)
        return None

    def query_top_lessons(
        self,
        workspace_id: str,
        domain: str,
        limit: int = 5,
    ) -> list[dict]:
        """Hämta top-K lärdomar sorterade efter confidence * seen_count."""
        try:
            rows = self._conn.execute(
                """SELECT lesson_text, lesson_category, confidence, seen_count
                   FROM behavior_lessons
                   WHERE workspace_id = ? AND domain = ?
                   ORDER BY confidence * seen_count DESC
                   LIMIT ?""",
                (workspace_id, domain, limit),
            ).fetchall()
            return [
                {
                    "lesson_text": r[0],
                    "category": r[1],
                    "confidence": r[2],
                    "seen_count": r[3],
                }
                for r in rows
            ]
        except Exception:
            return []

    def close(self) -> None:
        """Stäng databasanslutningen."""
        try:
            self._conn.close()
        except Exception:
            pass


def _similarity(a: str, b: str) -> float:
    """Enkel Jaccard-liknande similarity baserad på ordöverlapp."""
    import re
    # Ta bort skiljetecken för bättre matchning
    clean = lambda s: set(re.sub(r"[^\w\s]", "", s.lower()).split())
    words_a = clean(a)
    words_b = clean(b)
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)

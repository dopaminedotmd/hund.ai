"""Idempotent skill-XP ledger, deterministic award controller, and proficiency tracking."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Optional

from ..domains.xp import calculate_level_and_tier
from ..learning.receipts import PublicProgressReceipt
from ..store.sqlite import connect

SKILL_XP_TABLE = "skill_xp"
SKILL_XP_EVENTS_TABLE = "skill_xp_events"

# Event types and reward weights (§9.2 of Research Plan)
EVENT_VERIFIED_FIRST_USE = "verified_first_use"
EVENT_VERIFIED_SAME_PROJECT_REUSE = "verified_same_project_reuse"
EVENT_VERIFIED_CROSS_SESSION_REUSE = "verified_cross_session_reuse"
EVENT_ACCEPTED_PERSONAL_REFINEMENT = "accepted_personal_refinement"
EVENT_CROSS_PROJECT_GENERALIZATION = "cross_project_generalization"

SKILL_XP_AMOUNTS: dict[str, int] = {
    EVENT_VERIFIED_FIRST_USE: 2,
    EVENT_VERIFIED_SAME_PROJECT_REUSE: 2,
    EVENT_VERIFIED_CROSS_SESSION_REUSE: 4,
    EVENT_ACCEPTED_PERSONAL_REFINEMENT: 3,
    EVENT_CROSS_PROJECT_GENERALIZATION: 6,
}

SKILL_EVENT_DISPLAY_REASONS: dict[str, str] = {
    EVENT_VERIFIED_FIRST_USE: "verified first use",
    EVENT_VERIFIED_SAME_PROJECT_REUSE: "verified same-project reuse",
    EVENT_VERIFIED_CROSS_SESSION_REUSE: "verified cross-session reuse",
    EVENT_ACCEPTED_PERSONAL_REFINEMENT: "accepted personal refinement",
    EVENT_CROSS_PROJECT_GENERALIZATION: "cross-project generalization",
}


@dataclass(frozen=True)
class SkillXPRecord:
    capability_id: str
    domain: str
    version_lineage: str
    xp: int
    level: int
    tier: str
    use_count: int
    successful_use_count: int
    failure_count: int
    cross_session_success: int
    last_used_at: Optional[str]
    health: float
    updated_at: str


@dataclass(frozen=True)
class SkillXPEvent:
    event_id: str
    capability_id: str
    version: str
    xp_amount: int
    event_type: str
    task_id: str
    session_id: str
    evidence_id: str
    timestamp: str
    display_reason: str


class SkillProficiencyStore:
    """SQLite-backed authority for skill proficiency and XP events."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {SKILL_XP_TABLE} (
                    capability_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    version_lineage TEXT NOT NULL,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    tier TEXT DEFAULT 'Novice',
                    use_count INTEGER DEFAULT 0,
                    successful_use_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    cross_session_success INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    health REAL DEFAULT 1.0,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )"""
            )
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {SKILL_XP_EVENTS_TABLE} (
                    event_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    xp_amount INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    task_id TEXT,
                    session_id TEXT,
                    evidence_id TEXT,
                    timestamp TEXT NOT NULL,
                    display_reason TEXT NOT NULL
                )"""
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_skill_xp_events_cap ON {SKILL_XP_EVENTS_TABLE}(capability_id)"
            )
            conn.commit()
        finally:
            conn.close()


    def get_or_create_record(
        self,
        capability_id: str,
        domain: str = "general",
        version: str = "1.0.0",
        *,
        conn: Any = None,
    ) -> SkillXPRecord:
        should_close = False
        if conn is None:
            conn = connect(self.db_path)
            conn.execute("BEGIN IMMEDIATE")
            should_close = True

        try:
            row = conn.execute(
                f"SELECT capability_id, domain, version_lineage, xp, level, tier, use_count, "
                f"successful_use_count, failure_count, cross_session_success, last_used_at, health, updated_at "
                f"FROM {SKILL_XP_TABLE} WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
            if row:
                if should_close:
                    conn.commit()
                return SkillXPRecord(*row)

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                f"INSERT INTO {SKILL_XP_TABLE} (capability_id, domain, version_lineage, xp, level, tier, "
                f"use_count, successful_use_count, failure_count, cross_session_success, last_used_at, health, updated_at) "
                f"VALUES (?, ?, ?, 0, 1, 'Novice', 0, 0, 0, 0, NULL, 1.0, ?)",
                (capability_id, domain, version, now_iso),
            )
            if should_close:
                conn.commit()
            return SkillXPRecord(
                capability_id=capability_id,
                domain=domain,
                version_lineage=version,
                xp=0,
                level=1,
                tier="Novice",
                use_count=0,
                successful_use_count=0,
                failure_count=0,
                cross_session_success=0,
                last_used_at=None,
                health=1.0,
                updated_at=now_iso,
            )
        finally:
            if should_close:
                conn.close()

    def get_record(self, capability_id: str, *, conn: Any = None) -> Optional[SkillXPRecord]:
        should_close = False
        if conn is None:
            conn = connect(self.db_path)
            should_close = True
        try:
            row = conn.execute(
                f"SELECT capability_id, domain, version_lineage, xp, level, tier, use_count, "
                f"successful_use_count, failure_count, cross_session_success, last_used_at, health, updated_at "
                f"FROM {SKILL_XP_TABLE} WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
            return SkillXPRecord(*row) if row else None
        finally:
            if should_close:
                conn.close()

    def record_outcome(
        self,
        capability_id: str,
        *,
        success: bool,
        domain: str = "general",
        version: str = "1.0.0",
        error_msg: str = "",
        now: Optional[datetime] = None,
    ) -> SkillXPRecord:
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            rec = self.get_or_create_record(capability_id, domain=domain, version=version, conn=conn)
            ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

            new_use_count = rec.use_count + 1
            new_success_count = rec.successful_use_count + (1 if success else 0)
            new_failure_count = rec.failure_count + (0 if success else 1)
            new_health = round(new_success_count / new_use_count, 2) if new_use_count > 0 else 1.0

            conn.execute(
                f"UPDATE {SKILL_XP_TABLE} SET use_count = ?, successful_use_count = ?, failure_count = ?, "
                f"health = ?, last_used_at = ?, updated_at = ? WHERE capability_id = ?",
                (
                    new_use_count,
                    new_success_count,
                    new_failure_count,
                    new_health,
                    ts,
                    ts,
                    capability_id,
                ),
            )
            conn.commit()
            return SkillXPRecord(
                capability_id=capability_id,
                domain=rec.domain,
                version_lineage=rec.version_lineage,
                xp=rec.xp,
                level=rec.level,
                tier=rec.tier,
                use_count=new_use_count,
                successful_use_count=new_success_count,
                failure_count=new_failure_count,
                cross_session_success=rec.cross_session_success,
                last_used_at=ts,
                health=new_health,
                updated_at=ts,
            )
        finally:
            conn.close()

    def award_xp(
        self,
        capability_id: str,
        *,
        domain: str,
        version: str,
        event_type: str,
        task_id: str = "",
        session_id: str = "",
        evidence_id: str = "",
        now: Optional[datetime] = None,
    ) -> tuple[int, Optional[PublicProgressReceipt]]:
        """Award skill XP deterministically. Returns (delta_xp, receipt)."""
        xp_amount = SKILL_XP_AMOUNTS.get(event_type, 0)
        if xp_amount <= 0:
            return 0, None

        # Build idempotent deterministic event ID
        raw_key = "\x1f".join((capability_id, version, event_type, task_id, session_id))
        event_id = f"skxp_{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:20]}"
        ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        display_reason = SKILL_EVENT_DISPLAY_REASONS.get(event_type, event_type.replace("_", " "))

        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Check for deduplication
            existing = conn.execute(
                f"SELECT 1 FROM {SKILL_XP_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing:
                conn.commit()
                return 0, None

            # Get current record using existing connection
            rec = self.get_or_create_record(capability_id, domain=domain, version=version, conn=conn)
            new_xp = rec.xp + xp_amount
            new_level, new_tier, _, _, _ = calculate_level_and_tier(new_xp)

            # Insert event
            conn.execute(
                f"INSERT INTO {SKILL_XP_EVENTS_TABLE} "
                f"(event_id, capability_id, version, xp_amount, event_type, task_id, session_id, evidence_id, timestamp, display_reason) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    capability_id,
                    version,
                    xp_amount,
                    event_type,
                    task_id,
                    session_id,
                    evidence_id,
                    ts,
                    display_reason,
                ),
            )

            # Update master record
            conn.execute(
                f"UPDATE {SKILL_XP_TABLE} SET xp = ?, level = ?, tier = ?, updated_at = ? WHERE capability_id = ?",
                (new_xp, new_level, new_tier, ts, capability_id),
            )
            conn.commit()

            receipt = PublicProgressReceipt(
                system="skill",
                entity=capability_id,
                delta_xp=xp_amount,
                new_total=new_xp,
                new_tier=new_tier,
                reason=display_reason,
                timestamp=ts,
            )
            return xp_amount, receipt
        finally:
            conn.close()



def award_skill_xp(
    capability_id: str,
    domain: str,
    version: str,
    event_type: str,
    task_id: str = "",
    session_id: str = "",
    evidence_id: str = "",
    db_path: Path | str | None = None,
    now: Optional[datetime] = None,
) -> tuple[int, Optional[PublicProgressReceipt]]:
    store = SkillProficiencyStore(db_path=db_path)
    return store.award_xp(
        capability_id=capability_id,
        domain=domain,
        version=version,
        event_type=event_type,
        task_id=task_id,
        session_id=session_id,
        evidence_id=evidence_id,
        now=now,
    )


def record_skill_run_outcome(
    capability_id: str,
    *,
    success: bool,
    domain: str = "general",
    version: str = "1.0.0",
    error_msg: str = "",
    db_path: Path | str | None = None,
    now: Optional[datetime] = None,
) -> SkillXPRecord:
    store = SkillProficiencyStore(db_path=db_path)
    return store.record_outcome(
        capability_id=capability_id,
        success=success,
        domain=domain,
        version=version,
        error_msg=error_msg,
        now=now,
    )


def read_skill_xp_records(
    capability_ids: set[str],
    *,
    db_path: Path | str | None = None,
) -> dict[str, SkillXPRecord]:
    """Read audited Skill-XP records without creating a database or schema."""
    if not capability_ids:
        return {}

    from ..paths import db_path as default_db_path

    path = Path(db_path) if db_path is not None else default_db_path()
    if not path.exists():
        return {}

    records: dict[str, SkillXPRecord] = {}
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return {}

    try:
        columns = (
            "capability_id, domain, version_lineage, xp, level, tier, use_count, "
            "successful_use_count, failure_count, cross_session_success, last_used_at, health, updated_at"
        )
        ordered_ids = sorted(capability_ids)
        for start in range(0, len(ordered_ids), 500):
            batch = ordered_ids[start:start + 500]
            placeholders = ", ".join("?" for _ in batch)
            rows = connection.execute(
                f"SELECT {columns} FROM {SKILL_XP_TABLE} WHERE capability_id IN ({placeholders})",
                batch,
            ).fetchall()
            records.update({row[0]: SkillXPRecord(*row) for row in rows})
    except sqlite3.OperationalError:
        return {}
    finally:
        connection.close()
    return records

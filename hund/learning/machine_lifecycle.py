"""Fail-safe, scope-aware machine lifecycle and autonomy policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import hashlib
import sqlite3

from ..store.sqlite import connect

BASELINE_TASKS = 8
BASELINE_SESSIONS = 2


class LifecyclePhase(str, Enum):
    BOOTSTRAP = "bootstrap"
    OBSERVING = "observing"
    STANDARD = "standard"


@dataclass(frozen=True)
class LifecyclePolicy:
    phase: LifecyclePhase
    can_learn: bool = True
    can_award_xp: bool = True
    can_auto_equip: bool = False
    can_mutate_skills_autonomously: bool = False


def policy_for_phase(phase: LifecyclePhase) -> LifecyclePolicy:
    autonomous = phase == LifecyclePhase.STANDARD
    return LifecyclePolicy(
        phase=phase,
        can_auto_equip=autonomous,
        can_mutate_skills_autonomously=autonomous,
    )


class MachineLifecycle:
    """Persist lifecycle events and derive the most restrictive scope policy."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _audit_id(scope: str, action: str, reason: str, timestamp: str) -> str:
        raw = "\x1f".join((scope, action, reason, timestamp)).encode("utf-8")
        return "life_" + hashlib.sha256(raw).hexdigest()[:24]

    def initialize_scope(self, scope: str) -> LifecyclePhase:
        """Create an explicit bootstrap state without granting autonomy."""
        if not scope:
            raise ValueError("scope is required")
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """INSERT OR IGNORE INTO lifecycle_states
                       (scope, phase, onboarding_complete, updated_at)
                       VALUES (?, ?, 0, ?)""",
                    (scope, LifecyclePhase.BOOTSTRAP.value, now),
                )
            return self.get_phase(scope)
        except (sqlite3.Error, OSError):
            return LifecyclePhase.OBSERVING

    def get_phase(self, scope: str) -> LifecyclePhase:
        """Read one phase; storage failures are always fail-safe OBSERVING."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT phase FROM lifecycle_states WHERE scope = ?", (scope,)
                ).fetchone()
            if row is None:
                return LifecyclePhase.OBSERVING
            return LifecyclePhase(row[0])
        except (sqlite3.Error, OSError, ValueError):
            return LifecyclePhase.OBSERVING

    def counts(self, scope: str) -> tuple[int, int]:
        try:
            with self._connect() as conn:
                tasks = conn.execute(
                    "SELECT COUNT(*) FROM lifecycle_task_events WHERE scope = ?", (scope,)
                ).fetchone()[0]
                sessions = conn.execute(
                    "SELECT COUNT(*) FROM lifecycle_sessions WHERE scope = ?", (scope,)
                ).fetchone()[0]
            return int(tasks), int(sessions)
        except (sqlite3.Error, OSError):
            return 0, 0

    def record_task_completion(
        self, scope: str, task_id: str, session_id: str
    ) -> LifecyclePolicy:
        """Record a successful task once and atomically advance its scope."""
        if not scope or not task_id or not session_id:
            return policy_for_phase(LifecyclePhase.OBSERVING)
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """INSERT OR IGNORE INTO lifecycle_states
                       (scope, phase, onboarding_complete, updated_at)
                       VALUES (?, ?, 0, ?)""",
                    (scope, LifecyclePhase.OBSERVING.value, now),
                )
                conn.execute(
                    """UPDATE lifecycle_states SET phase = ?, updated_at = ?
                       WHERE scope = ? AND phase = ?""",
                    (
                        LifecyclePhase.OBSERVING.value, now, scope,
                        LifecyclePhase.BOOTSTRAP.value,
                    ),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO lifecycle_task_events
                       (scope, task_id, session_id, completed_at)
                       VALUES (?, ?, ?, ?)""",
                    (scope, task_id, session_id, now),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO lifecycle_sessions
                       (scope, session_id, first_seen_at) VALUES (?, ?, ?)""",
                    (scope, session_id, now),
                )
                state = conn.execute(
                    """SELECT phase, onboarding_complete FROM lifecycle_states
                       WHERE scope = ?""",
                    (scope,),
                ).fetchone()
                task_count = conn.execute(
                    "SELECT COUNT(*) FROM lifecycle_task_events WHERE scope = ?", (scope,)
                ).fetchone()[0]
                session_count = conn.execute(
                    "SELECT COUNT(*) FROM lifecycle_sessions WHERE scope = ?", (scope,)
                ).fetchone()[0]
                should_advance = bool(state[1]) or (
                    task_count >= BASELINE_TASKS and session_count >= BASELINE_SESSIONS
                )
                if should_advance and state[0] != LifecyclePhase.STANDARD.value:
                    reason = (
                        "explicit onboarding complete" if state[1]
                        else f"baseline reached: {task_count} tasks/{session_count} sessions"
                    )
                    conn.execute(
                        """UPDATE lifecycle_states SET phase = ?, updated_at = ?
                           WHERE scope = ?""",
                        (LifecyclePhase.STANDARD.value, now, scope),
                    )
                    conn.execute(
                        """INSERT INTO lifecycle_audit
                           (audit_id, scope, action, old_phase, new_phase, reason, timestamp)
                           VALUES (?, ?, 'phase_transition', ?, ?, ?, ?)""",
                        (
                            self._audit_id(scope, "phase_transition", reason, now),
                            scope, state[0], LifecyclePhase.STANDARD.value, reason, now,
                        ),
                    )
                    phase = LifecyclePhase.STANDARD
                else:
                    phase = LifecyclePhase(state[0])
            return policy_for_phase(phase)
        except (sqlite3.Error, OSError, ValueError):
            return policy_for_phase(LifecyclePhase.OBSERVING)

    def complete_onboarding(self, scope: str, reason: str = "user completed onboarding") -> LifecyclePolicy:
        """Explicitly unlock one scope with an audit trail."""
        if not scope:
            return policy_for_phase(LifecyclePhase.OBSERVING)
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT phase FROM lifecycle_states WHERE scope = ?", (scope,)
                ).fetchone()
                old_phase = row[0] if row else LifecyclePhase.OBSERVING.value
                conn.execute(
                    """INSERT INTO lifecycle_states
                       (scope, phase, onboarding_complete, updated_at)
                       VALUES (?, ?, 1, ?)
                       ON CONFLICT(scope) DO UPDATE SET
                           phase=excluded.phase,
                           onboarding_complete=1,
                           updated_at=excluded.updated_at""",
                    (scope, LifecyclePhase.STANDARD.value, now),
                )
                conn.execute(
                    """INSERT INTO lifecycle_audit
                       (audit_id, scope, action, old_phase, new_phase, reason, timestamp)
                       VALUES (?, ?, 'onboarding_complete', ?, ?, ?, ?)""",
                    (
                        self._audit_id(scope, "onboarding_complete", reason, now),
                        scope, old_phase, LifecyclePhase.STANDARD.value, reason, now,
                    ),
                )
            return policy_for_phase(LifecyclePhase.STANDARD)
        except (sqlite3.Error, OSError):
            return policy_for_phase(LifecyclePhase.OBSERVING)

    def effective_policy(self, scopes: list[str] | tuple[str, ...]) -> LifecyclePolicy:
        """Combine scopes by choosing the least autonomous phase."""
        if not scopes:
            return policy_for_phase(LifecyclePhase.OBSERVING)
        rank = {
            LifecyclePhase.BOOTSTRAP: 0,
            LifecyclePhase.OBSERVING: 1,
            LifecyclePhase.STANDARD: 2,
        }
        phases = [self.get_phase(scope) for scope in scopes]
        return policy_for_phase(min(phases, key=rank.__getitem__))


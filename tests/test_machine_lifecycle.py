"""Machine lifecycle persistence and fail-safe policy tests."""
from pathlib import Path
import sqlite3

from hund.learning.machine_lifecycle import (
    LifecyclePhase,
    MachineLifecycle,
)


def test_lifecycle_normalized_tables_idempotency(tmp_path: Path):
    lifecycle = MachineLifecycle(tmp_path / "hund.db")
    for _ in range(10):
        lifecycle.record_task_completion("workspace:a", "task-1", "session-1")
    assert lifecycle.counts("workspace:a") == (1, 1)
    assert lifecycle.get_phase("workspace:a") == LifecyclePhase.OBSERVING


def test_baseline_transition_to_standard_with_audit(tmp_path: Path):
    db_path = tmp_path / "hund.db"
    lifecycle = MachineLifecycle(db_path)
    for index in range(8):
        lifecycle.record_task_completion(
            "machine", f"task-{index}", "s1" if index < 4 else "s2"
        )
    policy = lifecycle.effective_policy(["machine"])
    assert policy.phase == LifecyclePhase.STANDARD
    assert policy.can_auto_equip
    with sqlite3.connect(db_path) as conn:
        audit = conn.execute(
            "SELECT old_phase, new_phase FROM lifecycle_audit WHERE scope='machine'"
        ).fetchone()
    assert audit == ("observing", "standard")


def test_most_restrictive_scope_policy_combination(tmp_path: Path):
    lifecycle = MachineLifecycle(tmp_path / "hund.db")
    lifecycle.complete_onboarding("machine")
    lifecycle.complete_onboarding("workspace:a")
    lifecycle.initialize_scope("domain:python")
    policy = lifecycle.effective_policy(["machine", "workspace:a", "domain:python"])
    assert policy.phase == LifecyclePhase.BOOTSTRAP
    assert not policy.can_mutate_skills_autonomously


def test_fail_safe_defaults_to_observing_on_db_error(tmp_path: Path):
    lifecycle = MachineLifecycle(tmp_path)  # directory cannot be opened as SQLite DB
    assert lifecycle.get_phase("machine") == LifecyclePhase.OBSERVING
    assert lifecycle.record_task_completion("machine", "t", "s").phase == LifecyclePhase.OBSERVING


def test_explicit_onboarding_override_audit_trail(tmp_path: Path):
    db_path = tmp_path / "hund.db"
    lifecycle = MachineLifecycle(db_path)
    policy = lifecycle.complete_onboarding("workspace:a", "confirmed by user")
    assert policy.phase == LifecyclePhase.STANDARD
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT action, reason FROM lifecycle_audit WHERE scope='workspace:a'"
        ).fetchone()
    assert row == ("onboarding_complete", "confirmed by user")


def test_scope_isolation_and_restart(tmp_path: Path):
    db_path = tmp_path / "hund.db"
    first = MachineLifecycle(db_path)
    first.complete_onboarding("workspace:a")
    second = MachineLifecycle(db_path)
    assert second.get_phase("workspace:a") == LifecyclePhase.STANDARD
    assert second.get_phase("workspace:b") == LifecyclePhase.OBSERVING

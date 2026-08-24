"""Tests for Reflection v2 and Background Learning Worker."""
from pathlib import Path
import pytest

from hund.domains.xp import award_xp, EVENT_DISCOVERY
from hund.knowledge import db as kdb
from hund.knowledge.models import KnowledgeUnit, STATUS_VALIDATED, STATUS_SUPPORTED
from hund.learning import ledger, reflection, worker
from hund.memory import db as mdb
from hund.memory.engine import record_memory


@pytest.fixture
def reflection_home(tmp_path: Path) -> Path:
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "learning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "brain" / "knowledge").mkdir(parents=True, exist_ok=True)

    # Initialize tables
    kdb.ensure_knowledge_tables(tmp_path / "knowledge" / "knowledge.db")
    conn_m = mdb.connect_memory(tmp_path / "memory" / "memory.db")
    conn_m.close()
    return tmp_path


def test_reflection_captures_memory_audit(reflection_home: Path) -> None:
    snapshot = reflection.take_snapshot(home=reflection_home)

    # Record a new memory entry
    record_memory(
        statement="Always use pytest for testing",
        db_path=reflection_home / "memory" / "memory.db",
    )

    lines = reflection.compute_reflections(snapshot, home=reflection_home)
    assert any("remembered preference:" in ln and "pytest" in ln for ln in lines)


def test_reflection_captures_knowledge_validation(reflection_home: Path) -> None:
    know_db = reflection_home / "knowledge" / "knowledge.db"
    kdb.insert_unit(
        KnowledgeUnit(id="ku1", domain="python", statement="Use pathlib", status=STATUS_SUPPORTED),
        db_path=know_db,
    )

    snapshot = reflection.take_snapshot(home=reflection_home)

    kdb.update_unit_status(
        unit_id="ku1",
        new_status=STATUS_VALIDATED,
        action="promote",
        reason="empirical validation",
        db_path=know_db,
    )

    lines = reflection.compute_reflections(snapshot, home=reflection_home)
    assert any("validated rule in python (+8 XP)" in ln for ln in lines)


def test_reflection_captures_xp_level_up(reflection_home: Path) -> None:
    h_db = reflection_home / "hund.db"
    snapshot = reflection.take_snapshot(home=reflection_home, db_path=h_db)

    # Award discovery XP
    award_xp("python", EVENT_DISCOVERY, unit_id="ku1", db_path=h_db)

    lines = reflection.compute_reflections(snapshot, home=reflection_home, db_path=h_db)
    assert any("python" in ln and "XP" in ln for ln in lines)


def test_learning_worker_processes_jobs(reflection_home: Path) -> None:
    h_db = reflection_home / "hund.db"

    # Append an event to the ledger and create a learning job
    ev_id = ledger.append_event(
        session_id="sess_1",
        turn_id=1,
        event_type="user_preference",
        source_type="user",
        payload="I prefer pytest over unittest",
        candidate_domains=["python"],
        db_path=h_db,
    )
    job_id = ledger.enqueue_job([ev_id], db_path=h_db)
    assert job_id != ""

    # Process pending jobs
    completed = worker.process_pending_learning_jobs(home=reflection_home, db_path=h_db)
    assert completed == 1

    # Verify job status in queue
    job = ledger.get_job(job_id, db_path=h_db)
    assert job["status"] == "completed"

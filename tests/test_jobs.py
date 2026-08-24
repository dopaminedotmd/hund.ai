"""Unit tests for durable learning_jobs queue."""
from pathlib import Path
import time

from hund.learning.ledger import (
    claim_next_job,
    complete_job,
    enqueue_job,
    fail_job,
    get_job,
)


def test_enqueue_and_claim_job(tmp_path: Path) -> None:
    db_file = tmp_path / "test_jobs.sqlite"

    job_id = enqueue_job(["evt_1", "evt_2"], db_path=db_file)
    assert isinstance(job_id, str) and len(job_id) > 0

    job_state = get_job(job_id, db_path=db_file)
    assert job_state is not None
    assert job_state["status"] == "pending"
    assert job_state["attempt_count"] == 0
    assert job_state["event_ids"] == ["evt_1", "evt_2"]
    assert job_state["last_error"] == ""

    # Claim next job
    claimed = claim_next_job(db_path=db_file)
    assert claimed is not None
    assert claimed["job_id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["claimed_at"] is not None

    # Claiming again when queue is empty returns None
    assert claim_next_job(db_path=db_file) is None


def test_complete_job(tmp_path: Path) -> None:
    db_file = tmp_path / "test_jobs.sqlite"

    job_id = enqueue_job(["evt_10"], db_path=db_file)
    claim_next_job(db_path=db_file)

    ok = complete_job(job_id, db_path=db_file)
    assert ok is True

    completed = get_job(job_id, db_path=db_file)
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None


def test_fail_job_retry_until_dead(tmp_path: Path) -> None:
    db_file = tmp_path / "test_jobs.sqlite"

    job_id = enqueue_job(["evt_99"], db_path=db_file)

    # 1st attempt
    claim_next_job(db_path=db_file)
    res1 = fail_job(job_id, error="Network timeout", db_path=db_file)
    assert res1 is not None
    assert res1["status"] == "pending"
    assert res1["attempt_count"] == 1
    assert res1["last_error"] == "Network timeout"
    assert res1["claimed_at"] is None

    # Can be claimed again for 2nd attempt
    claimed2 = claim_next_job(db_path=db_file)
    assert claimed2 is not None
    assert claimed2["job_id"] == job_id
    assert claimed2["attempt_count"] == 1

    # 2nd failure
    res2 = fail_job(job_id, error="Rate limited", db_path=db_file)
    assert res2 is not None
    assert res2["status"] == "pending"
    assert res2["attempt_count"] == 2
    assert res2["last_error"] == "Rate limited"

    # Can be claimed again for 3rd attempt
    claimed3 = claim_next_job(db_path=db_file)
    assert claimed3 is not None
    assert claimed3["job_id"] == job_id
    assert claimed3["attempt_count"] == 2

    # 3rd failure -> transitions to 'dead'
    res3 = fail_job(job_id, error="Fatal schema error", db_path=db_file)
    assert res3 is not None
    assert res3["status"] == "dead"
    assert res3["attempt_count"] == 3
    assert res3["last_error"] == "Fatal schema error"
    assert res3["completed_at"] is not None

    # Cannot be claimed anymore
    assert claim_next_job(db_path=db_file) is None


def test_fifo_claiming_order(tmp_path: Path) -> None:
    db_file = tmp_path / "test_jobs.sqlite"

    j1 = enqueue_job(["evt_a"], db_path=db_file)
    time.sleep(0.01)
    j2 = enqueue_job(["evt_b"], db_path=db_file)

    first = claim_next_job(db_path=db_file)
    second = claim_next_job(db_path=db_file)

    assert first is not None and first["job_id"] == j1
    assert second is not None and second["job_id"] == j2

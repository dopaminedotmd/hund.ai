"""Tests for knowledge.db canonical storage and audit trail."""
from pathlib import Path
import tempfile
import pytest

from hund.knowledge import db as kdb
from hund.knowledge.models import (
    ACTION_CREATE,
    ACTION_PROMOTE,
    KnowledgeUnit,
    STATUS_CANDIDATE,
    STATUS_SUPPORTED,
    STATUS_VALIDATED,
)


@pytest.fixture
def temp_knowledge_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_knowledge.db"
    kdb.ensure_knowledge_tables(db_file)
    return db_file


def test_insert_and_get_knowledge_unit(temp_knowledge_db: Path) -> None:
    unit = KnowledgeUnit(
        id="know_test1",
        domain="python/fastapi",
        statement="Always use Annotated for dependency injection",
        trigger="FastAPI endpoints",
        status=STATUS_CANDIDATE,
        confidence=0.6,
        evidence_ids=["ev_123"],
        deps={"fastapi": ">=0.95.0"},
    )
    uid = kdb.insert_unit(unit, db_path=temp_knowledge_db)
    assert uid == "know_test1"

    fetched = kdb.get_unit("know_test1", db_path=temp_knowledge_db)
    assert fetched is not None
    assert fetched.domain == "python/fastapi"
    assert fetched.statement == "Always use Annotated for dependency injection"
    assert fetched.status == STATUS_CANDIDATE
    assert fetched.confidence == 0.6
    assert fetched.evidence_ids == ["ev_123"]
    assert fetched.deps == {"fastapi": ">=0.95.0"}

    # Audit trail check
    audit = kdb.list_audit_trail("know_test1", db_path=temp_knowledge_db)
    assert len(audit) == 1
    assert audit[0].action == ACTION_CREATE
    assert audit[0].new_status == STATUS_CANDIDATE


def test_list_units_filter(temp_knowledge_db: Path) -> None:
    u1 = KnowledgeUnit(id="u1", domain="python", statement="rule 1", status=STATUS_CANDIDATE, confidence=0.5)
    u2 = KnowledgeUnit(id="u2", domain="python", statement="rule 2", status=STATUS_VALIDATED, confidence=0.9)
    u3 = KnowledgeUnit(id="u3", domain="rust", statement="rule 3", status=STATUS_CANDIDATE, confidence=0.7)

    kdb.insert_unit(u1, db_path=temp_knowledge_db)
    kdb.insert_unit(u2, db_path=temp_knowledge_db)
    kdb.insert_unit(u3, db_path=temp_knowledge_db)

    # Filter by domain
    py_units = kdb.list_units(domain="python", db_path=temp_knowledge_db)
    assert len(py_units) == 2
    assert py_units[0].id == "u2"  # ordered by confidence DESC

    # Filter by status
    val_units = kdb.list_units(status=STATUS_VALIDATED, db_path=temp_knowledge_db)
    assert len(val_units) == 1
    assert val_units[0].id == "u2"


def test_update_unit_status_and_audit(temp_knowledge_db: Path) -> None:
    u = KnowledgeUnit(id="u_trans", domain="git", statement="always use worktrees", status=STATUS_CANDIDATE, confidence=0.5)
    kdb.insert_unit(u, db_path=temp_knowledge_db)

    # Transition candidate -> supported
    ok = kdb.update_unit_status(
        unit_id="u_trans",
        new_status=STATUS_SUPPORTED,
        action=ACTION_PROMOTE,
        reason="verified by 2 successful runs",
        confidence_delta=0.2,
        db_path=temp_knowledge_db,
    )
    assert ok is True

    updated = kdb.get_unit("u_trans", db_path=temp_knowledge_db)
    assert updated is not None
    assert updated.status == STATUS_SUPPORTED
    assert updated.confidence == pytest.approx(0.7, 0.01)

    trail = kdb.list_audit_trail("u_trans", db_path=temp_knowledge_db)
    assert len(trail) == 2
    assert trail[1].old_status == STATUS_CANDIDATE
    assert trail[1].new_status == STATUS_SUPPORTED
    assert trail[1].action == ACTION_PROMOTE

"""Tests for CommitController policy, promotion, demotion, and materialized JSON sync."""
import json
from pathlib import Path
import pytest

from hund.knowledge import db as kdb
from hund.knowledge.models import (
    STATUS_CANDIDATE,
    STATUS_DEPRECATED,
    STATUS_SUPPORTED,
    STATUS_VALIDATED,
)
from hund.learning.commit_controller import CommitController
from hund.learning.evaluator import CandidateProposal


@pytest.fixture
def controller(tmp_path: Path) -> CommitController:
    db_file = tmp_path / "knowledge.db"
    kdb.ensure_knowledge_tables(db_file)
    return CommitController(db_path=db_file, home=tmp_path)


def test_commit_candidate_policy(controller: CommitController, tmp_path: Path) -> None:
    proposal = CandidateProposal(
        proposition="Always use pyproject.toml instead of setup.py for packaging",
        scope={"type": "domain", "id": "python/packaging"},
        kind="rule",
        relation_to_existing="NEW",
        confidence=0.85,
        suggested_action="store_candidate",
        evidence_ids=["ev_pack1"],
    )

    unit_id, msg = controller.commit_candidate(proposal)
    assert unit_id != ""
    assert "stored as candidate" in msg

    # Verify initial status is CANDIDATE (never directly validated!)
    unit = kdb.get_unit(unit_id, db_path=controller.db_path)
    assert unit is not None
    assert unit.status == STATUS_CANDIDATE
    assert unit.confidence <= 0.6  # Capped initial confidence

    # Verify JSON file was created and synced
    json_path = tmp_path / "brain" / "knowledge" / "python" / "packaging.json"
    if not json_path.exists():
        # Might be flattened or hierarchical depending on canonicalization
        json_path = tmp_path / "brain" / "knowledge" / f"{unit.domain}.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data["units"]) == 1
    assert data["units"][0]["id"] == unit_id
    assert data["units"][0]["status"] == STATUS_CANDIDATE


def test_promotion_policy_lifecycle(controller: CommitController) -> None:
    proposal = CandidateProposal(
        proposition="Use pytest-asyncio for async test fixtures",
        scope={"type": "domain", "id": "python/testing"},
        kind="rule",
        relation_to_existing="NEW",
        confidence=0.6,
        suggested_action="store_candidate",
    )
    unit_id, _ = controller.commit_candidate(proposal)

    # 1. First success
    controller.record_usage_and_validate(unit_id, success=True)
    u1 = kdb.get_unit(unit_id, db_path=controller.db_path)
    assert u1.status == STATUS_CANDIDATE
    assert u1.support_count == 1

    # 2. Second success -> promote to SUPPORTED
    controller.record_usage_and_validate(unit_id, success=True)
    u2 = kdb.get_unit(unit_id, db_path=controller.db_path)
    assert u2.status == STATUS_SUPPORTED
    assert u2.support_count == 2

    # 3. Third & Fourth success -> promote to VALIDATED
    controller.record_usage_and_validate(unit_id, success=True)
    controller.record_usage_and_validate(unit_id, success=True)
    u4 = kdb.get_unit(unit_id, db_path=controller.db_path)
    assert u4.status == STATUS_VALIDATED
    assert u4.support_count == 4
    assert u4.last_validated_at is not None


def test_demotion_policy_lifecycle(controller: CommitController) -> None:
    proposal = CandidateProposal(
        proposition="Run thread-unsafe shared globals in background",
        scope={"type": "domain", "id": "python"},
        kind="rule",
        relation_to_existing="NEW",
        confidence=0.5,
        suggested_action="store_candidate",
    )
    unit_id, _ = controller.commit_candidate(proposal)

    # 1. Failure 1
    controller.record_usage_and_validate(unit_id, success=False)
    u1 = kdb.get_unit(unit_id, db_path=controller.db_path)
    assert u1.contradiction_count == 1

    # 2. Failure 2 -> triggers deprecation
    controller.record_usage_and_validate(unit_id, success=False)
    u2 = kdb.get_unit(unit_id, db_path=controller.db_path)
    assert u2.status == STATUS_DEPRECATED
    assert u2.contradiction_count == 2

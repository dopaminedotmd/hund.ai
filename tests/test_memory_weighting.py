"""Unit tests for memory evidence weighting and promotion thresholds."""
from pathlib import Path

from hund.memory.engine import (
    PROMOTION_THRESHOLD,
    WEIGHT_ASSISTANT_INFERENCE,
    WEIGHT_CONTRADICTION,
    WEIGHT_EXPLICIT_PREFERENCE,
    WEIGHT_REPEATED_BEHAVIOR,
    get_audit_history,
    record_contradiction,
    record_memory,
    reinforce_memory,
)
from hund.memory.models import ACTION_FLAG_CONFLICT, ACTION_PROMOTE, STATUS_DRAFT, STATUS_FLAGGED, STATUS_VERIFIED


def test_explicit_user_memory_promoted_immediately(tmp_path: Path) -> None:
    db_file = tmp_path / "test_weight.db"

    item = record_memory(
        statement="speaks swedish",
        source_type="user",
        db_path=db_file,
    )
    assert item.confidence == WEIGHT_EXPLICIT_PREFERENCE
    assert item.status == STATUS_VERIFIED


def test_inference_starts_as_draft_and_promotes_with_evidence(tmp_path: Path) -> None:
    db_file = tmp_path / "test_weight.db"

    # Assistant inference starts as draft in project memory
    item = record_memory(
        statement="frequently uses pytest",
        scope="project:repo_1",
        source_type="inference",
        db_path=db_file,
    )
    assert item.confidence == WEIGHT_ASSISTANT_INFERENCE
    assert item.status == STATUS_DRAFT

    # 1st reinforcement: 0.15 + 0.35 = 0.50 -> still draft
    item = reinforce_memory(item.memory_id, signal_weight=WEIGHT_REPEATED_BEHAVIOR, db_path=db_file)
    assert item is not None
    assert round(item.confidence, 2) == 0.50
    assert item.status == STATUS_DRAFT

    # 2nd reinforcement: 0.50 + 0.35 = 0.85 -> still draft
    item = reinforce_memory(item.memory_id, signal_weight=WEIGHT_REPEATED_BEHAVIOR, db_path=db_file)
    assert item is not None
    assert round(item.confidence, 2) == 0.85
    assert item.status == STATUS_DRAFT

    # 3rd reinforcement: 0.85 + 0.35 = 1.20 >= 1.0 -> promoted to verified!
    item = reinforce_memory(item.memory_id, signal_weight=WEIGHT_REPEATED_BEHAVIOR, db_path=db_file)
    assert item is not None
    assert round(item.confidence, 2) == 1.20
    assert item.status == STATUS_VERIFIED

    # Check promotion audit trail
    audits = get_audit_history(item.memory_id, db_path=db_file)
    actions = [a.action for a in audits]
    assert ACTION_PROMOTE in actions


def test_contradiction_handling_and_flagging(tmp_path: Path) -> None:
    db_file = tmp_path / "test_weight.db"

    item = record_memory(
        statement="uses tabs instead of spaces",
        source_type="user",
        db_path=db_file,
    )
    assert item.confidence == 1.0

    # 1st contradiction: 1.0 - 0.8 = 0.2 < 0.5 -> flagged!
    item = record_contradiction(item.memory_id, reason="observed spaces in new file", db_path=db_file)
    assert item is not None
    assert round(item.confidence, 2) == 0.20
    assert item.contradiction_count == 1
    assert item.status == STATUS_FLAGGED

    audits = get_audit_history(item.memory_id, db_path=db_file)
    assert any(a.action == ACTION_FLAG_CONFLICT for a in audits)

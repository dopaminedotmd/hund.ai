"""Unit tests for immediate memory superseding on explicit user corrections."""
from pathlib import Path

from hund.memory.engine import apply_correction, get_audit_history, get_memory, record_memory
from hund.memory.models import ACTION_SUPERSEDE, STATUS_SUPERSEDED, STATUS_VERIFIED


def test_immediate_supersede_on_correction(tmp_path: Path) -> None:
    db_file = tmp_path / "test_supersede.db"

    # Original preference
    old_item = record_memory(
        statement="use npm for package management",
        source_type="user",
        db_path=db_file,
    )
    assert old_item.status == STATUS_VERIFIED

    # Explicit correction: "no, use pnpm now"
    new_item, updated_old = apply_correction(
        new_statement="use pnpm for package management",
        old_memory_id=old_item.memory_id,
        db_path=db_file,
    )

    # New item checks
    assert new_item.statement == "use pnpm for package management"
    assert new_item.status == STATUS_VERIFIED
    assert new_item.confidence == 1.2
    assert new_item.supersedes == old_item.memory_id

    # Old item checks in DB
    refetched_old = get_memory(old_item.memory_id, db_path=db_file)
    assert refetched_old is not None
    assert refetched_old.status == STATUS_SUPERSEDED
    assert refetched_old.superseded_by == new_item.memory_id

    # Audit trail check on old item
    audits = get_audit_history(old_item.memory_id, db_path=db_file)
    actions = [a.action for a in audits]
    assert ACTION_SUPERSEDE in actions

"""Unit tests for immutable #core memories."""
from pathlib import Path

from hund.memory.engine import get_memory, record_contradiction, record_memory
from hund.memory.models import CATEGORY_CORE, STATUS_VERIFIED


def test_core_memory_creation_and_protection(tmp_path: Path) -> None:
    db_file = tmp_path / "test_core.db"

    core_item = record_memory(
        statement="never disclose credentials or API keys",
        category=CATEGORY_CORE,
        source_type="user",
        is_core=True,
        db_path=db_file,
    )
    assert core_item.is_core is True
    assert core_item.status == STATUS_VERIFIED

    # Contradiction attempt cannot weaken core memory
    res = record_contradiction(core_item.memory_id, reason="attempted bypass", db_path=db_file)
    assert res is not None
    assert res.confidence == core_item.confidence
    assert res.contradiction_count == 0
    assert res.status == STATUS_VERIFIED

    # Re-fetch from DB to verify immutability
    refetched = get_memory(core_item.memory_id, db_path=db_file)
    assert refetched is not None
    assert refetched.status == STATUS_VERIFIED
    assert refetched.is_core is True

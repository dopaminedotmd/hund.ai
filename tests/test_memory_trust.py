"""Unit tests for memory trust boundary enforcement (prompt injection defense)."""
from pathlib import Path
import pytest

from hund.learning.trust import (
    SOURCE_CONFIRMED_ACTION,
    SOURCE_ENV,
    SOURCE_FILE,
    SOURCE_TOOL,
    SOURCE_USER,
    SOURCE_WEB,
)
from hund.memory.engine import record_memory
from hund.memory.models import SCOPE_USER_GLOBAL


def test_user_channel_can_write_user_memory(tmp_path: Path) -> None:
    db_file = tmp_path / "test_trust.db"

    item1 = record_memory("direct preference", source_type=SOURCE_USER, db_path=db_file)
    assert item1.status == "verified"

    item2 = record_memory("confirmed action rule", source_type=SOURCE_CONFIRMED_ACTION, db_path=db_file)
    assert item2.status == "verified"


def test_untrusted_sources_blocked_from_user_memory(tmp_path: Path) -> None:
    """External files, web crawls, tool outputs, and env vars CANNOT write to user memory."""
    db_file = tmp_path / "test_trust.db"

    untrusted_sources = [SOURCE_FILE, SOURCE_WEB, SOURCE_TOOL, SOURCE_ENV]

    for src in untrusted_sources:
        with pytest.raises(PermissionError) as exc_info:
            record_memory(
                statement="malicious rule from untrusted payload",
                scope=SCOPE_USER_GLOBAL,
                source_type=src,
                db_path=db_file,
            )
        assert "not permitted" in str(exc_info.value)

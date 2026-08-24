"""Unit tests for deterministic context-gating and character budget limits."""
from pathlib import Path

from hund.memory.engine import record_memory
from hund.memory.gating import select_memory_bullets
from hund.memory.models import CATEGORY_CORE, SCOPE_DOMAIN_PREFIX, SCOPE_PROJECT_PREFIX, SCOPE_USER_GLOBAL


def test_context_gating_priority_order(tmp_path: Path) -> None:
    db_file = tmp_path / "test_gating.db"

    # Core item
    record_memory("core security rule", is_core=True, db_path=db_file)
    # Global preference
    record_memory("prefers swedish", scope=SCOPE_USER_GLOBAL, db_path=db_file)
    # Project-specific rule
    record_memory("uses fastapi router", scope=f"{SCOPE_PROJECT_PREFIX}ws_123", db_path=db_file)
    # Domain-specific rule
    record_memory("cache liquid loops", scope=f"{SCOPE_DOMAIN_PREFIX}shopify", db_path=db_file)

    # 1. Without workspace or domain -> core + global
    bullets = select_memory_bullets(db_path=db_file)
    assert bullets == ["core security rule", "prefers swedish"]

    # 2. With workspace -> core + global + project
    bullets_proj = select_memory_bullets(db_path=db_file, workspace_id="ws_123")
    assert bullets_proj == ["core security rule", "prefers swedish", "uses fastapi router"]

    # 3. With workspace + active domain -> core + global + project + domain
    bullets_all = select_memory_bullets(
        db_path=db_file,
        workspace_id="ws_123",
        active_domains=["shopify"],
    )
    assert bullets_all == [
        "core security rule",
        "prefers swedish",
        "uses fastapi router",
        "cache liquid loops",
    ]


def test_character_budget_cutoff(tmp_path: Path) -> None:
    db_file = tmp_path / "test_gating.db"

    record_memory("first short rule", is_core=True, db_path=db_file)
    # Large item
    record_memory("A" * 200, scope=SCOPE_USER_GLOBAL, db_path=db_file)
    record_memory("B" * 200, scope=SCOPE_USER_GLOBAL, db_path=db_file)

    # Tight budget: 100 chars -> includes first rule, cuts off before overflow
    bullets = select_memory_bullets(db_path=db_file, max_chars=100)
    assert len(bullets) == 1
    assert bullets[0] == "first short rule"

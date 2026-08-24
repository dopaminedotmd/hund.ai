"""Unit tests for unified turn context resolver."""
from pathlib import Path

from hund.context_resolver import resolve_turn_context
from hund.memory.engine import record_memory
from hund.memory.models import SCOPE_PROJECT_PREFIX, SCOPE_USER_GLOBAL


def test_resolve_turn_context_assembly(tmp_path: Path) -> None:
    # Setup mock workspace files
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "fastapi-demo"
dependencies = [
    "fastapi>=0.100.0",
    "pydantic>=2.0.0",
]
""",
        encoding="utf-8",
    )

    db_file = tmp_path / "memory" / "memory.db"

    # Add user preference
    record_memory("always write concise code", scope=SCOPE_USER_GLOBAL, is_core=False, db_path=db_file)

    # Add core rule
    record_memory("never leak secrets", is_core=True, db_path=db_file)

    ctx = resolve_turn_context(
        workspace_path=tmp_path,
        user_query="create a new route",
        home=tmp_path,
        max_chars=2000,
    )

    assert ctx.workspace_id is not None
    assert "fastapi" in ctx.workspace_deps
    assert "pydantic" in ctx.workspace_deps

    # Verify prompt bullets include core rule and user preference
    assert "never leak secrets" in ctx.prompt_bullets
    assert "always write concise code" in ctx.prompt_bullets
    assert ctx.char_count > 0

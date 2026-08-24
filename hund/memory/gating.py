"""Deterministic context-gating selector for prompt memory injection."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .db import connect_memory
from .engine import list_active_memories
from .models import (
    CATEGORY_CORE,
    SCOPE_DOMAIN_PREFIX,
    SCOPE_PROJECT_PREFIX,
    SCOPE_USER_GLOBAL,
    STATUS_VERIFIED,
    MemoryItem,
)


def select_memory_bullets(
    home: Optional[Path] = None,
    db_path: Path | str | None = None,
    workspace_id: str | None = None,
    active_domains: list[str] | None = None,
    max_chars: int = 4000,
) -> list[str]:
    """Select prioritized memory bullets for system prompt within character budget.

    Priority order:
    1. #core items (immutable security/language invariants)
    2. Global verified user preferences
    3. Project-specific verified memories for current workspace
    4. Domain-specific verified memories for active domains

    Falls back to legacy user.md bullets if no database entries exist.
    """
    if db_path is None and home is not None:
        actual_db_path = home / "memory" / "memory.db"
    elif db_path is not None:
        actual_db_path = Path(db_path)
    else:
        from ..paths import memory_db_path

        actual_db_path = memory_db_path()

    selected_bullets: list[str] = []
    current_char_count = 0
    seen_statements: set[str] = set()

    def _try_add(statement: str) -> bool:
        nonlocal current_char_count
        clean = statement.strip()
        if not clean or clean in seen_statements:
            return True
        # Bullet overhead: "- " + statement + "\n"
        added_len = len(clean) + 4
        if current_char_count + added_len > max_chars and selected_bullets:
            return False
        selected_bullets.append(clean)
        seen_statements.add(clean)
        current_char_count += added_len
        return True

    # 1. Fetch from memory.db if database file exists
    if actual_db_path.exists():
        conn = connect_memory(actual_db_path)

        # 1a. Core items (highest priority)
        core_rows = conn.execute(
            """SELECT * FROM memory
               WHERE status = 'verified' AND (is_core = 1 OR category = 'core')
               ORDER BY confidence DESC, first_seen ASC, rowid ASC"""
        ).fetchall()
        for r in core_rows:
            item = MemoryItem.from_row(r)
            _try_add(item.statement)

        # 1b. Global verified preferences
        global_rows = conn.execute(
            """SELECT * FROM memory
               WHERE status = 'verified' AND scope = 'user_global' AND is_core = 0 AND category != 'core'
               ORDER BY confidence DESC, first_seen ASC, rowid ASC"""
        ).fetchall()
        for r in global_rows:
            item = MemoryItem.from_row(r)
            if not _try_add(item.statement):
                break

        # 1c. Project-specific memories
        if workspace_id:
            project_scope = f"{SCOPE_PROJECT_PREFIX}{workspace_id}"
            proj_rows = conn.execute(
                """SELECT * FROM memory
                   WHERE status = 'verified' AND scope = ?
                   ORDER BY confidence DESC, first_seen ASC, rowid ASC""",
                (project_scope,),
            ).fetchall()
            for r in proj_rows:
                item = MemoryItem.from_row(r)
                if not _try_add(item.statement):
                    break

        # 1d. Domain-specific memories
        if active_domains:
            for domain in active_domains:
                domain_scope = f"{SCOPE_DOMAIN_PREFIX}{domain}"
                dom_rows = conn.execute(
                    """SELECT * FROM memory
                       WHERE status = 'verified' AND scope = ?
                       ORDER BY confidence DESC, first_seen ASC, rowid ASC""",
                    (domain_scope,),
                ).fetchall()
                for r in dom_rows:
                    item = MemoryItem.from_row(r)
                    if not _try_add(item.statement):
                        break

        conn.close()

    # 2. If nothing selected from DB, fall back to legacy user.md file
    if not selected_bullets:
        from .view import USER_MD_SEED

        user_md_path = (home / "memory" / "user.md") if home else None
        if user_md_path is None:
            from ..paths import memory_user_path

            user_md_path = memory_user_path()

        if user_md_path.exists():
            for line in user_md_path.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s.startswith("- "):
                    stmt = s[2:].strip()
                    if not _try_add(stmt):
                        break

    return selected_bullets

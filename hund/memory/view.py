"""Materialized view renderer and atomic file writer for user.md."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .db import connect_memory
from .engine import list_active_memories
from .models import (
    CATEGORY_BIOGRAPHICAL_FACT,
    CATEGORY_CORE,
    CATEGORY_PROJECT_STATE,
    CATEGORY_STABLE_PREFERENCE,
    CATEGORY_TEMPORARY_CONTEXT,
    CATEGORY_WORKFLOW_HABIT,
    CATEGORY_WORKING_PREFERENCE,
    SCOPE_USER_GLOBAL,
    MemoryItem,
)

USER_MD_SEED = """\
# Användarprofil
# hund läser rader som börjar med '- ' som minne. Redigera fritt.
# kör: hund memory update user
"""


def render_user_md(db_path: Path | str | None = None) -> str:
    """Render the materialized markdown view of active verified user memories."""
    memories = list_active_memories(scope=SCOPE_USER_GLOBAL, db_path=db_path)
    if not memories:
        return USER_MD_SEED

    core_items: list[str] = []
    pref_items: list[str] = []
    bio_items: list[str] = []
    other_items: list[str] = []

    for m in memories:
        bullet = f"- {m.statement}"
        if m.is_core or m.category == CATEGORY_CORE:
            core_items.append(bullet)
        elif m.category in (
            CATEGORY_STABLE_PREFERENCE,
            CATEGORY_WORKING_PREFERENCE,
            CATEGORY_WORKFLOW_HABIT,
        ):
            pref_items.append(bullet)
        elif m.category == CATEGORY_BIOGRAPHICAL_FACT:
            bio_items.append(bullet)
        else:
            other_items.append(bullet)

    sections: list[str] = [
        "# Användarprofil (Materialized View)",
        "# Genererad automatiskt från memory.db. Ändringar synkas.",
    ]

    if core_items:
        sections.append("")
        sections.append("## Core (Immutable)")
        sections.extend(core_items)

    if pref_items:
        sections.append("")
        sections.append("## Preferences & Habits")
        sections.extend(pref_items)

    if bio_items:
        sections.append("")
        sections.append("## Biographical Facts")
        sections.extend(bio_items)

    if other_items:
        sections.append("")
        sections.append("## Context & State")
        sections.extend(other_items)

    return "\n".join(sections) + "\n"


def sync_user_md(home: Optional[Path] = None, db_path: Path | str | None = None) -> Path:
    """Atomically write the materialized view to user.md.

    Writes to user.md.tmp, fsyncs, and performs an atomic rename.
    """
    if home is not None:
        target_dir = home / "memory"
    else:
        from ..paths import memory_dir

        target_dir = memory_dir()

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "user.md"
    tmp_path = target_dir / f".user.md.tmp.{os.getpid()}"

    content = render_user_md(db_path=db_path)

    # Atomic write: write -> fsync -> replace
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, target_path)
    return target_path

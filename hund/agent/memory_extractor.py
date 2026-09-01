"""Bounded, deterministic turn-end memory capture."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from ..learning.redactor import redact_text
from ..learning.trust import SOURCE_INFERENCE, SOURCE_USER
from ..memory.engine import list_active_memories, record_memory
from ..memory.models import (
    CATEGORY_BIOGRAPHICAL_FACT,
    CATEGORY_STABLE_PREFERENCE,
    CATEGORY_TEMPORARY_CONTEXT,
    MemoryItem,
    SCOPE_PROJECT_PREFIX,
    SCOPE_USER_GLOBAL,
    STATUS_VERIFIED,
)
from ..memory.view import sync_user_md

_PREFIX_STRIP = re.compile(
    r"^(?:(?:kom\s+ihåg\s+att|glöm\s+inte\s+att|kom\s+ihag\s+att|glom\s+inte\s+att|remember\s+that|please\s+remember\s+that|note\s+that)\s+)+",
    re.IGNORECASE,
)

_NAME = re.compile(
    r"(?:^|(?:\b(?:and|och|samt)\b|[.!?])\s*)\s*(?:my name is|jag heter|mitt namn är|mitt namn ar)\s+"
    r"([\wÅÄÖåäö'-]+(?:\s+[\wÅÄÖåäö'-]+){0,3})"
    r"(?=\s+(?:and|och|samt)\b|[.!?]|$)",
    re.IGNORECASE,
)
_FAVORITE = re.compile(
    r"(?:^|(?:\b(?:and|och|samt)\b|[.!?])\s*)\s*(?:(?:mitt\s+)?favorit(\w*)|(?:my\s+)?favorite\s+(\w+))\s+(?:är|ar|is)\s+"
    r"([^.!?\n]+?)(?=\s+(?:and|och|samt)\b|[.!?]|$)",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"(?:^|(?:\b(?:and|och|samt)\b|[.!?])\s*)\s*(?:i prefer|jag föredrar|jag foredrar|jag gillar|i like|jag vill ha|i want|jag använder|i use)\s+"
    r"([^.!?\n]+?)(?=\s+(?:and|och|samt)\b|[.!?]|$)",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return value.strip(" \t\r\n\"'")


def extract_and_record_memories(
    user_text: str,
    *,
    inference_candidates: Iterable[str] = (),
    workspace_id: str = "",
    evidence_id: str,
    db_path: Path | str | None = None,
) -> list[MemoryItem]:
    """Record explicit user facts as verified and model candidates as draft."""
    from ..paths import memory_db_path

    actual_db_path = Path(db_path) if db_path is not None else memory_db_path()
    candidates: list[tuple[str, str, str, str]] = []
    cleaned_user_text = _PREFIX_STRIP.sub("", user_text.strip())

    for match in _NAME.finditer(cleaned_user_text):
        name_val = _clean(match.group(1))
        if name_val:
            candidates.append(
                (f"User's name is {name_val}", SCOPE_USER_GLOBAL,
                 CATEGORY_BIOGRAPHICAL_FACT, SOURCE_USER)
            )

    for match in _FAVORITE.finditer(cleaned_user_text):
        kind = _clean(match.group(1) or match.group(2) or "tool")
        val = _clean(match.group(3))
        if val:
            candidates.append(
                (f"User's favorite {kind} is {val}", SCOPE_USER_GLOBAL,
                 CATEGORY_STABLE_PREFERENCE, SOURCE_USER)
            )

    for match in _PREFERENCE.finditer(cleaned_user_text):
        pref_val = _clean(match.group(1))
        if pref_val:
            candidates.append(
                (f"User prefers {pref_val}", SCOPE_USER_GLOBAL,
                 CATEGORY_STABLE_PREFERENCE, SOURCE_USER)
            )
    if workspace_id:
        for statement in list(inference_candidates)[:3]:
            candidates.append(
                (statement, f"{SCOPE_PROJECT_PREFIX}{workspace_id}",
                 CATEGORY_TEMPORARY_CONTEXT, SOURCE_INFERENCE)
            )

    existing = {
        (item.scope, item.category, item.statement.casefold()): item
        for item in list_active_memories(
            include_drafts=True, db_path=actual_db_path, limit=500
        )
    }
    recorded: list[MemoryItem] = []
    for statement, scope, category, source_type in candidates:
        redacted = redact_text(_clean(statement), max_chars=200)
        if redacted.blocked_fields or not redacted.text:
            continue
        key = (scope, category, redacted.text.casefold())
        current = existing.get(key)
        if current is not None and evidence_id in current.evidence_ids:
            recorded.append(current)
            continue
        item = record_memory(
            statement=redacted.text,
            scope=scope,
            category=category,
            source_type=source_type,
            evidence_ids=[evidence_id],
            db_path=actual_db_path,
        )
        existing[key] = item
        recorded.append(item)

    if any(item.status == STATUS_VERIFIED for item in recorded):
        sync_user_md(home=actual_db_path.parent.parent, db_path=actual_db_path)
    return recorded

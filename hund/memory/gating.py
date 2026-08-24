"""Fail-closed read-side gate for untrusted personal memory."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Optional

from .db import connect_memory
from .models import (
    CATEGORY_BEHAVIORAL,
    CATEGORY_BIOGRAPHICAL_FACT,
    CATEGORY_CONTEXTUAL,
    CATEGORY_CORE,
    CATEGORY_PROJECT_STATE,
    CATEGORY_SENSITIVE,
    CATEGORY_STABLE_PREFERENCE,
    CATEGORY_TEMPORARY_CONTEXT,
    CATEGORY_WORKFLOW_HABIT,
    CATEGORY_WORKING_PREFERENCE,
    SCOPE_DOMAIN_PREFIX,
    SCOPE_PROJECT_PREFIX,
    SCOPE_USER_GLOBAL,
    MemoryItem,
)

_POLICY_INJECTION = re.compile(
    r"\b(ignore|bypass|override|disable|skip|kringgå|ignorera)\b.{0,48}"
    r"\b(safety|policy|confirmation|permission|git|säkerhet|bekräftelse|behörighet)\b",
    re.IGNORECASE,
)
_SENSITIVE = re.compile(
    r"\b(health|diagnosis|religion|ethnicity|sexual|politic|medical|"
    r"hälsa|diagnos|religion|etnicitet|sexuell|politisk)\w*\b",
    re.IGNORECASE,
)
_WORDS = re.compile(r"[a-zA-ZÅÄÖåäö0-9_+#.-]{3,}")
_STYLE_TERMS = {
    "language", "swedish", "english", "svenska", "engelska", "concise",
    "kort", "format", "style", "stil", "pytest", "unittest", "code", "kod",
}


def _category(item: MemoryItem) -> str:
    if item.is_core or item.category == CATEGORY_CORE:
        return CATEGORY_CORE
    if item.category in {
        CATEGORY_BEHAVIORAL, CATEGORY_STABLE_PREFERENCE,
        CATEGORY_WORKING_PREFERENCE, CATEGORY_WORKFLOW_HABIT,
    }:
        return CATEGORY_BEHAVIORAL
    if item.category == CATEGORY_SENSITIVE or _SENSITIVE.search(item.statement):
        return CATEGORY_SENSITIVE
    if item.category in {
        CATEGORY_CONTEXTUAL, CATEGORY_BIOGRAPHICAL_FACT,
        CATEGORY_PROJECT_STATE, CATEGORY_TEMPORARY_CONTEXT,
    }:
        return CATEGORY_CONTEXTUAL
    return CATEGORY_CONTEXTUAL


def _explicitly_relevant(statement: str, query: str) -> bool:
    if not query.strip():
        return True  # compatibility for direct administrative memory views
    query_words = {word.casefold() for word in _WORDS.findall(query)}
    memory_words = {word.casefold() for word in _WORDS.findall(statement)}
    return bool(query_words & memory_words)


class MemoryApplicationGate:
    """Classify and filter memory as data, never executable policy."""

    def should_apply(
        self,
        item: MemoryItem,
        *,
        user_query: str,
        workspace_facts: Iterable[str] = (),
    ) -> bool:
        statement = item.statement.strip()
        if not statement or _POLICY_INJECTION.search(statement):
            return False
        category = _category(item)
        if category == CATEGORY_SENSITIVE:
            return _explicitly_relevant(statement, user_query) and bool(user_query.strip())
        if category == CATEGORY_CONTEXTUAL:
            return _explicitly_relevant(statement, user_query)
        if category == CATEGORY_BEHAVIORAL:
            words = {word.casefold() for word in _WORDS.findall(statement)}
            relevant = not user_query.strip() or bool(words & _STYLE_TERMS)
            relevant = relevant or _explicitly_relevant(statement, user_query)
            if not relevant:
                return False
        facts = {fact.casefold() for fact in workspace_facts}
        lower = statement.casefold()
        if "unittest" in lower and any("pytest" in fact for fact in facts):
            return False
        if "pytest" in lower and any("unittest" in fact for fact in facts):
            return False
        return True

    def filter(
        self,
        items: Iterable[MemoryItem],
        *,
        user_query: str,
        workspace_facts: Iterable[str] = (),
        max_chars: int = 4000,
    ) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        used = 0
        for item in items:
            if not self.should_apply(
                item, user_query=user_query, workspace_facts=workspace_facts
            ):
                continue
            statement = item.statement.strip()
            if statement in seen:
                continue
            cost = len(statement) + 4
            if used + cost > max_chars:
                break
            selected.append(statement)
            seen.add(statement)
            used += cost
        return selected


def select_memory_bullets(
    home: Optional[Path] = None,
    db_path: Path | str | None = None,
    workspace_id: str | None = None,
    active_domains: list[str] | None = None,
    max_chars: int = 4000,
    user_query: str = "",
    workspace_facts: Iterable[str] = (),
) -> list[str]:
    """Load verified memory and apply the gate; any failure yields zero memories."""
    try:
        if db_path is None and home is not None:
            actual_db_path = home / "memory" / "memory.db"
        elif db_path is not None:
            actual_db_path = Path(db_path)
        else:
            from ..paths import memory_db_path
            actual_db_path = memory_db_path()
        if not actual_db_path.exists():
            return []
        scopes = [SCOPE_USER_GLOBAL]
        if workspace_id:
            scopes.append(f"{SCOPE_PROJECT_PREFIX}{workspace_id}")
        scopes.extend(
            f"{SCOPE_DOMAIN_PREFIX}{domain}" for domain in (active_domains or [])
        )
        placeholders = ",".join("?" for _ in scopes)
        conn = connect_memory(actual_db_path)
        try:
            rows = conn.execute(
                f"""SELECT * FROM memory
                    WHERE status='verified'
                      AND (is_core=1 OR category='core' OR scope IN ({placeholders}))
                    ORDER BY
                      CASE WHEN is_core=1 OR category='core' THEN 0
                           WHEN scope='user_global' THEN 1
                           WHEN scope LIKE 'project:%' THEN 2 ELSE 3 END,
                      confidence DESC, first_seen ASC, rowid ASC
                    LIMIT 256""",
                scopes,
            ).fetchall()
        finally:
            conn.close()
        items = [MemoryItem.from_row(row) for row in rows]
        return MemoryApplicationGate().filter(
            items,
            user_query=user_query,
            workspace_facts=workspace_facts,
            max_chars=max_chars,
        )
    except Exception:
        return []

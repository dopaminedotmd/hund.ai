"""DomainRegistry — anti-fragmentation and hierarchical domain management.

Hierarchical domain IDs (e.g., 'python', 'python/fastapi', 'web/shopify/liquid').
Canonicalization maps variations to existing registered domains and NEVER
auto-creates from arbitrary raw strings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any

from ..store.sqlite import connect

REGISTRY_TABLE = "domain_registry"


def _ensure_table(db_path: Path | str | None = None) -> None:
    conn = connect(Path(db_path) if db_path else None)
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {REGISTRY_TABLE} (
            domain_id TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            registered_at TEXT NOT NULL,
            parent_id TEXT
        )"""
    )
    conn.commit()
    conn.close()


def _normalize_id(raw: str) -> str:
    """Normalize domain ID format: lowercase, trimmed, clean single slashes."""
    parts = [re.sub(r"[^a-z0-9_.-]", "", p.strip().lower()) for p in raw.split("/")]
    non_empty = [p for p in parts if p]
    return "/".join(non_empty)


def _derive_parent(domain_id: str) -> str | None:
    """Derive parent domain ID if hierarchical."""
    if "/" in domain_id:
        return domain_id.rsplit("/", 1)[0]
    return None


def register(
    domain_id: str,
    description: str = "",
    db_path: Path | str | None = None,
) -> str:
    """Register a new domain explicitly.

    Returns the canonical registered domain ID.
    """
    clean_id = _normalize_id(domain_id)
    if not clean_id:
        raise ValueError("Domain ID cannot be empty.")

    _ensure_table(db_path)
    parent_id = _derive_parent(clean_id)
    now = datetime.now(timezone.utc).isoformat()

    conn = connect(Path(db_path) if db_path else None)
    conn.execute(
        f"""INSERT INTO {REGISTRY_TABLE} (domain_id, description, registered_at, parent_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(domain_id) DO UPDATE SET
                description = CASE WHEN excluded.description != '' THEN excluded.description ELSE description END""",
        (clean_id, description, now, parent_id),
    )
    conn.commit()
    conn.close()
    return clean_id


def get(domain_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Retrieve registered domain details."""
    clean_id = _normalize_id(domain_id)
    if not clean_id:
        return None

    _ensure_table(db_path)
    conn = connect(Path(db_path) if db_path else None)
    row = conn.execute(
        f"SELECT domain_id, description, registered_at, parent_id FROM {REGISTRY_TABLE} WHERE domain_id = ?",
        (clean_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "domain_id": row[0],
        "description": row[1] or "",
        "registered_at": row[2],
        "parent_id": row[3],
    }


def list_all(db_path: Path | str | None = None) -> list[str]:
    """List all registered domain IDs sorted alphabetically."""
    _ensure_table(db_path)
    conn = connect(Path(db_path) if db_path else None)
    rows = conn.execute(f"SELECT domain_id FROM {REGISTRY_TABLE} ORDER BY domain_id ASC").fetchall()
    conn.close()
    return [r[0] for r in rows]


def children(parent_id: str, db_path: Path | str | None = None) -> list[str]:
    """Return all registered child domain IDs for a given parent ID (direct & recursive)."""
    clean_parent = _normalize_id(parent_id)
    if not clean_parent:
        return []

    all_domains = list_all(db_path)
    prefix = clean_parent + "/"
    return [d for d in all_domains if d.startswith(prefix)]


def parent(domain_id: str) -> str | None:
    """Return parent domain ID for a given domain ID."""
    clean_id = _normalize_id(domain_id)
    return _derive_parent(clean_id)


def _simplify_token(s: str) -> str:
    """Strip all punctuation and extra noise for fuzzy candidate matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def canonicalize(name: str, db_path: Path | str | None = None) -> str | None:
    """Suggest nearest registered domain ID for a given name without auto-creating.

    If name matches a registered domain (exact, normalized, or via alias/segment),
    returns the registered domain_id.
    If no registered domain matches, returns None.
    """
    clean = _normalize_id(name)
    if not clean:
        return None

    registered = list_all(db_path)
    if not registered:
        return None

    # 1. Exact match
    if clean in registered:
        return clean

    # 2. Normalized token match (e.g. "fast-api" -> "python/fastapi" or "fastapi")
    simplified_query = _simplify_token(clean)
    if not simplified_query:
        return None

    # Map registered domains to simplified keys
    # Match against full domain simplified or leaf segment simplified
    candidates: list[str] = []
    for reg in registered:
        reg_simplified = _simplify_token(reg)
        leaf_simplified = _simplify_token(reg.rsplit("/", 1)[-1])

        # Exact simplified match on full path or leaf
        if simplified_query == reg_simplified or simplified_query == leaf_simplified:
            candidates.append(reg)
            continue

        # Handle noise suffixes/prefixes like "-api", "-lib", "fastapi-api"
        trimmed_query = re.sub(r"(api|lib|sdk|framework)$", "", simplified_query)
        if trimmed_query and (trimmed_query == reg_simplified or trimmed_query == leaf_simplified):
            candidates.append(reg)

    if candidates:
        # Prefer exact leaf match or shortest matching domain
        candidates.sort(key=lambda c: (len(c.split("/")), len(c)))
        return candidates[0]

    return None


class DomainRegistry:
    """Object interface for domain registry operations."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None

    def register(self, domain_id: str, description: str = "", parent: str | None = None) -> str:
        actual_id = f"{parent}/{domain_id}" if parent and not domain_id.startswith(f"{parent}/") else domain_id
        return register(actual_id, description=description, db_path=self.db_path)

    def get(self, domain_id: str) -> dict[str, Any] | None:
        return get(domain_id, db_path=self.db_path)

    def list_all(self) -> list[str]:
        return list_all(db_path=self.db_path)

    def children(self, parent_id: str) -> list[str]:
        return children(parent_id, db_path=self.db_path)

    def parent(self, domain_id: str) -> str | None:
        return parent(domain_id)

    def canonicalize(self, name: str) -> str | None:
        return canonicalize(name, db_path=self.db_path)


_GLOBAL_REGISTRY: DomainRegistry | None = None


def get_registry(db_path: Path | str | None = None) -> DomainRegistry:
    """Get or create singleton DomainRegistry instance."""
    global _GLOBAL_REGISTRY
    if db_path is not None:
        return DomainRegistry(db_path)
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = DomainRegistry()
    return _GLOBAL_REGISTRY

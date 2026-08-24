"""Unit tests for deterministic scope resolution and domain routing."""
from pathlib import Path

from hund.domains.registry import DomainRegistry
from hund.learning.resolver import (
    SCOPE_TYPE_DOMAIN,
    SCOPE_TYPE_PROJECT,
    SCOPE_TYPE_USER,
    resolve_scope,
)
from hund.learning.trust import (
    SOURCE_FILE,
    SOURCE_TOOL,
    SOURCE_USER,
    SOURCE_WEB,
)


def _make_registry() -> DomainRegistry:
    reg = DomainRegistry()
    reg.register("python", description="Python ecosystem")
    reg.register("python/fastapi", parent="python", description="FastAPI framework")
    reg.register("web/react", description="React UI library")
    reg.register("web/shopify/liquid", description="Shopify Liquid templates")
    reg.register("rust", description="Rust systems programming")
    return reg


def test_user_preference_resolves_to_user_global() -> None:
    reg = _make_registry()

    # English preference
    res1 = resolve_scope(
        observation_text="I prefer short and concise responses",
        workspace_id="ws_123",
        source_type=SOURCE_USER,
        registry=reg,
    )
    assert res1.scope_type == SCOPE_TYPE_USER
    assert res1.scope_id == "user_global"

    # Swedish preference
    res2 = resolve_scope(
        observation_text="jag föredrar att du svarar på svenska",
        workspace_id="ws_123",
        source_type=SOURCE_USER,
        registry=reg,
    )
    assert res2.scope_type == SCOPE_TYPE_USER
    assert res2.scope_id == "user_global"


def test_project_rules_resolve_to_project_scope() -> None:
    reg = _make_registry()

    res = resolve_scope(
        observation_text="all route handlers in this repo live under src/api/routes",
        workspace_id="ws_git_abc123",
        source_type=SOURCE_FILE,
        registry=reg,
    )
    assert res.scope_type == SCOPE_TYPE_PROJECT
    assert res.scope_id == "project:ws_git_abc123"


def test_domain_knowledge_resolves_to_canonical_domain() -> None:
    reg = _make_registry()

    # FastAPI rule
    res = resolve_scope(
        observation_text="use Depends(get_db) for FastAPI dependency injection",
        workspace_id="ws_123",
        source_type=SOURCE_WEB,
        registry=reg,
    )
    assert res.scope_type == SCOPE_TYPE_DOMAIN
    assert res.scope_id == "domain:python/fastapi"
    assert res.domain_id == "python/fastapi"


def test_unregistered_domain_falls_back_safely() -> None:
    reg = _make_registry()

    # Unknown technology not in registry
    res = resolve_scope(
        observation_text="some rule about unknown_framework_xyz",
        workspace_id="ws_123",
        source_type=SOURCE_WEB,
        registry=reg,
    )
    assert res.scope_type == SCOPE_TYPE_DOMAIN
    # Never invents domain:unknown_framework_xyz!
    assert res.scope_id == "domain:general"
    assert res.domain_id == "general"

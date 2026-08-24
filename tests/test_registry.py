"""Unit tests for domain registry and anti-fragmentation canonicalization."""
from pathlib import Path
import pytest

from hund.domains.registry import (
    canonicalize,
    children,
    get,
    list_all,
    parent,
    register,
)


def test_register_and_get(tmp_path: Path) -> None:
    db_file = tmp_path / "test_reg.sqlite"

    reg_id = register("python/fastapi", description="FastAPI web framework", db_path=db_file)
    assert reg_id == "python/fastapi"

    info = get("python/fastapi", db_path=db_file)
    assert info is not None
    assert info["domain_id"] == "python/fastapi"
    assert info["description"] == "FastAPI web framework"
    assert info["parent_id"] == "python"


def test_empty_registration_raises(tmp_path: Path) -> None:
    db_file = tmp_path / "test_reg.sqlite"
    with pytest.raises(ValueError):
        register("", db_path=db_file)


def test_hierarchical_children_and_parents(tmp_path: Path) -> None:
    db_file = tmp_path / "test_reg.sqlite"

    register("web", db_path=db_file)
    register("web/shopify", db_path=db_file)
    register("web/shopify/liquid", db_path=db_file)
    register("web/react", db_path=db_file)
    register("python", db_path=db_file)
    register("python/fastapi", db_path=db_file)

    all_domains = list_all(db_path=db_file)
    assert all_domains == [
        "python",
        "python/fastapi",
        "web",
        "web/react",
        "web/shopify",
        "web/shopify/liquid",
    ]

    web_children = children("web", db_path=db_file)
    assert set(web_children) == {
        "web/shopify",
        "web/shopify/liquid",
        "web/react",
    }

    shopify_children = children("web/shopify", db_path=db_file)
    assert shopify_children == ["web/shopify/liquid"]

    assert parent("web/shopify/liquid") == "web/shopify"
    assert parent("web/shopify") == "web"
    assert parent("web") is None


def test_canonicalize_matching(tmp_path: Path) -> None:
    db_file = tmp_path / "test_reg.sqlite"

    register("python", db_path=db_file)
    register("python/fastapi", db_path=db_file)
    register("web/shopify/liquid", db_path=db_file)

    # Exact match
    assert canonicalize("python", db_path=db_file) == "python"
    assert canonicalize("python/fastapi", db_path=db_file) == "python/fastapi"

    # Normalized variations
    assert canonicalize("fast-api", db_path=db_file) == "python/fastapi"
    assert canonicalize("fast_api", db_path=db_file) == "python/fastapi"
    assert canonicalize("fastapi", db_path=db_file) == "python/fastapi"
    assert canonicalize("fastapi-api", db_path=db_file) == "python/fastapi"
    assert canonicalize("liquid", db_path=db_file) == "web/shopify/liquid"


def test_canonicalize_never_auto_creates(tmp_path: Path) -> None:
    db_file = tmp_path / "test_reg.sqlite"

    register("python", db_path=db_file)

    # Unregistered raw string should return None
    assert canonicalize("completely_unknown_domain", db_path=db_file) is None
    assert canonicalize("rust", db_path=db_file) is None

    # Verify no new domains were added to the database
    domains_after = list_all(db_path=db_file)
    assert domains_after == ["python"]

"""Unit tests for trust boundary and provenance rules."""
import pytest

from hund.learning.trust import (
    ALL_SOURCES,
    SOURCE_CONFIRMED_ACTION,
    SOURCE_ENV,
    SOURCE_FILE,
    SOURCE_INFERENCE,
    SOURCE_TOOL,
    SOURCE_USER,
    SOURCE_WEB,
    source_allowed,
)


def test_trust_matrix_full_verification() -> None:
    # SOURCE_USER -> user: True, project: True, domain: True
    assert source_allowed(SOURCE_USER, "user") is True
    assert source_allowed(SOURCE_USER, "project") is True
    assert source_allowed(SOURCE_USER, "domain") is True

    # SOURCE_CONFIRMED_ACTION -> user: True, project: True, domain: False
    assert source_allowed(SOURCE_CONFIRMED_ACTION, "user") is True
    assert source_allowed(SOURCE_CONFIRMED_ACTION, "project") is True
    assert source_allowed(SOURCE_CONFIRMED_ACTION, "domain") is False

    # SOURCE_INFERENCE -> user: False (draft only), project: True, domain: False
    assert source_allowed(SOURCE_INFERENCE, "user") is False
    assert source_allowed(SOURCE_INFERENCE, "project") is True
    assert source_allowed(SOURCE_INFERENCE, "domain") is False

    # SOURCE_FILE -> user: False, project: True, domain: True
    assert source_allowed(SOURCE_FILE, "user") is False
    assert source_allowed(SOURCE_FILE, "project") is True
    assert source_allowed(SOURCE_FILE, "domain") is True

    # SOURCE_WEB -> user: False, project: False, domain: True
    assert source_allowed(SOURCE_WEB, "user") is False
    assert source_allowed(SOURCE_WEB, "project") is False
    assert source_allowed(SOURCE_WEB, "domain") is True

    # SOURCE_TOOL -> user: False, project: False, domain: True
    assert source_allowed(SOURCE_TOOL, "user") is False
    assert source_allowed(SOURCE_TOOL, "project") is False
    assert source_allowed(SOURCE_TOOL, "domain") is True

    # SOURCE_ENV -> all: False
    assert source_allowed(SOURCE_ENV, "user") is False
    assert source_allowed(SOURCE_ENV, "project") is False
    assert source_allowed(SOURCE_ENV, "domain") is False


def test_prompt_injection_defense_invariants() -> None:
    """Critical invariant: External/untrusted sources can NEVER write to user memory."""
    untrusted_for_user = [
        SOURCE_FILE,
        SOURCE_WEB,
        SOURCE_TOOL,
        SOURCE_ENV,
        SOURCE_INFERENCE,
    ]
    for src in untrusted_for_user:
        assert source_allowed(src, "user") is False, f"Source '{src}' must NOT write to user memory"
        assert source_allowed(src, "user_memory") is False
        assert source_allowed(src, "user_global") is False


def test_case_insensitivity_and_aliases() -> None:
    assert source_allowed("USER", "USER") is True
    assert source_allowed("  user  ", "  user_memory  ") is True
    assert source_allowed("FILE", "PROJECT_MEMORY") is True
    assert source_allowed("web", "domain_knowledge") is True
    assert source_allowed("tool", "domain_memory") is True


def test_unknown_inputs() -> None:
    assert source_allowed("unknown_source", "user") is False
    assert source_allowed(SOURCE_USER, "unknown_destination") is False
    assert source_allowed("", "") is False

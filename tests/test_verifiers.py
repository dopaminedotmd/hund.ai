"""Tests for deterministic candidate verifiers (AST and Dependency checks)."""
import pytest

from hund.learning.evaluator import CandidateProposal
from hund.learning.verifiers import (
    extract_code_blocks,
    verify_candidate_unit,
    verify_syntax_ast,
)


def test_syntax_ast_verification() -> None:
    valid_code = "def greet(name: str) -> str:\n    return f'Hello {name}'"
    ok, msg = verify_syntax_ast(valid_code, "python")
    assert ok is True

    invalid_code = "def broken(:\n    return 1"
    ok, msg = verify_syntax_ast(invalid_code, "python")
    assert ok is False
    assert "syntax error" in msg.lower()


def test_extract_code_blocks() -> None:
    text = "Use this helper:\n```python\ndef run():\n    pass\n```\nAnd done."
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert "def run():" in blocks[0]


def test_verify_candidate_unit_valid() -> None:
    proposal = CandidateProposal(
        proposition="Always use `model_validate` in Pydantic V2:\n```python\nfrom pydantic import BaseModel\nm = BaseModel.model_validate({})\n```",
        scope={"type": "domain", "id": "python/pydantic"},
        kind="rule",
        relation_to_existing="NEW",
        deps={"pydantic": ">=2.0.0"},
        confidence=0.8,
        suggested_action="store_candidate",
    )
    workspace_deps = {"pydantic": "2.6.1"}
    ok, msg = verify_candidate_unit(proposal, workspace_deps=workspace_deps)
    assert ok is True


def test_verify_candidate_unit_syntax_failure() -> None:
    proposal = CandidateProposal(
        proposition="Broken syntax rule:\n```python\ndef invalid_func(x\n    return x\n```",
        scope={"type": "domain", "id": "python"},
        kind="rule",
        relation_to_existing="NEW",
        confidence=0.8,
        suggested_action="store_candidate",
    )
    ok, msg = verify_candidate_unit(proposal)
    assert ok is False
    assert "rejected by ast verifier" in msg.lower()


def test_verify_candidate_unit_dep_mismatch() -> None:
    proposal = CandidateProposal(
        proposition="Use legacy BaseModel.parse_obj()",
        scope={"type": "domain", "id": "python/pydantic"},
        kind="rule",
        relation_to_existing="NEW",
        deps={"pydantic": "<2.0.0"},
        confidence=0.8,
        suggested_action="store_candidate",
    )
    workspace_deps = {"pydantic": "2.7.0"}
    ok, msg = verify_candidate_unit(proposal, workspace_deps=workspace_deps)
    assert ok is False
    assert "rejected by dependency verifier" in msg.lower()

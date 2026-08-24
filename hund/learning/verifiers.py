"""Deterministic verifiers for candidate propositions before commit.

Validates AST syntax, dependency compatibility, and structural bounds
with zero LLM overhead.
"""
from __future__ import annotations

import ast
import re
from typing import Optional

from .deps import check_dep_compatibility
from .evaluator import CandidateProposal, VALID_ACTIONS, VALID_KINDS, VALID_RELATIONS


def verify_syntax_ast(code_snippet: str, language: str = "python") -> tuple[bool, str]:
    """Verify code snippet syntax using deterministic AST parser."""
    if not code_snippet or not code_snippet.strip():
        return True, "empty code snippet"

    clean_code = code_snippet.strip()
    # Strip markdown code blocks if wrapped
    if clean_code.startswith("```"):
        lines = clean_code.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean_code = "\n".join(lines).strip()

    if language.lower() in ("python", "py"):
        try:
            ast.parse(clean_code)
            return True, "valid python ast"
        except SyntaxError as e:
            return False, f"python syntax error: {e.msg} at line {e.lineno}"

    return True, f"language {language} syntax check skipped"


def extract_code_blocks(text: str) -> list[str]:
    """Extract code snippets from markdown code blocks or inline backticks."""
    blocks: list[str] = []
    # 1. Fenced code blocks ```python ... ``` or ``` ... ```
    fenced = re.findall(r"```(?:python|py)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    blocks.extend(fenced)

    # 2. If no fenced blocks, check if entire text looks like Python definition/call
    if not blocks:
        s = text.strip()
        if re.search(r"\b(def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+\s+import)\b", s):
            blocks.append(s)

    return blocks


def verify_candidate_unit(
    proposal: CandidateProposal,
    workspace_deps: Optional[dict[str, str]] = None,
) -> tuple[bool, str]:
    """Deterministically verify a candidate proposal before commit.

    Checks:
    1. Proposition bounds & non-empty statement.
    2. Valid enum fields (kind, relation, action).
    3. AST syntax check on any embedded Python code blocks.
    4. Dependency constraints vs current workspace dependencies (drift prevention).
    """
    if not proposal.proposition or len(proposal.proposition.strip()) < 5:
        return False, "proposition is empty or too short (< 5 chars)"

    if proposal.kind not in VALID_KINDS:
        return False, f"invalid knowledge kind: {proposal.kind}"

    if proposal.relation_to_existing not in VALID_RELATIONS:
        return False, f"invalid relation to existing knowledge: {proposal.relation_to_existing}"

    if proposal.suggested_action not in VALID_ACTIONS:
        return False, f"invalid suggested action: {proposal.suggested_action}"

    # 1. AST syntax check
    code_blocks = extract_code_blocks(proposal.proposition)
    for block in code_blocks:
        is_valid, msg = verify_syntax_ast(block, language="python")
        if not is_valid:
            return False, f"rejected by AST verifier: {msg}"

    # 2. Dependency drift check
    if proposal.deps and workspace_deps:
        is_compat, reason = check_dep_compatibility(proposal.deps, workspace_deps)
        if not is_compat:
            return False, f"rejected by dependency verifier: {reason}"

    return True, "candidate passed all deterministic verifications"

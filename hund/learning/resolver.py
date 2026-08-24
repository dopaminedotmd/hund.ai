"""Deterministic scope resolution and domain routing for evidence and candidate knowledge."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional

from ..domains.registry import DomainRegistry, get_registry
from .trust import (
    SOURCE_CONFIRMED_ACTION,
    SOURCE_ENV,
    SOURCE_FILE,
    SOURCE_INFERENCE,
    SOURCE_TOOL,
    SOURCE_USER,
    SOURCE_WEB,
)

SCOPE_TYPE_USER = "user_global"
SCOPE_TYPE_PROJECT = "project"
SCOPE_TYPE_DOMAIN = "domain"

# Regex patterns for user preference statements
USER_PREF_PATTERNS = [
    r"\b(i\s+prefer|i\s+like|i\s+want|always\s+respond|always\s+speak|talk\s+in|my\s+name|my\s+timezone|call\s+me)\b",
    r"\b(jag\s+föredrar|jag\s+vill|svara\s+alltid|prata\s+svenska|skriv\s+på\s+svenska|mitt\s+namn|kalla\s+mig)\b",
    r"\b(be\s+concise|korta\s+svar|svenska|kortfattad|dark\s+mode|mörkt\s+tema)\b",
]

# Patterns for workspace / project specifics
PROJECT_SPECIFIC_PATTERNS = [
    r"\b(in\s+this\s+repo|in\s+this\s+project|our\s+codebase|this\s+codebase|workspace\s+root)\b",
    r"\b(i\s+denna\s+repo|i\s+detta\s+projekt|vår\s+kodbas|projektstruktur)\b",
    r"\b(src/|hund/|apps/|packages/|tests/|docs/|pyproject\.toml|package\.json|cargo\.toml|\.env)\b",
    r"\b(architecture|monorepo|build\s+step|makefile|taskfile)\b",
]


@dataclass
class ResolvedScope:
    scope_type: str
    scope_id: str
    domain_id: Optional[str] = None
    confidence: float = 1.0
    reason: str = ""


def resolve_scope(
    observation_text: str,
    workspace_id: str | None = None,
    active_domains: list[str] | None = None,
    source_type: str = SOURCE_USER,
    file_paths: list[str] | None = None,
    registry: DomainRegistry | None = None,
) -> ResolvedScope:
    """Deterministically route an observation or rule to its canonical scope.

    Priority:
    1. User global preference (from SOURCE_USER matching user preference cues).
    2. Project-specific rule (referencing local repo files, paths, or workspace invariants).
    3. Domain knowledge (referencing generic framework, library, tool, or language concepts).
    """
    text_lower = observation_text.strip().lower()
    reg = registry or get_registry()
    ws_id = workspace_id or "default"

    # 1. User Global Preference
    if source_type in (SOURCE_USER, SOURCE_CONFIRMED_ACTION):
        for pat in USER_PREF_PATTERNS:
            if re.search(pat, text_lower):
                return ResolvedScope(
                    scope_type=SCOPE_TYPE_USER,
                    scope_id=SCOPE_TYPE_USER,
                    confidence=1.0,
                    reason=f"matches user preference pattern '{pat}'",
                )

    # 2. Project-Specific Rules
    # Untrusted sources (files, tools) or explicit project markers route to project
    is_project_source = source_type in (SOURCE_FILE, SOURCE_ENV)
    matches_project_pat = any(re.search(pat, text_lower) for pat in PROJECT_SPECIFIC_PATTERNS)
    has_local_file_path = bool(file_paths and any(not p.startswith("http") for p in file_paths))

    if matches_project_pat or (is_project_source and not any(d in text_lower for d in ("fastapi", "react", "django", "pydantic"))):
        return ResolvedScope(
            scope_type=SCOPE_TYPE_PROJECT,
            scope_id=f"project:{ws_id}",
            confidence=0.9,
            reason="matches project-specific file or codebase references",
        )

    # 3. Domain Knowledge Routing
    # Check individual words/tokens in text_lower against registered domains
    words = re.findall(r"[a-z0-9_\-\./]+", text_lower)
    for w in words:
        if len(w) >= 2:
            matched = reg.canonicalize(w)
            if matched and matched != "general":
                return ResolvedScope(
                    scope_type=SCOPE_TYPE_DOMAIN,
                    scope_id=f"domain:{matched}",
                    domain_id=matched,
                    confidence=0.85,
                    reason=f"mapped token '{w}' to canonical domain '{matched}'",
                )

    # Check all registered domains (longest first) against text
    for d in sorted(reg.list_all(), key=len, reverse=True):
        leaf = d.rsplit("/", 1)[-1]
        if leaf in words or d in text_lower:
            return ResolvedScope(
                scope_type=SCOPE_TYPE_DOMAIN,
                scope_id=f"domain:{d}",
                domain_id=d,
                confidence=0.85,
                reason=f"matched registered domain '{d}'",
            )

    # Check active_domains list if provided
    if active_domains:
        for dom in active_domains:
            matched = reg.canonicalize(dom)
            if matched:
                return ResolvedScope(
                    scope_type=SCOPE_TYPE_DOMAIN,
                    scope_id=f"domain:{matched}",
                    domain_id=matched,
                    confidence=0.75,
                    reason=f"derived from active domain context '{matched}'",
                )

    # 4. Fallback Routing based on provenance
    if source_type in (SOURCE_FILE, SOURCE_TOOL):
        return ResolvedScope(
            scope_type=SCOPE_TYPE_PROJECT,
            scope_id=f"project:{ws_id}",
            confidence=0.6,
            reason="fallback project scope for tool/file provenance",
        )

    if source_type in (SOURCE_USER, SOURCE_CONFIRMED_ACTION):
        return ResolvedScope(
            scope_type=SCOPE_TYPE_USER,
            scope_id=SCOPE_TYPE_USER,
            confidence=0.6,
            reason="fallback user scope for direct user utterance",
        )

    # General domain fallback
    return ResolvedScope(
        scope_type=SCOPE_TYPE_DOMAIN,
        scope_id="domain:general",
        domain_id="general",
        confidence=0.5,
        reason="default domain fallback",
    )

"""Candidate Evaluator — proposes structured candidate knowledge from evidence events.

Adheres strictly to §5 and §10 of PLAN_2026-08-24_learning_engine.md:
- LLM PROPOSES ONLY: NO writes to persistent databases, NO XP awarded.
- Categorical relation to existing knowledge (NEW, DUPLICATE, REFINEMENT, CONTRADICTION, SCOPE_VARIANT, OBSOLETES).
- Trust boundary enforcement: untrusted sources are never allowed to propose user memory.
- Precision > Recall: high threshold for store_candidate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Optional, Sequence

from .prefilter import prefilter_evidence
from .redactor_v2 import redact_text_v2
from .resolver import resolve_scope
from .trust import SOURCE_USER, source_allowed

KIND_RULE = "rule"
KIND_NEGATIVE_RULE = "negative_rule"
KIND_CONSTRAINT = "constraint"
KIND_EXCEPTION = "exception"
VALID_KINDS = {KIND_RULE, KIND_NEGATIVE_RULE, KIND_CONSTRAINT, KIND_EXCEPTION}

RELATION_NEW = "NEW"
RELATION_DUPLICATE = "DUPLICATE"
RELATION_REFINEMENT = "REFINEMENT"
RELATION_CONTRADICTION = "CONTRADICTION"
RELATION_SCOPE_VARIANT = "SCOPE_VARIANT"
RELATION_OBSOLETES = "OBSOLETES"
VALID_RELATIONS = {
    RELATION_NEW,
    RELATION_DUPLICATE,
    RELATION_REFINEMENT,
    RELATION_CONTRADICTION,
    RELATION_SCOPE_VARIANT,
    RELATION_OBSOLETES,
}

ACTION_STORE_CANDIDATE = "store_candidate"
ACTION_DISCARD = "discard"
ACTION_FLAG_CONFLICT = "flag_conflict"
VALID_ACTIONS = {ACTION_STORE_CANDIDATE, ACTION_DISCARD, ACTION_FLAG_CONFLICT}


@dataclass
class CandidateProposal:
    proposition: str
    scope: dict[str, str]  # {"type": "domain"|"project"|"user_global", "id": "..."}
    kind: str = KIND_RULE
    relation_to_existing: str = RELATION_NEW
    related_memory_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    reusability: float = 0.8
    task_impact: float = 0.7
    confidence: float = 0.8
    suggested_action: str = ACTION_STORE_CANDIDATE
    deps: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateProposal:
        kind = data.get("kind", KIND_RULE)
        if kind not in VALID_KINDS:
            kind = KIND_RULE

        rel = data.get("relation_to_existing", RELATION_NEW).upper()
        if rel not in VALID_RELATIONS:
            rel = RELATION_NEW

        action = data.get("suggested_action", ACTION_STORE_CANDIDATE)
        if action not in VALID_ACTIONS:
            action = ACTION_STORE_CANDIDATE

        raw_scope = data.get("scope", {})
        if isinstance(raw_scope, str):
            scope = {"type": "domain", "id": raw_scope}
        elif isinstance(raw_scope, dict):
            scope = {
                "type": str(raw_scope.get("type", "domain")),
                "id": str(raw_scope.get("id", "general")),
            }
        else:
            scope = {"type": "domain", "id": "general"}

        return cls(
            proposition=str(data.get("proposition", "")).strip(),
            scope=scope,
            kind=kind,
            relation_to_existing=rel,
            related_memory_ids=[str(x) for x in data.get("related_memory_ids", [])],
            evidence_ids=[str(x) for x in data.get("evidence_ids", [])],
            reusability=float(data.get("reusability", 0.8)),
            task_impact=float(data.get("task_impact", 0.7)),
            confidence=float(data.get("confidence", 0.8)),
            suggested_action=action,
            deps={str(k): str(v) for k, v in data.get("deps", {}).items()},
        )


EVALUATOR_SYSTEM_PROMPT = """You are Hund's Epistemic Candidate Evaluator.
Analyze evidence from recent agent actions and user interactions.
Propose structured candidate knowledge units adhering strictly to the contract below.

RULES:
1. Propose generalizable, high-value patterns or rules (positive or negative).
2. Categorical relations to existing knowledge: NEW, DUPLICATE, REFINEMENT, CONTRADICTION, SCOPE_VARIANT, OBSOLETES.
3. Reject temporary workarounds, single-task noise, or user-specific secrets.
4. If an observation contradicts existing knowledge, mark relation as CONTRADICTION and suggested_action as flag_conflict.
5. NEVER include API keys, passwords, or raw secrets in propositions.

OUTPUT JSON FORMAT:
{
  "candidates": [
    {
      "proposition": "<concise reusable rule>",
      "scope": {"type": "domain" | "project" | "user_global", "id": "<domain_id or project_id>"},
      "kind": "rule" | "negative_rule" | "constraint" | "exception",
      "relation_to_existing": "NEW" | "DUPLICATE" | "REFINEMENT" | "CONTRADICTION" | "SCOPE_VARIANT" | "OBSOLETES",
      "related_memory_ids": [],
      "evidence_ids": [],
      "reusability": 0.85,
      "task_impact": 0.75,
      "confidence": 0.80,
      "suggested_action": "store_candidate" | "discard" | "flag_conflict",
      "deps": {}
    }
  ]
}
"""


def parse_candidate_proposals(
    raw_text: str,
    default_evidence_ids: Sequence[str] | None = None,
    source_type: str = SOURCE_USER,
    workspace_id: str | None = None,
) -> list[CandidateProposal]:
    """Parse, sanitize, and validate candidate proposals from LLM output."""
    proposals: list[CandidateProposal] = []
    ev_ids = list(default_evidence_ids or [])

    # Extract JSON object from output
    m = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if not m:
        return []

    json_str = m.group(1)
    try:
        data = json.loads(json_str)
    except Exception:
        return []

    raw_candidates = data.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return []

    for item in raw_candidates:
        if not isinstance(item, dict):
            continue

        proposal = CandidateProposal.from_dict(item)

        # 1. Sanitize proposition for secrets using redactor
        redacted = redact_text_v2(proposal.proposition)
        proposal.proposition = redacted.text.strip()

        if not proposal.proposition:
            continue

        # 2. Attach evidence IDs if missing
        if not proposal.evidence_ids and ev_ids:
            proposal.evidence_ids = ev_ids

        # 3. Trust boundary gate enforcement on scope
        target_scope_type = proposal.scope.get("type", "domain")
        if target_scope_type == "user_global" and not source_allowed(source_type, "user"):
            # Untrusted source attempted to write to user_global -> force project scope
            proposal.scope = {
                "type": "project",
                "id": f"project:{workspace_id or 'default'}",
            }

        # 4. Precision threshold filter
        # Discard proposals with low confidence or trivial reusability
        if proposal.reusability < 0.3 or proposal.confidence < 0.4:
            proposal.suggested_action = ACTION_DISCARD

        proposals.append(proposal)

    return proposals


def evaluate_heuristic_candidates(
    events: Sequence[Any],
    existing_rules: Sequence[str] | None = None,
    workspace_id: str | None = None,
    active_domains: list[str] | None = None,
) -> list[CandidateProposal]:
    """Deterministic fallback evaluator for local execution without LLM."""
    filtered_events, _ = prefilter_evidence(events, existing_rules)
    proposals: list[CandidateProposal] = []

    for evt in filtered_events:
        if isinstance(evt, dict):
            payload = evt.get("payload", "")
            ev_id = evt.get("event_id", "evt_local")
            src_type = evt.get("source_type", SOURCE_USER)
        else:
            payload = getattr(evt, "payload", str(evt))
            ev_id = getattr(evt, "event_id", "evt_local")
            src_type = getattr(evt, "source_type", SOURCE_USER)

        # Redact secrets
        clean_text = redact_text_v2(payload).text.strip()
        if not clean_text:
            continue

        resolved = resolve_scope(
            observation_text=clean_text,
            workspace_id=workspace_id,
            active_domains=active_domains,
            source_type=src_type,
        )

        proposal = CandidateProposal(
            proposition=clean_text,
            scope={"type": resolved.scope_type, "id": resolved.scope_id},
            kind=KIND_RULE,
            relation_to_existing=RELATION_NEW,
            evidence_ids=[ev_id],
            reusability=0.75,
            task_impact=0.70,
            confidence=resolved.confidence,
            suggested_action=ACTION_STORE_CANDIDATE if resolved.confidence >= 0.7 else ACTION_DISCARD,
        )
        proposals.append(proposal)

    return proposals

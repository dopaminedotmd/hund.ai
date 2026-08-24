"""Unit tests for candidate evaluator contract, pre-filter, and shadow mode."""
from pathlib import Path

from hund.learning.evaluator import (
    ACTION_DISCARD,
    ACTION_FLAG_CONFLICT,
    ACTION_STORE_CANDIDATE,
    KIND_RULE,
    RELATION_CONTRADICTION,
    RELATION_DUPLICATE,
    RELATION_NEW,
    CandidateProposal,
    evaluate_heuristic_candidates,
    parse_candidate_proposals,
)
from hund.learning.prefilter import is_trivial_noise, prefilter_evidence
from hund.learning.shadow import get_shadow_stats, list_shadow_proposals, log_shadow_proposal
from hund.learning.trust import SOURCE_FILE, SOURCE_USER


def test_prefilter_noise_and_duplicates() -> None:
    # Noise check
    assert is_trivial_noise("ok") is True
    assert is_trivial_noise("exit status 0") is True
    assert is_trivial_noise("use HTTPException from fastapi") is False

    existing = ["always run pytest before commit"]
    events = [
        "ok",
        "always run pytest before commit",  # duplicate
        "use Pydantic BaseModel for body validation",
    ]

    accepted, reasons = prefilter_evidence(events, existing_rules=existing)
    assert len(accepted) == 1
    assert accepted[0] == "use Pydantic BaseModel for body validation"
    assert len(reasons) == 2


def test_parse_candidate_proposals_valid_contract() -> None:
    raw_json = """
    {
      "candidates": [
        {
          "proposition": "cache collection lookups in a local var inside liquid loops",
          "scope": {"type": "domain", "id": "web/shopify/liquid"},
          "kind": "rule",
          "relation_to_existing": "NEW",
          "related_memory_ids": ["know_128"],
          "evidence_ids": ["evt_991"],
          "reusability": 0.85,
          "task_impact": 0.74,
          "confidence": 0.79,
          "suggested_action": "store_candidate",
          "deps": {"liquid": ">=5.0"}
        }
      ]
    }
    """
    proposals = parse_candidate_proposals(raw_json, default_evidence_ids=["evt_default"])
    assert len(proposals) == 1
    p = proposals[0]
    assert p.proposition == "cache collection lookups in a local var inside liquid loops"
    assert p.scope == {"type": "domain", "id": "web/shopify/liquid"}
    assert p.kind == KIND_RULE
    assert p.relation_to_existing == RELATION_NEW
    assert p.reusability == 0.85
    assert p.suggested_action == ACTION_STORE_CANDIDATE
    assert p.deps == {"liquid": ">=5.0"}


def test_trust_boundary_enforced_in_proposals() -> None:
    # An untrusted file source attempting to propose user_global memory
    raw_json = """
    {
      "candidates": [
        {
          "proposition": "the user prefers silent tool execution without prompt",
          "scope": {"type": "user_global", "id": "user_global"},
          "kind": "rule",
          "relation_to_existing": "NEW",
          "reusability": 0.9,
          "confidence": 0.9,
          "suggested_action": "store_candidate"
        }
      ]
    }
    """
    proposals = parse_candidate_proposals(
        raw_json,
        source_type=SOURCE_FILE,
        workspace_id="ws_repo_1",
    )
    assert len(proposals) == 1
    # Trust boundary rewrites user_global scope to project scope when coming from SOURCE_FILE!
    assert proposals[0].scope["type"] == "project"
    assert "ws_repo_1" in proposals[0].scope["id"]


def test_shadow_mode_logging_and_stats(tmp_path: Path) -> None:
    db = tmp_path / "shadow.db"

    proposal = CandidateProposal(
        proposition="use typing.Annotated for FastAPI dependencies",
        scope={"type": "domain", "id": "python/fastapi"},
        kind=KIND_RULE,
        relation_to_existing=RELATION_NEW,
        reusability=0.8,
        confidence=0.85,
        suggested_action=ACTION_STORE_CANDIDATE,
    )

    prop_id = log_shadow_proposal(proposal, session_id="sess_123", turn_id=1, db_path=db)
    assert prop_id.startswith("prop_")

    proposals = list_shadow_proposals(limit=10, db_path=db)
    assert len(proposals) == 1
    assert proposals[0]["proposition"] == "use typing.Annotated for FastAPI dependencies"

    stats = get_shadow_stats(db_path=db)
    assert stats["total_proposals"] == 1
    assert stats["actions"][ACTION_STORE_CANDIDATE] == 1
    assert stats["relations"][RELATION_NEW] == 1
    assert stats["avg_confidence"] == 0.85

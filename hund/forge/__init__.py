"""Forge integration for proposal evaluation and apply-policy."""

from .client import submit_to_forge
from .policy import (
    ApplyPolicy,
    ArtifactDecision,
    ForgeEvaluation,
    ForgeProposal,
    classify_artifact,
    evaluate_proposal_locally,
)
from .registry import ForgeRegistry
from .workflow import customer_training_approved, forge_proposal_from_selfimprovement

__all__ = [
    "ApplyPolicy",
    "ArtifactDecision",
    "ForgeEvaluation",
    "ForgeProposal",
    "ForgeRegistry",
    "classify_artifact",
    "evaluate_proposal_locally",
    "submit_to_forge",
    "customer_training_approved",
    "forge_proposal_from_selfimprovement",
]

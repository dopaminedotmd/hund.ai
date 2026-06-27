"""High-level proposal workflow for customer-approved training."""
from __future__ import annotations

import json
from typing import Any

from ..selfimprovement.proposal import Proposal, set_status
from .client import submit_to_forge
from .policy import ForgeProposal


def forge_proposal_from_selfimprovement(proposal: Proposal) -> ForgeProposal:
    evidence = tuple(str(g) for g in proposal.related_gaps)
    return ForgeProposal(
        id=proposal.id,
        title=proposal.title,
        problem=proposal.problem,
        proposed_change=proposal.proposed_change,
        change_type=proposal.change_type,
        risk=proposal.risk.lower(),
        evidence=evidence,
    )


def customer_training_approved(
    proposal: Proposal,
    *,
    tenant_id: str,
    endpoint: str,
    service_token: str,
    persona: str = "",
    context: dict[str, Any] | None = None,
    simulation_source: bool = False,
) -> dict[str, Any]:
    """One-button training mandate.

    This is not mutation approval. It only queues a redacted Forge evaluation;
    promotion is controlled by the apply-policy matrix.
    """
    set_status(proposal.id, "approved")
    raw_context = dict(context or {})
    if proposal.raw_summary:
        try:
            raw_context["proposal_raw_summary"] = json.loads(proposal.raw_summary)
        except json.JSONDecodeError:
            raw_context["proposal_raw_summary"] = proposal.raw_summary
    return submit_to_forge(
        endpoint=endpoint,
        service_token=service_token,
        tenant_id=tenant_id,
        proposal=forge_proposal_from_selfimprovement(proposal),
        persona=persona,
        context=raw_context,
        simulation_source=simulation_source,
    )

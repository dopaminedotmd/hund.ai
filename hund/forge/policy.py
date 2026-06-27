"""Apply-policy and deterministic Forge evaluation contract.

Forge verifies proposals. This module decides what may be staged or promoted.
TCB/core/safety artifacts fail closed and never reach staged state.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

TCB_PATHS = (
    "hund/agent/safety.py",
    "hund/learning/redactor.py",
    "hund/agent/tool_dispatch.py",
    "hund/agent/loop.py",
    "hund/updater/",
)

LOW_RISK = {"low"}
TENANT_LOCAL_TYPES = {"tenant-local-knowledge", "tenant-local-skill"}

STATE_TRANSITIONS: dict[str, set[str]] = {
    "observed_gap": {"proposal_created"},
    "proposal_created": {"customer_training_approved"},
    "customer_training_approved": {"forge_queued"},
    "forge_queued": {"forge_running"},
    "forge_running": {"forge_rejected", "forge_verified"},
    "forge_rejected": {"study_target_created"},
    "forge_verified": {"staged", "blocked_tcb"},
    "staged": {"promoted", "needs_review"},
    "needs_review": {"canary_running"},
    "promoted": {"canary_running", "active", "rolled_back"},
    "canary_running": {"active", "rolled_back"},
    "active": {"rolled_back"},
    "blocked_tcb": set(),
    "rolled_back": set(),
    "study_target_created": {"proposal_created"},
}


@dataclass(frozen=True)
class ForgeProposal:
    id: str
    title: str
    problem: str
    proposed_change: str
    change_type: str
    risk: str = "medium"
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ForgeProposal":
        evidence = data.get("evidence") or data.get("related_gaps") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            problem=str(data.get("problem") or ""),
            proposed_change=str(data.get("proposed_change") or ""),
            change_type=str(data.get("change_type") or ""),
            risk=str(data.get("risk") or "medium").lower(),
            evidence=tuple(str(e) for e in evidence),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "problem": self.problem,
            "proposed_change": self.proposed_change,
            "change_type": self.change_type,
            "risk": self.risk,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ApplyPolicy:
    auto_stage: bool
    auto_promote: bool
    required_gate: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_stage": self.auto_stage,
            "auto_promote": self.auto_promote,
            "required_gate": self.required_gate,
        }


@dataclass(frozen=True)
class ArtifactDecision:
    artifact_type: str
    scope: str
    state: str
    policy: ApplyPolicy
    blocked_reason: str = ""


@dataclass(frozen=True)
class ForgeEvaluation:
    verdict: str
    composite_score: int
    dimension_scores: dict[str, int]
    artifact_type: str
    apply_policy: ApplyPolicy
    teacher_notes: str = ""
    study_targets: tuple[str, ...] = ()
    iterations: int = 1
    idempotency_key: str = ""
    state: str = "forge_verified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "composite_score": self.composite_score,
            "dimension_scores": self.dimension_scores,
            "artifact_type": self.artifact_type,
            "apply_policy": self.apply_policy.to_dict(),
            "teacher_notes": self.teacher_notes,
            "study_targets": list(self.study_targets),
            "iterations": self.iterations,
            "idempotency_key": self.idempotency_key,
            "state": self.state,
        }


def idempotency_key(proposal_id: str, tenant_id: str) -> str:
    raw = f"{proposal_id}:{tenant_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_tcb_target(proposal: ForgeProposal, extra_text: str = "") -> bool:
    haystack = " ".join(
        [
            proposal.title,
            proposal.problem,
            proposal.proposed_change,
            proposal.change_type,
            extra_text,
        ]
    ).replace("\\", "/").lower()
    if proposal.change_type.lower() in {"core", "engine", "safety", "updater", "redactor"}:
        return True
    return any(path.lower() in haystack for path in TCB_PATHS)


def artifact_type_for(proposal: ForgeProposal) -> str:
    ct = proposal.change_type.lower()
    if ct == "skill":
        return "tenant-local-skill"
    if ct in {"knowledge", "hundk"}:
        return "tenant-local-knowledge"
    if ct == "prompt":
        return "prompt-persona"
    if ct in {"runtime_policy", "policy", "permission"}:
        return "policy-tool-permission"
    if ct in {"test", "shared_knowledge", "global_knowledge"}:
        return "shared-global-knowledge"
    return "shared-global-knowledge"


def classify_artifact(proposal: ForgeProposal, *, extra_text: str = "") -> ArtifactDecision:
    if is_tcb_target(proposal, extra_text=extra_text):
        return ArtifactDecision(
            artifact_type="core-safety-tcb",
            scope="global",
            state="blocked_tcb",
            policy=ApplyPolicy(False, False, "signed_release_outside_loop"),
            blocked_reason="tcb_target",
        )

    artifact_type = artifact_type_for(proposal)
    risk = proposal.risk.lower()
    if artifact_type in TENANT_LOCAL_TYPES:
        can_auto = risk in LOW_RISK
        return ArtifactDecision(
            artifact_type=artifact_type,
            scope="tenant",
            state="promoted" if can_auto else "needs_review",
            policy=ApplyPolicy(True, can_auto, "training_mandate" if can_auto else "admin_review"),
        )
    if artifact_type == "prompt-persona":
        return ArtifactDecision(
            artifact_type=artifact_type,
            scope="global",
            state="needs_review",
            policy=ApplyPolicy(True, False, "explicit_review"),
        )
    if artifact_type == "policy-tool-permission":
        return ArtifactDecision(
            artifact_type=artifact_type,
            scope="global",
            state="needs_review",
            policy=ApplyPolicy(True, False, "explicit_approval_gate"),
        )
    return ArtifactDecision(
        artifact_type=artifact_type,
        scope="shared",
        state="needs_review",
        policy=ApplyPolicy(True, False, "admin_release_policy"),
    )


def valid_transition(current: str, target: str) -> bool:
    return target in STATE_TRANSITIONS.get(current, set())


def evaluate_proposal_locally(
    proposal: ForgeProposal,
    *,
    tenant_id: str,
    idempotency: str | None = None,
    extra_text: str = "",
) -> ForgeEvaluation:
    """Small deterministic evaluator used by tests and the local HTTP stub."""
    idem = idempotency or idempotency_key(proposal.id, tenant_id)
    decision = classify_artifact(proposal, extra_text=extra_text)
    if decision.state == "blocked_tcb":
        return ForgeEvaluation(
            verdict="rejected",
            composite_score=0,
            dimension_scores={
                "accuracy": 0,
                "completeness": 0,
                "persona_preservation": 0,
                "safety": 0,
                "feasibility": 0,
            },
            artifact_type=decision.artifact_type,
            apply_policy=decision.policy,
            teacher_notes="TCB/core/safety target blocked before staging.",
            study_targets=("signed_release_required",),
            idempotency_key=idem,
            state="blocked_tcb",
        )

    completeness = 70
    if proposal.title:
        completeness += 5
    if proposal.problem:
        completeness += 10
    if proposal.proposed_change:
        completeness += 10
    if proposal.evidence:
        completeness += 5
    completeness = min(100, completeness)
    safety = 98 if proposal.risk in LOW_RISK else 82
    feasibility = 92 if proposal.change_type else 50
    score = round((94 + completeness + 96 + safety + feasibility) / 5)
    verdict = "approved" if score >= 80 else "rejected"
    state = "forge_verified" if verdict == "approved" else "forge_rejected"
    return ForgeEvaluation(
        verdict=verdict,
        composite_score=score,
        dimension_scores={
            "accuracy": 94,
            "completeness": completeness,
            "persona_preservation": 96,
            "safety": safety,
            "feasibility": feasibility,
        },
        artifact_type=decision.artifact_type,
        apply_policy=decision.policy,
        teacher_notes="Deterministic local Forge contract evaluation.",
        study_targets=() if verdict == "approved" else ("improve_proposal_evidence",),
        iterations=1,
        idempotency_key=idem,
        state=state,
    )

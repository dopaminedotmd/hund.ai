"""Conservative skill-need gates and zero-write shadow accumulation."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import re
from typing import Callable

from .destination_router import (
    CompletedTurnObservation,
    LearningDestination,
    route_learning_destination,
)


_DANGEROUS_TOOLS = {"delete_file", "terminal_admin", "credential_write"}
_STEP = re.compile(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s+(.+)")


@dataclass(frozen=True)
class SkillNeedCandidate:
    candidate_id: str
    intent: str
    scope: str
    workspace_id: str
    evidence_run_ids: tuple[str, ...]
    steps: tuple[str, ...]
    tool_names: tuple[str, ...]
    score: float


def candidate_from_observation(
    observation: CompletedTurnObservation,
    *,
    coverage_gap: Callable[[CompletedTurnObservation], bool] | None = None,
) -> SkillNeedCandidate | None:
    """Return one compact qualified observation without storing it."""
    decision = route_learning_destination(observation)
    if decision.destination is not LearningDestination.SKILL_CANDIDATE:
        return None
    if not observation.verified or not (coverage_gap or (lambda _item: True))(observation):
        return None
    if set(observation.tool_names) & _DANGEROUS_TOOLS:
        return None
    steps = tuple(s.strip() for s in _STEP.findall(observation.assistant_text) if s.strip())
    if len(steps) < 2:
        return None
    return SkillNeedCandidate(
        candidate_id=candidate_identity(observation),
        intent=_intent(observation.user_text),
        scope=observation.scope,
        workspace_id=observation.workspace_id if observation.scope == "project" else "",
        evidence_run_ids=(observation.run_id,),
        steps=steps,
        tool_names=tuple(sorted(set(observation.tool_names))),
        score=1.0,
    )


def _intent(text: str) -> str:
    clean = re.sub(
        r"\b(?:again|every time|repeat(?:ed|able)?|recurring|workflow|routine|"
        r"igen|varje gång|återkommande|arbetsflöde|rutin)\b",
        " ", text.casefold(), flags=re.I,
    )
    return " ".join(re.findall(r"[a-zåäö0-9]+", clean))[:120] or "repeated-work"


def candidate_identity(observation: CompletedTurnObservation) -> str:
    """Project identities include workspace; global identities deliberately do not."""
    workspace = observation.workspace_id if observation.scope == "project" else ""
    raw = "\x1f".join((observation.scope, workspace, _intent(observation.user_text)))
    return "skillneed_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class ShadowSkillNeedEngine:
    """Bounded process-memory engine. No filesystem, DB, UI or network access."""

    def __init__(
        self,
        *,
        max_candidates: int = 256,
        coverage_gap: Callable[[CompletedTurnObservation], bool] | None = None,
    ) -> None:
        self.max_candidates = max(1, max_candidates)
        self.coverage_gap = coverage_gap or (lambda _observation: True)
        self._evidence: OrderedDict[str, dict[str, CompletedTurnObservation]] = OrderedDict()
        self._emitted: set[str] = set()

    def observe(self, observation: CompletedTurnObservation) -> SkillNeedCandidate | None:
        qualified = candidate_from_observation(
            observation, coverage_gap=self.coverage_gap
        )
        if qualified is None:
            return None

        key = qualified.candidate_id
        runs = self._evidence.setdefault(key, {})
        runs[observation.run_id] = observation
        self._evidence.move_to_end(key)
        while len(self._evidence) > self.max_candidates:
            old, _ = self._evidence.popitem(last=False)
            self._emitted.discard(old)
        if len(runs) < 2 or key in self._emitted:
            return None

        self._emitted.add(key)
        tool_names = tuple(sorted({t for item in runs.values() for t in item.tool_names}))
        return SkillNeedCandidate(
            candidate_id=key,
            intent=qualified.intent,
            scope=observation.scope,
            workspace_id=observation.workspace_id if observation.scope == "project" else "",
            evidence_run_ids=tuple(sorted(runs)),
            steps=qualified.steps,
            tool_names=tool_names,
            score=1.0,
        )

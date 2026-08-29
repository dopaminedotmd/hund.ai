"""Pure, provider-neutral routing for completed-turn learning."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class LearningDestination(str, Enum):
    NONE = "none"
    KNOWLEDGE = "knowledge"
    SKILL_CANDIDATE = "skill_candidate"


@dataclass(frozen=True)
class CompletedTurnObservation:
    session_id: str
    turn_id: str
    run_id: str
    workspace_id: str
    user_text: str
    assistant_text: str
    tool_names: tuple[str, ...] = ()
    completed: bool = True
    verified: bool = False
    scope: str = "project"


@dataclass(frozen=True)
class DestinationDecision:
    destination: LearningDestination
    reasons: tuple[str, ...]


_REPEAT = re.compile(
    r"\b(?:again|every time|repeat(?:ed|able)?|recurring|workflow|routine|"
    r"igen|varje gång|återkommande|arbetsflöde|rutin)\b", re.I
)
_PROCEDURE = re.compile(
    r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s+|\b(?:first|then|next|finally|"
    r"först|sedan|därefter|slutligen)\b", re.I
)
_EXPLICIT_SKILL = re.compile(r"\b(?:create|build|make|skapa|bygg|gör)\b.{0,24}\bskill", re.I)


def route_learning_destination(observation: CompletedTurnObservation) -> DestinationDecision:
    """Route only high-signal completed work; never call a model or mutate state."""
    text = f"{observation.user_text}\n{observation.assistant_text}"
    if not observation.completed:
        return DestinationDecision(LearningDestination.NONE, ("turn_not_completed",))
    if _EXPLICIT_SKILL.search(observation.user_text):
        return DestinationDecision(LearningDestination.NONE, ("explicit_phase4_intent",))
    if _REPEAT.search(observation.user_text) and _PROCEDURE.search(text):
        return DestinationDecision(
            LearningDestination.SKILL_CANDIDATE,
            ("repeated_need", "procedural_shape"),
        )
    if observation.verified:
        return DestinationDecision(LearningDestination.KNOWLEDGE, ("verified_result",))
    return DestinationDecision(LearningDestination.NONE, ("insufficient_signal",))

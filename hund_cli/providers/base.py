"""Provider-abstraktion — enhetligt kontrakt över modell-leverantörer.

DESIGNBESLUT (review): v1 = EN shape, OpenAI-compatible (chat/completions +
tool-calls). Anthropic/Gemini har annorlunda tool-format och streaming-events —
de blir separata adapter först när v1 funkar. Detta kontrakt döljer den
skillnaden så agentloopen inte bryr sig.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class CompletionResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    raw: Any = None


class ProviderClient(ABC):
    """Enheltigt gränssnitt mot en modell-leverantör."""

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> CompletionResult:
        ...

    # @abstractmethod  # fas 1+
    # def stream(self, messages, tools=None, model=None): ...

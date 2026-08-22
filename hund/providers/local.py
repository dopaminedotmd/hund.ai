"""Local Provider — implements ProviderClient interface using LocalEngine.

Compatible with OpenAICompatibleClient interface for drop-in replacement
in the agent loop when no API key is available.
"""

from __future__ import annotations

import time
from typing import Any, Generator

from ..local.engine import LocalEngine, EngineNotRunningError
from .base import Message, CompletionResult, ProviderClient


class LocalProvider(ProviderClient):
    """Provider that runs inference via local llama.cpp engine.

    Args:
        engine: LocalEngine instance.
        model: Model name/identifier (default 'local').
    """

    def __init__(
        self,
        engine: LocalEngine,
        model: str = "local",
    ) -> None:
        self._engine = engine
        self._model = model
        self._base_url = f"http://{engine.port}"

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> CompletionResult:
        """Send messages to local engine and get completion.

        Args:
            messages: List of Message objects.
            tools: Not supported in local mode (ignored).
            model: Model override (defaults to 'local').

        Returns:
            CompletionResult with generated text.

        Raises:
            EngineNotRunningError: If local engine is not running.
        """
        if not self._engine.is_running:
            raise EngineNotRunningError("Local engine is not running. Start with `hund local start`.")

        start_time = time.time()

        # Convert Messages to dicts
        msg_dicts = []
        for m in messages:
            entry: dict[str, str] = {"role": m.role, "content": m.content}
            msg_dicts.append(entry)

        # If tools are provided, add a note about tool support
        if tools:
            tools_note = (
                "\n\n[System note: Tool calling is not supported in local mode. "
                "Respond with the best available information without calling tools.]"
            )
            if msg_dicts and msg_dicts[-1]["role"] == "user":
                msg_dicts[-1]["content"] += tools_note

        result = self._engine.complete(
            messages=msg_dicts,
            temperature=0.7,
            max_tokens=2048,
            timeout=120,
        )

        latency = int((time.time() - start_time) * 1000)

        return CompletionResult(
            text=result["text"],
            finish_reason=result["finish_reason"],
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
            latency_ms=latency,
        )

    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> Generator[str, None, None]:
        """Stream response from local engine (basic non-streaming fallback).

        Note: llama.cpp supports streaming SSE, but for simplicity in v1
        we yield the full response as a single chunk.
        """
        result = self.complete(messages, tools=tools, model=model)
        yield result.text

    @property
    def engine(self) -> LocalEngine:
        return self._engine

"""Tool registry — tools som JSON-schema + handler, samma princip som moderna agenter.

Varje tool har schema + basrisk. PermissionEngine klassificerar VID ANROP.
Dispatch (agent/tool_dispatch.py) frågar användare för ej-SAFE och nekar BLOCKED.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .types import (
    ToolCallContext,
    ToolKind,
    ToolResult,
    ToolStatus,
    create_error_result,
    create_success_result,
)

Handler = Callable[[dict], str | ToolResult] | Callable[[dict, ToolCallContext], str | ToolResult]
ContextMode = Literal["legacy", "required", "optional"]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON-schema för function-parameters
    base_risk: str  # matchar agent.safety.RiskLevel value
    handler: Handler | None = None  # sätts när workspace-known vid register
    context_mode: ContextMode = "legacy"
    category: str | None = None
    dispatch_description: str | None = None


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    _REGISTRY[tool.name] = tool


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def as_provider_schemas() -> list[dict]:
    """OpenAI-format tools-payload att skicka till providern."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]


def _normalize_legacy_result(value: str) -> ToolResult:
    stripped = value.strip()
    lowered = stripped.casefold()
    if lowered.startswith("[error]"):
        return create_error_result(
            ToolStatus.ERROR,
            ToolKind.TEXT,
            raw_error=stripped,
            public_error=stripped[7:].strip() or "Tool execution failed",
        )
    if lowered.startswith("[blocked]"):
        return ToolResult(
            ToolStatus.BLOCKED,
            ToolKind.TEXT,
            public_error=stripped[9:].strip() or "Action blocked",
        )
    if lowered.startswith("[declined"):
        message = stripped.split("]", 1)[1].strip() if "]" in stripped else "Declined"
        return ToolResult(ToolStatus.DECLINED, ToolKind.TEXT, public_error=message)
    return create_success_result(ToolKind.TEXT, value)


def call_typed(
    name: str,
    args: dict,
    context: ToolCallContext | None = None,
) -> ToolResult:
    """Run a handler through the typed, context-aware compatibility boundary."""
    tool = _REGISTRY.get(name)
    if tool is None or tool.handler is None:
        return ToolResult(
            ToolStatus.ERROR,
            ToolKind.TEXT,
            public_error=f"okänd/ohanterad tool: {name}",
        )
    if tool.context_mode == "required" and context is None:
        return ToolResult(
            ToolStatus.ERROR,
            ToolKind.TEXT,
            public_error=f"tool '{name}' requires execution context",
        )
    try:
        if tool.context_mode == "legacy":
            result = tool.handler(args)  # type: ignore[call-arg]
        else:
            result = tool.handler(args, context)  # type: ignore[call-arg]
        if isinstance(result, ToolResult):
            return result
        if isinstance(result, str):
            return _normalize_legacy_result(result)
        return ToolResult(
            ToolStatus.ERROR,
            ToolKind.TEXT,
            public_error=f"tool '{name}' returned an unsupported result type",
        )
    except Exception as e:  # tool-feil får inte krascha agentloopen
        return create_error_result(
            ToolStatus.ERROR,
            ToolKind.TEXT,
            raw_error=e,
            public_error="Tool execution failed",
        )


def call(
    name: str,
    args: dict,
    context: ToolCallContext | None = None,
) -> str:
    """Backward-compatible text boundary; all execution flows through call_typed."""
    return call_typed(name, args, context).to_llm_text()

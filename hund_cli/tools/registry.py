"""Tool registry — tools som JSON-schema + handler, samma princip som moderna agenter.

Varje tool har schema + basrisk. PermissionEngine klassificerar VID ANROP.
Dispatch (agent/tool_dispatch.py) frågar användare för ej-SAFE och nekar BLOCKED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

Handler = Callable[[dict], str]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON-schema för function-parameters
    base_risk: str  # matchar agent.safety.RiskLevel value
    handler: Handler | None = None  # sätts när workspace-known vid register


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


def call(name: str, args: dict) -> str:
    """Kör tool-handler. Raise om saknas."""
    tool = _REGISTRY.get(name)
    if tool is None or tool.handler is None:
        return f"[error] okänd/ohanterad tool: {name}"
    try:
        return tool.handler(args)
    except Exception as e:  # tool-feil får inte krascha agentloopen
        return f"[error] {type(e).__name__}: {e}"

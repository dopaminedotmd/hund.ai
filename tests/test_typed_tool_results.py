from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from hund.agent.safety import PermissionEngine
from hund.agent.tool_dispatch import dispatch_tool_call
from hund.tools import registry
from hund.tools.registry import Tool
from hund.tools.types import (
    ToolCallContext,
    ToolKind,
    ToolResult,
    ToolStatus,
    create_success_result,
)


def test_registry_normalizes_legacy_and_typed_results(monkeypatch, tmp_path):
    monkeypatch.setitem(
        registry._REGISTRY,
        "legacy_contract_test",
        Tool("legacy_contract_test", "test", {}, "safe", lambda args: "legacy ok"),
    )
    monkeypatch.setitem(
        registry._REGISTRY,
        "typed_contract_test",
        Tool(
            "typed_contract_test",
            "test",
            {},
            "safe",
            lambda args: create_success_result(ToolKind.OBSERVATION, {"ok": True}),
        ),
    )

    assert registry.call_typed("legacy_contract_test", {}).status is ToolStatus.SUCCESS
    typed = registry.call_typed("typed_contract_test", {})
    assert typed.status is ToolStatus.SUCCESS
    assert typed.payload == {"ok": True}


def test_required_context_is_enforced_and_forwarded(monkeypatch, tmp_path):
    seen: list[ToolCallContext | None] = []

    def handler(args, context):
        seen.append(context)
        return ToolResult(ToolStatus.SUCCESS, ToolKind.TEXT, "context ok")

    monkeypatch.setitem(
        registry._REGISTRY,
        "context_contract_test",
        Tool(
            "context_contract_test",
            "test",
            {},
            "safe",
            handler,
            context_mode="required",
        ),
    )
    missing = registry.call_typed("context_contract_test", {})
    assert missing.status is ToolStatus.ERROR
    assert not seen

    context = ToolCallContext("session", tmp_path, turn_id="turn")
    result = registry.call_typed("context_contract_test", {}, context)
    assert result.status is ToolStatus.SUCCESS
    assert seen == [context]


def test_handler_exception_is_redacted(monkeypatch):
    secret = "sk-1234567890abcdef1234567890"

    def explode(args):
        raise RuntimeError(f"token={secret}")

    monkeypatch.setitem(
        registry._REGISTRY,
        "exception_contract_test",
        Tool("exception_contract_test", "test", {}, "safe", explode),
    )
    result = registry.call_typed("exception_contract_test", {})
    assert result.status is ToolStatus.ERROR
    assert secret not in result.to_llm_text()
    assert secret not in (result.audit_error or "")


def test_dispatch_forwards_turn_context_to_typed_handler(monkeypatch, tmp_path):
    seen: list[ToolCallContext | None] = []

    def handler(args, context):
        seen.append(context)
        return create_success_result(ToolKind.FILE, "typed output")

    monkeypatch.setitem(
        registry._REGISTRY,
        "read_file",
        Tool("read_file", "test", {}, "safe", handler, context_mode="required"),
    )
    call = {"function": {"name": "read_file", "arguments": "{}"}}
    output = dispatch_tool_call(
        call,
        PermissionEngine(tmp_path),
        Console(file=io.StringIO(), force_terminal=False),
        session_id="session-1",
        turn_id="turn-1",
    )

    assert output == "typed output"
    assert len(seen) == 1
    assert seen[0] is not None
    assert seen[0].session_id == "session-1"
    assert seen[0].turn_id == "turn-1"
    assert seen[0].workspace == tmp_path.resolve()

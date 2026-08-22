"""Subagent delegation — isolerade child-agenter med egen PermissionEngine."""
from __future__ import annotations
import concurrent.futures
import uuid
from dataclasses import dataclass, field
from .safety import PermissionEngine, RiskLevel
from ..providers.base import Message
from ..providers.openai_compatible import OpenAICompatibleClient
from ..tools import registry as tool_registry
from ..trace.events import create_event, write_event

BLOCKED_CHILD_TOOLS = {
    "execute_code", "delegate_task", "memory",
    "self_update", "apply_update", "modify_tcb",
}
MAX_CHILDREN = 3
CHILD_MAX_TOOL_ROUNDS = 5
CHILD_SYSTEM_PROMPT = (
    "Du ar en subagent till Hund CLI. Kor uppgiften sjalvstandigt. "
    "Anvand verktyg vid behov. Returnera en kortfattad sammanfattning nar du ar klar. "
    "Svara pa svenska. Inga emojis. Tredje person ('subagenten ser'). "
    "Du har begransade verktyg och kan inte self-improve."
)

@dataclass
class DelegationResult:
    task_id: int
    summary: str
    success: bool
    error: str = ""

def _run_child(
    task_id: int,
    goal: str,
    context: str,
    client: OpenAICompatibleClient,
    allowed_tools: set[str],
    parent_run_id: str | None = None,
    session_id: str = "delegation-session",
    workspace_id: str | None = None,
) -> DelegationResult:
    """Kor EN subagent — isolerad session."""
    child_run_id = uuid.uuid4().hex
    workspace_id = workspace_id or "delegation"

    def _emit(event_type: str, payload: dict, *, success_risk: str = "none") -> None:
        try:
            event = create_event(
                workspace_id=workspace_id,
                session_id=session_id,
                run_id=child_run_id,
                parent_run_id=parent_run_id,
                actor="subagent",
                event_type=event_type,
                policy_version="1.0.0",
                payload_unredacted=payload,
                risk=success_risk,
            )
            write_event(event)
        except Exception:
            pass

    _emit("run_started", {"task_id": task_id, "goal": goal})
    try:
        # Bygg meddelanden
        system_msg = Message(role="system", content=CHILD_SYSTEM_PROMPT)
        user_msg = Message(
            role="user",
            content=f"UPPGIFT: {goal}\n\nKONTEXT: {context}\n\nKor uppgiften och sammanfatta resultatet.",
        )
        messages = [system_msg, user_msg]
        # PermissionEngine i RESTRICTED mode — bara SAFE tools
        engine = PermissionEngine(mode="subagent")
        # Filtrera tools
        all_schemas = tool_registry.as_provider_schemas()
        child_schemas = [
            s for s in all_schemas
            if s["function"]["name"] in allowed_tools
        ]
        if not child_schemas:
            _emit("run_completed", {"task_id": task_id, "success": False, "error": "inga tillatna tools"})
            return DelegationResult(task_id, "", False, "inga tillatna tools")
        # Agent loop — noninteractive
        max_rounds = CHILD_MAX_TOOL_ROUNDS
        for _ in range(max_rounds):
            result = client.complete(messages, tools=child_schemas)
            if not result.tool_calls:
                messages.append(Message(role="assistant", content=result.text))
                break
            # Tool anrop — noninteractive, SAFE only
            messages.append(Message(role="assistant", content=result.text or "", tool_calls=result.tool_calls))
            for tc in result.tool_calls:
                name = tc.get("function", {}).get("name", "")
                raw_args = tc.get("function", {}).get("arguments", "{}")
                import json
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
                decision = engine.classify(name, args)
                if decision.risk == RiskLevel.BLOCKED:
                    outcome = f"[blocked] {decision.reason}"
                elif decision.risk == RiskLevel.SAFE:
                    outcome = tool_registry.call(name, args)
                else:
                    outcome = f"[declined] {decision.risk} kräver godkännande (noninteractive child)"
                tc_id = tc.get("id")
                messages.append(Message(role="tool", content=outcome, tool_call_id=tc_id))
        # Extrahera sista assistant-meddelandet som summary
        for m in reversed(messages):
            if m.role == "assistant" and m.content:
                _emit("run_completed", {"task_id": task_id, "success": True})
                return DelegationResult(task_id, m.content[:2000], True)
        _emit("run_completed", {"task_id": task_id, "success": True, "empty": True})
        return DelegationResult(task_id, "(inget svar)", True)
    except Exception as e:
        _emit("run_completed", {"task_id": task_id, "success": False, "error": str(e)})
        return DelegationResult(task_id, "", False, str(e))


def delegate_tasks(
    tasks: list[dict],
    client: OpenAICompatibleClient,
    *,
    allowed_tools: set[str] | None = None,
    max_workers: int = MAX_CHILDREN,
    parent_run_id: str | None = None,
    session_id: str = "delegation-session",
    workspace_id: str | None = None,
) -> list[DelegationResult]:
    """Spawna upp till max_workers subagents parallellt."""
    if allowed_tools is None:
        # Default: alla SAFE tools utom blockerade
        allowed_tools = set()
        for t in tool_registry.all_tools():
            if t.base_risk == "safe" and t.name not in BLOCKED_CHILD_TOOLS:
                allowed_tools.add(t.name)
    workers = min(max_workers, len(tasks), MAX_CHILDREN)
    results: list[DelegationResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, task in enumerate(tasks):
            fut = executor.submit(
                _run_child,
                task_id=i,
                goal=task.get("goal", task.get("prompt", "")),
                context=task.get("context", ""),
                client=client,
                allowed_tools=allowed_tools,
                parent_run_id=parent_run_id,
                session_id=session_id,
                workspace_id=workspace_id,
            )
            futures[fut] = i
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    return results


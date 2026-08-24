"""Tool dispatch — säkerhetscirkeln kring varje tool-anrop.

Flöde per tool_call:
  1. PermissionEngine.classify(tool, args)
  2. BLOCKED  -> alltid nekad (aldrig fråga, aldrig kör)
  3. SAFE     -> auto-tillåten (kan stängas av)
  4. annat    -> fråga användare; nej = declined
  5. approved  -> kör handler, returnera resultat
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from rich.console import Console

from ..tools import registry
from ..tools.types import ToolCallContext, ToolStatus
from .safety import PermissionEngine, RiskLevel, Decision
from .types import ConfirmRequest, ConfirmResponse, ConfirmVerdict, normalize_confirm_response
from ..trace.events import create_event, write_event

class SessionAllowlist:
    """Per-session tool allowlist. Thread-safe via dict isolation.

    SECURITY: prevents cross-session and cross-thread allowlist leakage.
    A tool approved in session A must never be auto-approved in session B.
    """

    def __init__(self) -> None:
        self._allowed: dict[str, set[str]] = {}

    def is_allowed(self, session_id: str | None, tool: str) -> bool:
        sid = session_id or "_default"
        return tool in self._allowed.get(sid, set())

    def allow(self, session_id: str | None, tool: str) -> None:
        sid = session_id or "_default"
        self._allowed.setdefault(sid, set()).add(tool)

    def clear_session(self, session_id: str | None) -> None:
        sid = session_id or "_default"
        self._allowed.pop(sid, None)

    def clear(self) -> None:
        """Clear all sessions (for test fixtures / resets)."""
        self._allowed.clear()

    def add(self, tool: str) -> None:
        """Backward compatibility for set-like interface."""
        self.allow(None, tool)

    def __contains__(self, tool: str) -> bool:
        """Check if tool is allowed in default session or any session."""
        return any(tool in tools for tools in self._allowed.values())


_SESSION_ALLOWLIST = SessionAllowlist()


def _parse(tc: dict) -> tuple[str, dict]:
    fn = tc.get("function", tc)
    name = fn.get("name", "<unknown>")
    raw = fn.get("arguments", "{}") or "{}"
    try:
        return name, json.loads(raw)
    except json.JSONDecodeError:
        return name, {"_raw_arguments": raw}


TOOL_DOMAIN_MAP = {
    "read_file": "files",
    "write_file": "files",
    "edit_file": "files",
    "replace_file_content": "files",
    "list_dir": "files",
    "search_files": "files",
    "grep_search": "files",
    "terminal": "system",
    "powershell": "system",
    "bash": "system",
    "cmd": "system",
    "git": "git",
    "web_search": "research",
    "fetch_web_page": "research",
    "read_url_content": "research",
}

_TURN_TOOL_XP: dict[tuple[str, str], int] = {}


def _log_tool(tool: str, risk: str, outcome: str, success: int, run_id: str | None = None) -> None:
    """Compatibility telemetry hook. Tool use never awards domain XP."""
    return None


def dispatch_tool_call(
    tc: dict,
    engine: PermissionEngine,
    console: Console,
    *,
    auto_approve_safe: bool = True,
    noninteractive: bool = False,
    hooks=None,
    run_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    tool_context: ToolCallContext | None = None,
) -> str:
    """Kör ett tool-anrop genom säkerhetscirkeln. Returnerar tool-resultatsträng.

    hooks (valfritt, duck-typed) — när givet styrs UI-output via callbacks istället
    för console.print/input. Säkerhetsvägen (classify/block/approve) är densamma
    oavsett hooks. hooks=None = exakt tidigare console-beteende.
    """
    name, args = _parse(tc)
    decision = engine.classify(name, args)
    workspace_id = str(engine.workspace_root)

    # Helper för att skriva händelser under anropet
    def _emit(event_type: str, payload: dict, risk_level: str = "none", approval_id: str | None = None):
        if run_id and session_id:
            try:
                event = create_event(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    run_id=run_id,
                    actor="hund",
                    event_type=event_type,
                    policy_version="1.0.0",
                    payload_unredacted=payload,
                    risk=risk_level,
                    tool_name=name,
                    approval_id=approval_id
                )
                write_event(event)
            except Exception:
                pass

    _emit("tool_call_requested", args)
    _emit("tool_call_classified", {
        "risk": decision.risk.value,
        "allowed": decision.allowed,
        "reason": decision.reason
    }, risk_level=decision.risk.value)

    # Session-allowlist: hoppa over confirm for tidigare tillatna tools
    if (
        name == "terminal"
        and decision.risk == RiskLevel.CONFIRM
        and _SESSION_ALLOWLIST.is_allowed(session_id, name)
    ):
        decision = Decision(RiskLevel.SAFE, allowed=True, reason="session-allowlisted")

    if decision.risk is RiskLevel.BLOCKED:
        _emit("tool_call_blocked", {"reason": decision.reason}, risk_level=decision.risk.value)
        if hooks is not None:
            hooks.blocked(name, decision.reason)
        else:
            console.print(f"[red]BLOCKED[/red] {name} — {decision.reason}")
        return f"[blocked] {decision.reason}"

    if not (decision.risk is RiskLevel.SAFE and auto_approve_safe):
        approved_id = str(uuid.uuid4())
        if noninteractive:
            reason = f"{decision.risk} requires approval"
            _emit("tool_call_declined", {"reason": reason}, risk_level=decision.risk.value, approval_id=approved_id)
            if hooks is not None:
                hooks.declined(name, reason)
            else:
                console.print(f"[yellow]DECLINED[/yellow] (noninteractive) {name} {args}")
            return f"[declined: {reason}]"

        request = ConfirmRequest(tool_name=name, args=args, risk=decision.risk.value)

        if hooks is not None:
            response = normalize_confirm_response(hooks.confirm(request))
        else:
            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 200:
                preview = preview[:200] + "…"
            prompt = (
                f"[yellow]{decision.risk.upper()}[/yellow] hund wants to run "
                f"[bold]{name}[/bold] {preview} — allow? [y/N]"
            )
            ans = console.input(prompt + " ").strip().lower()
            if ans in {"y", "yes", "j", "ja"}:
                response = ConfirmResponse(ConfirmVerdict.APPROVE_ONCE)
            else:
                response = ConfirmResponse(ConfirmVerdict.DENY)

        verdict = response.verdict

        if verdict is ConfirmVerdict.DENY:
            _emit("tool_call_declined", {"reason": "user declined"}, risk_level=decision.risk.value, approval_id=approved_id)
            if hooks is not None:
                hooks.declined(name, "declined by user")
            else:
                console.print("[dim]declined by user[/dim]")
            return "[declined by user]"

        if verdict is ConfirmVerdict.EDIT:
            edited_args = response.edited_args
            if edited_args is None and hooks is not None and hasattr(hooks, "edit"):
                try:
                    edited_args = hooks.edit(request)
                except Exception:
                    edited_args = None
            if not isinstance(edited_args, dict):
                _emit("tool_call_declined", {"reason": "edit cancelled"}, risk_level=decision.risk.value, approval_id=approved_id)
                if hooks is not None:
                    hooks.declined(name, "edit cancelled")
                return "[declined: edit cancelled]"
            _emit(
                "tool_call_edited",
                {"original_args": args, "edited_args": edited_args},
                risk_level=decision.risk.value,
                approval_id=approved_id,
            )
            edited_call = {
                "function": {
                    "name": name,
                    "arguments": json.dumps(dict(edited_args), ensure_ascii=False),
                }
            }
            return dispatch_tool_call(
                edited_call, engine, console,
                auto_approve_safe=auto_approve_safe,
                noninteractive=noninteractive, hooks=hooks,
                run_id=run_id, session_id=session_id, turn_id=turn_id,
                tool_context=tool_context,
            )

        _emit("tool_call_approved", {}, risk_level=decision.risk.value, approval_id=approved_id)

        if (
            verdict is ConfirmVerdict.ALLOW_SESSION
            and name == "terminal"
            and decision.risk == RiskLevel.CONFIRM
        ):
            _SESSION_ALLOWLIST.allow(session_id, name)

    _emit("tool_call_started", args, risk_level=decision.risk.value)
    if hooks is not None:
        hooks.tool_start(name, args)
    if tool_context is None:
        tool_context = ToolCallContext(
            session_id=session_id or "_default",
            turn_id=turn_id,
            workspace=engine.workspace_root,
        )
    typed_result = registry.call_typed(name, args, context=tool_context)
    result = typed_result.to_llm_text()
    # Trunkera stora tool-resultat innan de hamnar i context window.
    MAX_TOOL_OUTPUT = 50_000  # ~12K tokens
    if len(result) > MAX_TOOL_OUTPUT:
        result = result[:MAX_TOOL_OUTPUT] + "\n[TRUNCATED — output oversteg 50KB]"
    success = 1 if typed_result.status is ToolStatus.SUCCESS else 0
    _log_tool(name, decision.risk.value, result, success, run_id=run_id)
    if success:
        _emit("tool_call_completed", {"stdout_redacted_summary": result[:200]}, risk_level=decision.risk.value)
    else:
        _emit(
            "tool_call_failed",
            {"error": typed_result.audit_error or typed_result.public_error or typed_result.status.value},
            risk_level=decision.risk.value,
        )
    if run_id and session_id:
        try:
            from .injection_trace import scan_and_emit

            scan_and_emit(
                result,
                source="tool_output",
                workspace_id=workspace_id,
                session_id=session_id,
                run_id=run_id,
            )
        except Exception:
            pass
        if name == "terminal":
            try:
                from .verification import classify_and_emit

                classify_and_emit(
                    command=str(args.get("command", "")),
                    exit_code=0 if success else 1,
                    stdout_summary=result[:1000],
                    workspace_id=workspace_id,
                    session_id=session_id,
                    run_id=run_id,
                    tool_name=name,
                )
            except Exception:
                pass
    shown = result if len(result) <= 120 else result[:120] + "…"
    if hooks is not None:
        hooks.tool_result(name, shown)
    else:
        console.print(f"[dim]tool {name} -> {shown}[/dim]")
    return result


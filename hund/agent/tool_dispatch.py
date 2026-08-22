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
from .safety import PermissionEngine, RiskLevel, Decision
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


def _log_tool(tool: str, risk: str, outcome: str, success: int) -> None:
    """Deprecated in favor of trace_events."""
    pass


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
    if decision.risk == RiskLevel.CONFIRM and _SESSION_ALLOWLIST.is_allowed(session_id, name):
        decision = Decision(RiskLevel.SAFE, allowed=True, reason="session-allowlisted")

    if decision.risk is RiskLevel.BLOCKED:
        _emit("tool_call_blocked", {"reason": decision.reason}, risk_level=decision.risk.value)
        if hooks is not None:
            hooks.blocked(name, decision.reason)
        else:
            console.print(f"[red]BLOCKERAD[/red] {name} — {decision.reason}")
        return f"[blocked] {decision.reason}"

    if not (decision.risk is RiskLevel.SAFE and auto_approve_safe):
        approved_id = str(uuid.uuid4())
        if noninteractive:
            reason = f"{decision.risk} kräver godkännande"
            _emit("tool_call_declined", {"reason": reason}, risk_level=decision.risk.value, approval_id=approved_id)
            if hooks is not None:
                hooks.declined(name, reason)
            else:
                console.print(f"[yellow]NEKAD[/yellow] (noninteractive) {name} {args}")
            return f"[declined: {reason}]"
        preview = json.dumps(args, ensure_ascii=False)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        prompt = (
            f"[yellow]{decision.risk.upper()}[/yellow] Hund vill köra "
            f"[bold]{name}[/bold] {preview} — tillåt? [j/N]"
        )
        if hooks is not None:
            approved = hooks.confirm(prompt)
        else:
            ans = console.input(prompt + " ").strip().lower()
            approved = ans in {"j", "y", "ja", "yes"}
        if not approved:
            _emit("tool_call_declined", {"reason": "user declined"}, risk_level=decision.risk.value, approval_id=approved_id)
            if hooks is not None:
                hooks.declined(name, "nekad av användare")
            else:
                console.print("[dim]nekad av användare[/dim]")
            return "[declined by user]"
        _emit("tool_call_approved", {}, risk_level=decision.risk.value, approval_id=approved_id)
        # Efter godkannande: erbjud session-allowlist
        if decision.risk == RiskLevel.CONFIRM:
            if hooks is not None:
                allow_all = hooks.confirm("Tillat alla " + name + " i denna session? [j/N/a(lla)]")
            else:
                ans = console.input(
                    f"[dim]Tillat alla [bold]{name}[/bold] i denna session? [j/N/a(lla)] [/dim]"
                ).strip().lower()
                allow_all = ans in {"a", "alla"}
            if allow_all:
                _SESSION_ALLOWLIST.allow(session_id, name)

    _emit("tool_call_started", args, risk_level=decision.risk.value)
    if hooks is not None:
        hooks.tool_start(name, args)
    result = registry.call(name, args)
    # Trunkera stora tool-resultat innan de hamnar i context window.
    MAX_TOOL_OUTPUT = 50_000  # ~12K tokens
    if len(result) > MAX_TOOL_OUTPUT:
        result = result[:MAX_TOOL_OUTPUT] + "\n[TRUNCATED — output oversteg 50KB]"
    success = 0 if result.startswith("[error]") else 1
    if success:
        _emit("tool_call_completed", {"stdout_redacted_summary": result[:200]}, risk_level=decision.risk.value)
    else:
        _emit("tool_call_failed", {"error": result}, risk_level=decision.risk.value)
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



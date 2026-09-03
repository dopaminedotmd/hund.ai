"""Dispatch every tool call through the central safety boundary."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

from rich.console import Console

from ..tools import registry
from ..tools.types import ToolCallContext, ToolStatus
from .safety import PermissionEngine, RiskLevel, Decision
from .types import ConfirmRequest, ConfirmResponse, ConfirmVerdict, normalize_confirm_response
from ..trace.events import create_event, write_event

def _canonical_args_str(args: object) -> str:
    if args is None:
        return ""
    if isinstance(args, dict):
        return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(args)


def _emit_session_grant_event(
    event_type: str,
    payload: dict,
    *,
    session_id: str,
    workspace_id: str | None = None,
    run_id: str | None = None,
    risk_level: str = "none",
    tool_name: str | None = None,
    approval_id: str | None = None,
) -> None:
    if not session_id:
        return
    try:
        event = create_event(
            workspace_id=workspace_id or str(Path.cwd()),
            session_id=session_id,
            run_id=run_id or uuid.uuid4().hex,
            actor="hund",
            event_type=event_type,
            policy_version="1.0.0",
            payload_unredacted=payload,
            risk=risk_level,
            tool_name=tool_name or "",
            approval_id=approval_id,
        )
        write_event(event)
    except Exception:
        pass


class SessionAllowlist:
    """Store narrowly scoped policy approvals for one live session."""

    def __init__(self) -> None:
        self._allowed: dict[str, set[tuple[str, str, str, str]]] = {}

    def is_allowed(
        self,
        session_id: str | None,
        tool: str,
        policy_id: str | None,
        args: dict | None = None,
        risk: str | RiskLevel | None = None,
    ) -> bool:
        if not session_id or not policy_id:
            return False
        risk_str = risk.value if isinstance(risk, RiskLevel) else (risk or "confirm")
        canonical = _canonical_args_str(args)
        entries = self._allowed.get(session_id, set())
        if tool == "terminal":
            return any(
                entry_tool == tool
                and (
                    entry_policy == policy_id
                    or (entry_policy in ("terminal.compound", "terminal.unknown") and policy_id in ("terminal.compound", "terminal.unknown"))
                )
                and entry_risk == risk_str
                for entry_tool, entry_policy, entry_risk, _entry_args in entries
            )
        return (tool, policy_id, risk_str, canonical) in entries

    def allow(
        self,
        session_id: str | None,
        tool: str,
        decision: Decision,
        args: dict | None = None,
    ) -> bool:
        if (
            not session_id
            or decision.risk is not RiskLevel.CONFIRM
            or not decision.policy_id
            or not decision.session_allowable
        ):
            return False
        risk_str = decision.risk.value
        canonical = _canonical_args_str(args)
        self._allowed.setdefault(session_id, set()).add(
            (tool, decision.policy_id, risk_str, canonical)
        )
        return True

    def revoke(
        self,
        session_id: str | None,
        tool: str,
        policy_id: str | None,
        args: dict | None = None,
        risk: str | RiskLevel | None = None,
        *,
        run_id: str | None = None,
        workspace_id: str | None = None,
        approval_id: str | None = None,
    ) -> bool:
        if not session_id or not policy_id:
            return False
        risk_str = risk.value if isinstance(risk, RiskLevel) else (risk or "confirm")
        canonical = _canonical_args_str(args)
        entries = self._allowed.get(session_id)
        key = (tool, policy_id, risk_str, canonical)
        if entries and key in entries:
            entries.remove(key)
            _emit_session_grant_event(
                "session_grant_revoked",
                {
                    "session_id": session_id,
                    "tool": tool,
                    "policy_id": policy_id,
                    "risk": risk_str,
                    "args": args,
                },
                session_id=session_id,
                workspace_id=workspace_id,
                run_id=run_id,
                risk_level=risk_str,
                tool_name=tool,
                approval_id=approval_id,
            )
            return True
        return False

    def clear_session(
        self,
        session_id: str | None,
        *,
        run_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if session_id:
            existed = self._allowed.pop(session_id, None)
            if existed:
                _emit_session_grant_event(
                    "session_grant_cleared",
                    {
                        "session_id": session_id,
                        "cleared_grants": len(existed),
                    },
                    session_id=session_id,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    risk_level="none",
                )

    def clear(self) -> None:
        """Clear all sessions (for test fixtures / resets)."""
        self._allowed.clear()

    def __contains__(self, tool: str) -> bool:
        """Support diagnostic membership checks without broadening scope."""
        return any(
            any(entry_tool == tool for entry_tool, _, _, _ in entries)
            for entries in self._allowed.values()
        )


_SESSION_ALLOWLIST = SessionAllowlist()
_TURN_TERMINAL_ALLOWLIST: set[tuple[str, str]] = set()
_PREFLIGHT_ALLOWLIST: set[tuple[str, str, str, str]] = set()


def _parse(tc: dict) -> tuple[str, dict]:
    fn = tc.get("function", tc)
    name = fn.get("name", "<unknown>")
    raw = fn.get("arguments", "{}") or "{}"
    try:
        return name, json.loads(raw)
    except Exception:
        return name, {}


def preflight_check_tool_calls(
    tool_calls: list[dict],
    engine: PermissionEngine,
    console: Console,
    *,
    hooks=None,
    session_id: str | None = None,
    turn_id: str | None = None,
    noninteractive: bool = False,
) -> bool:
    """Classify all tool calls in advance.

    If any call requires confirmation and is not already allowlisted,
    prompt the user before executing any tool in the turn.
    Returns False if the user denies confirmation (cancelling the whole chain),
    or True if execution should proceed.
    """
    for tc in tool_calls:
        name, args = _parse(tc)
        decision = engine.classify(name, args)
        canonical_args = _canonical_args_str(args)

        if decision.risk is not RiskLevel.CONFIRM:
            continue

        if (
            name == "terminal"
            and session_id
            and turn_id
            and (session_id, turn_id) in _TURN_TERMINAL_ALLOWLIST
        ):
            continue

        if (
            decision.session_allowable
            and _SESSION_ALLOWLIST.is_allowed(session_id, name, decision.policy_id, args=args, risk=decision.risk)
        ):
            continue

        if (
            session_id
            and turn_id
            and (session_id, turn_id, name, canonical_args) in _PREFLIGHT_ALLOWLIST
        ):
            continue

        if noninteractive:
            return False

        request = ConfirmRequest(
            tool_name=name,
            args=args,
            risk=decision.risk.value,
            reason=decision.reason,
            policy_id=decision.policy_id or "",
            session_allowable=decision.session_allowable,
            turn_allowable=name == "terminal" and decision.risk is RiskLevel.CONFIRM,
        )

        if hooks is not None:
            response = normalize_confirm_response(hooks.confirm(request))
        else:
            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 200:
                preview = preview[:200] + "…"
            prompt = (
                f"[yellow]{decision.risk.upper()}[/yellow] "
                "hund wants to run a potentially dangerous command: "
                f"[bold]{name}[/bold] {preview} — allow? [y/N]"
            )
            ans = console.input(prompt + " ").strip().lower()
            if ans in {"y", "yes", "j", "ja"}:
                response = ConfirmResponse(ConfirmVerdict.APPROVE_ONCE)
            else:
                response = ConfirmResponse(ConfirmVerdict.DENY)

        verdict = response.verdict
        if verdict is ConfirmVerdict.DENY:
            return False
        elif verdict is ConfirmVerdict.ALLOW_SESSION:
            _SESSION_ALLOWLIST.allow(session_id, name, decision, args=args)
        elif verdict is ConfirmVerdict.ALLOW_TURN and name == "terminal":
            if session_id and turn_id:
                _TURN_TERMINAL_ALLOWLIST.add((session_id, turn_id))
        elif verdict is ConfirmVerdict.APPROVE_ONCE:
            if session_id and turn_id:
                _PREFLIGHT_ALLOWLIST.add((session_id, turn_id, name, canonical_args))
        elif verdict is ConfirmVerdict.EDIT:
            if session_id and turn_id:
                _PREFLIGHT_ALLOWLIST.add((session_id, turn_id, name, canonical_args))

    return True


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

    if (
        name == "terminal"
        and decision.risk is RiskLevel.CONFIRM
        and session_id
        and turn_id
        and (session_id, turn_id) in _TURN_TERMINAL_ALLOWLIST
    ):
        decision = Decision(RiskLevel.SAFE, allowed=True, reason="Approved terminal commands for this turn")

    canonical_args = _canonical_args_str(args)
    if (
        decision.risk is RiskLevel.CONFIRM
        and session_id
        and turn_id
        and (session_id, turn_id, name, canonical_args) in _PREFLIGHT_ALLOWLIST
    ):
        _PREFLIGHT_ALLOWLIST.discard((session_id, turn_id, name, canonical_args))
        decision = Decision(RiskLevel.SAFE, allowed=True, reason="Pre-flight approved tool call")

    # A session grant only applies to the exact policy category, risk and arguments that were approved.
    if (
        decision.risk is RiskLevel.CONFIRM
        and decision.session_allowable
        and _SESSION_ALLOWLIST.is_allowed(session_id, name, decision.policy_id, args=args, risk=decision.risk)
    ):
        _emit("session_grant_hit", {
            "tool": name,
            "policy_id": decision.policy_id,
            "risk": decision.risk.value,
            "args": args,
        }, risk_level=decision.risk.value)
        decision = Decision(
            RiskLevel.SAFE,
            allowed=True,
            reason="Approved command for this session",
            policy_id=decision.policy_id,
            session_allowable=False,
        )

    if decision.risk is RiskLevel.BLOCKED:
        _emit("tool_call_blocked", {"reason": decision.reason}, risk_level=decision.risk.value)
        if hooks is not None:
            hooks.blocked(name, decision.reason)
        else:
            console.print(f"[red]BLOCKED[/red] {name} — {decision.reason}")
        return f"[blocked] {decision.reason}"

    # Phase 3 Skill Authoring Guards
    effective_sid = (tool_context.session_id if tool_context else None) or session_id or args.get("session_id")
    from ..skills.authoring import AuthoringState, get_authoring_registry
    auth_reg = get_authoring_registry()
    auth_session = auth_reg.get(effective_sid) if effective_sid else None

    # 1. External Research Grant Check during active Skill Authoring
    if auth_session is not None and (
        name in ("web_search", "fetch_web_page", "read_url_content", "web_open", "web_extract")
        or TOOL_DOMAIN_MAP.get(name) == "research"
    ):
        grant = auth_session.research_grant
        if grant is None or not grant.is_valid(name):
            reason = "external research not authorized for this authoring session"
            _emit("tool_call_declined", {"reason": reason}, risk_level=decision.risk.value)
            if hooks is not None:
                hooks.declined(name, reason)
            else:
                console.print(f"[yellow]DECLINED[/yellow] {name} — {reason}")
            return f"[declined: {reason}]"

    # 2. Exact-Draft Single-Use Publication Authorization Check for create_skill
    publication_binding: tuple[str, str, str] | None = None
    if name == "create_skill":
        from ..skills.contracts import compute_payload_hash

        skill_payload = args.get("skill")
        supplied_hash = str(args.get("payload_hash", ""))
        supplied_auth_id = str(args.get("authorization_id", ""))
        actual_hash = compute_payload_hash(skill_payload) if isinstance(skill_payload, dict) else ""
        auth = auth_session.publication_authorization if auth_session is not None else None
        requested_scope = str(skill_payload.get("scope", "global")) if isinstance(skill_payload, dict) else ""
        requested_disposition = str(args.get("desired_disposition", "auto"))
        terminal_authoring_states = {
            AuthoringState.PUBLISHED,
            AuthoringState.CANCELLED,
            AuthoringState.FAILED,
        }
        if (
            auth_session is None
            or auth_session.state in terminal_authoring_states
            or auth is None
            or not isinstance(skill_payload, dict)
            or not supplied_hash
            or not supplied_auth_id
            or supplied_hash != actual_hash
            or supplied_auth_id != auth.authorization_id
            or effective_sid != auth.session_id
            or requested_scope != auth.scope
            or requested_disposition != auth.disposition
            or not auth.is_valid(actual_hash)
        ):
            reason = "unconfirmed or modified skill payload requires explicit user acceptance"
            _emit("tool_call_declined", {"reason": reason}, risk_level=decision.risk.value)
            if hooks is not None:
                hooks.declined(name, reason)
            else:
                console.print(f"[yellow]DECLINED[/yellow] {name} — {reason}")
            return f"[declined: {reason}]"
        publication_binding = (effective_sid, supplied_auth_id, actual_hash)

    if publication_binding is None and not (
        decision.risk is RiskLevel.SAFE and auto_approve_safe
    ):
        approved_id = str(uuid.uuid4())
        if noninteractive:
            reason = f"{decision.risk} requires approval"
            _emit("tool_call_declined", {"reason": reason}, risk_level=decision.risk.value, approval_id=approved_id)
            if hooks is not None:
                hooks.declined(name, reason)
            else:
                console.print(f"[yellow]DECLINED[/yellow] (noninteractive) {name} {args}")
            return f"[declined: {reason}]"

        request = ConfirmRequest(
            tool_name=name,
            args=args,
            risk=decision.risk.value,
            reason=decision.reason,
            policy_id=decision.policy_id or "",
            session_allowable=decision.session_allowable,
            turn_allowable=name == "terminal" and decision.risk is RiskLevel.CONFIRM,
        )

        if hooks is not None:
            response = normalize_confirm_response(hooks.confirm(request))
        else:
            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 200:
                preview = preview[:200] + "…"
            prompt = (
                f"[yellow]{decision.risk.upper()}[/yellow] "
                "hund wants to run a potentially dangerous command: "
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

        if verdict is ConfirmVerdict.ALLOW_SESSION:
            if _SESSION_ALLOWLIST.allow(session_id, name, decision, args=args):
                _emit("session_grant_added", {
                    "tool": name,
                    "policy_id": decision.policy_id,
                    "risk": decision.risk.value,
                    "args": args,
                }, risk_level=decision.risk.value, approval_id=approved_id)
        elif verdict is ConfirmVerdict.ALLOW_TURN and name == "terminal" and session_id and turn_id:
            _TURN_TERMINAL_ALLOWLIST.add((session_id, turn_id))

    if publication_binding is not None:
        pub_session_id, pub_auth_id, pub_hash = publication_binding
        if not auth_reg.consume_publication_authorization(pub_session_id, pub_auth_id, pub_hash):
            reason = "publication authorization was already used or expired"
            _emit("tool_call_declined", {"reason": reason}, risk_level=decision.risk.value)
            if hooks is not None:
                hooks.declined(name, reason)
            return f"[declined: {reason}]"

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
    if publication_binding is not None and not success:
        from dataclasses import replace

        failed_session = auth_reg.get(publication_binding[0])
        if failed_session is not None and failed_session.state == AuthoringState.PUBLISHING:
            auth_reg.save(replace(
                failed_session,
                state=AuthoringState.READY,
                publication_authorization=None,
            ))
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
    if hooks is not None and hasattr(hooks, "tool_result"):
        hooks.tool_result(name, shown)
    else:
        console.print(f"[dim]tool {name} -> {shown}[/dim]")
    return result

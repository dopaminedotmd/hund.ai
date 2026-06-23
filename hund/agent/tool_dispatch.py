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

from ..store.sqlite import connect_tool_events
from ..tools import registry
from .safety import PermissionEngine, RiskLevel, Decision

_SESSION_ALLOWLIST: set[str] = set()


def _parse(tc: dict) -> tuple[str, dict]:
    fn = tc.get("function", tc)
    name = fn.get("name", "<unknown>")
    raw = fn.get("arguments", "{}") or "{}"
    try:
        return name, json.loads(raw)
    except json.JSONDecodeError:
        return name, {"_raw_arguments": raw}


def _log_tool(tool: str, risk: str, outcome: str, success: int) -> None:
    """Logga tool-event till logs/tool_events.db. Får ej krascha agentloopen."""
    try:
        conn = connect_tool_events()
        conn.execute(
            """INSERT INTO tool_events(id, created_at, tool, risk, outcome, success)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(), tool, risk, outcome, success),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def dispatch_tool_call(
    tc: dict,
    engine: PermissionEngine,
    console: Console,
    *,
    auto_approve_safe: bool = True,
    noninteractive: bool = False,
    hooks=None,
) -> str:
    """Kör ett tool-anrop genom säkerhetscirkeln. Returnerar tool-resultatsträng.

    hooks (valfritt, duck-typed) — när givet styrs UI-output via callbacks istället
    för console.print/input. Säkerhetsvägen (classify/block/approve) är densamma
    oavsett hooks. hooks=None = exakt tidigare console-beteende.

    Sink-protokoll (se agent/loop.py):
      hooks.tool_start(name, args)     innan körning (≈ "● läser X")
      hooks.confirm(prompt) -> bool    True = tillåt (ersätter console.input)
      hooks.tool_result(name, shown)   efter körning
      hooks.blocked(name, reason)
      hooks.declined(name, reason)
    """
    name, args = _parse(tc)
    decision = engine.classify(name, args)

    # Session-allowlist: hoppa over confirm for tidigare tillatna tools
    if decision.risk == RiskLevel.CONFIRM and name in _SESSION_ALLOWLIST:
        decision = Decision(RiskLevel.SAFE, allowed=True, reason="session-allowlisted")

    if decision.risk is RiskLevel.BLOCKED:
        _log_tool(name, decision.risk.value, "blocked", 0)
        if hooks is not None:
            hooks.blocked(name, decision.reason)
        else:
            console.print(f"[red]BLOCKERAD[/red] {name} — {decision.reason}")
        return f"[blocked] {decision.reason}"

    if not (decision.risk is RiskLevel.SAFE and auto_approve_safe):
        if noninteractive:
            _log_tool(name, decision.risk.value, "declined", 0)
            reason = f"{decision.risk} kräver godkännande"
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
            _log_tool(name, decision.risk.value, "declined", 0)
            if hooks is not None:
                hooks.declined(name, "nekad av användare")
            else:
                console.print("[dim]nekad av användare[/dim]")
            return "[declined by user]"
        _log_tool(name, decision.risk.value, "approved", 0)
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
                _SESSION_ALLOWLIST.add(name)

    if hooks is not None:
        hooks.tool_start(name, args)
    result = registry.call(name, args)
    # Trunkera stora tool-resultat innan de hamnar i context window.
    MAX_TOOL_OUTPUT = 50_000  # ~12K tokens
    if len(result) > MAX_TOOL_OUTPUT:
        result = result[:MAX_TOOL_OUTPUT] + "\n[TRUNCATED — output oversteg 50KB]"
    success = 0 if result.startswith("[error]") else 1
    _log_tool(name, decision.risk.value, "ran", success)
    shown = result if len(result) <= 120 else result[:120] + "…"
    if hooks is not None:
        hooks.tool_result(name, shown)
    else:
        console.print(f"[dim]tool {name} -> {shown}[/dim]")
    return result


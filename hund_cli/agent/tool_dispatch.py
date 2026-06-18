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
from .safety import PermissionEngine, RiskLevel


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
) -> str:
    name, args = _parse(tc)
    decision = engine.classify(name, args)

    if decision.risk is RiskLevel.BLOCKED:
        _log_tool(name, decision.risk.value, "blocked", 0)
        console.print(f"[red]BLOCKERAD[/red] {name} — {decision.reason}")
        return f"[blocked] {decision.reason}"

    if not (decision.risk is RiskLevel.SAFE and auto_approve_safe):
        if noninteractive:
            _log_tool(name, decision.risk.value, "declined", 0)
            console.print(f"[yellow]NEKAD[/yellow] (noninteractive) {name} {args}")
            return f"[declined: {decision.risk} kräver godkännande]"
        preview = json.dumps(args, ensure_ascii=False)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        ans = (
            console.input(
                f"[yellow]{decision.risk.upper()}[/yellow] Hund vill köra "
                f"[bold]{name}[/bold] {preview} — tillåt? [j/N] "
            )
            .strip()
            .lower()
        )
        if ans not in {"j", "y", "ja", "yes"}:
            _log_tool(name, decision.risk.value, "declined", 0)
            console.print("[dim]nekad av användare[/dim]")
            return "[declined by user]"
        _log_tool(name, decision.risk.value, "approved", 0)

    result = registry.call(name, args)
    success = 0 if result.startswith("[error]") else 1
    _log_tool(name, decision.risk.value, "ran", success)
    shown = result if len(result) <= 120 else result[:120] + "…"
    console.print(f"[dim]tool {name} -> {shown}[/dim]")
    return result


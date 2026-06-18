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

from rich.console import Console

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
        console.print(f"[red]BLOCKERAD[/red] {name} — {decision.reason}")
        return f"[blocked] {decision.reason}"

    if not (decision.risk is RiskLevel.SAFE and auto_approve_safe):
        if noninteractive:
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
            console.print("[dim]nekad av användare[/dim]")
            return "[declined by user]"

    result = registry.call(name, args)
    shown = result if len(result) <= 120 else result[:120] + "…"
    console.print(f"[dim]tool {name} -> {shown}[/dim]")
    return result

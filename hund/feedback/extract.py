"""Extrahera lärdomar från trace-events efter en agent-turn.

Läser trace_events för en session och extraherar fyra typer av lärdomar:
  A. Verktygsfel — tool_call_completed med error i payload
  B. Verifieringsfail — verification_completed med passed=false
  C. Användarkorrigering — user-meddelanden med korrigeringsnyckelord
  D. Framgångsmönster — verification_completed med passed=true efter tidigare fail
"""

from __future__ import annotations

from ..trace.events import list_events_by_session

# Nyckelord som indikerar användarkorrigering
_CORRECTION_KEYWORDS = ["nej", "inte", "istället", "använd"]


def extract_lessons(
    session_id: str,
    run_id: str,
    workspace_id: str,
) -> list[dict]:
    """Extrahera lärdomar från en session baserat på trace-events.

    Returnerar en lista av dicts med format:
      {category, raw_text, confidence, domain, workspace_id}
    """
    try:
        events = list_events_by_session(session_id)
    except Exception:
        return []

    lessons: list[dict] = []

    # Hjälp: hämta domän från workspace_id (fallback: sista komponenten)
    domain = _guess_domain(workspace_id)

    # A. Verktygsfel: tool_call_completed med error i payload
    _extract_tool_errors(events, lessons, domain, workspace_id)

    # B. Verifieringsfail: verification_completed med passed=false
    _extract_verification_fails(events, lessons, domain, workspace_id)

    # C. Användarkorrigering: user-meddelanden med nyckelord
    _extract_user_corrections(events, lessons, domain, workspace_id)

    # D. Framgångsmönster: passed efter tidigare fail i sessionen
    _extract_success_patterns(events, lessons, domain, workspace_id)

    return lessons


def _guess_domain(workspace_id: str) -> str:
    """Gissa domän från workspace-sökvägen."""
    try:
        from pathlib import Path

        return Path(workspace_id).name
    except Exception:
        return "general"


def _extract_tool_errors(
    events, lessons: list[dict], domain: str, workspace_id: str
) -> None:
    """Extrahera lärdomar från verktygsfel."""
    for ev in events:
        if ev.event_type not in ("tool_call_completed", "tool_call_failed"):
            continue
        payload = ev.payload_redacted
        # Leta efter error i payload
        error_text = payload.get("error") or payload.get("stderr") or ""
        if not error_text and not _looks_like_error(payload):
            continue
        if not error_text:
            error_text = str(payload.get("output", "") or "")
        tool = ev.tool_name or payload.get("tool") or "okänt verktyg"
        snippet = str(error_text)[:200]
        lessons.append(
            {
                "category": "tool_error",
                "raw_text": f"{tool}: {snippet}",
                "confidence": 0.7,
                "domain": domain,
                "workspace_id": workspace_id,
            }
        )


def _looks_like_error(payload: dict) -> bool:
    """Heuristik: indikerar payload ett fel?"""
    text = str(payload.get("output", "") or payload.get("text", "") or "")
    low = text.lower()
    for marker in ("error", "traceback", "exception", "failed", "cannot", "not found"):
        if marker in low:
            return True
    return False


def _extract_verification_fails(
    events, lessons: list[dict], domain: str, workspace_id: str
) -> None:
    """Extrahera lärdomar från misslyckade verifieringar."""
    for ev in events:
        if ev.event_type != "verification_completed":
            continue
        payload = ev.payload_redacted
        passed = payload.get("passed", True)
        if passed is not False:
            continue
        kind = payload.get("verification_kind") or payload.get("kind") or "verifiering"
        cmd = payload.get("command") or ""
        exit_code = payload.get("exit_code", "?")
        raw = f"{kind}: \"{cmd}\" (exit {exit_code})"
        lessons.append(
            {
                "category": "verify_fail",
                "raw_text": raw[:300],
                "confidence": 0.6,
                "domain": domain,
                "workspace_id": workspace_id,
            }
        )


def _extract_user_corrections(
    events, lessons: list[dict], domain: str, workspace_id: str
) -> None:
    """Extrahera lärdomar från användarkorrigeringar."""
    # Hitta user-events EFTER tool_call_completed med korrigeringsnyckelord
    tool_seen = False
    for ev in events:
        if ev.event_type == "tool_call_completed":
            tool_seen = True
            continue
        if ev.actor == "user" and tool_seen:
            content = str(ev.payload_redacted.get("content", "") or "")
            low = content.lower()
            if any(kw in low for kw in _CORRECTION_KEYWORDS):
                snippet = content[:200]
                lessons.append(
                    {
                        "category": "user_correction",
                        "raw_text": snippet,
                        "confidence": 0.9,
                        "domain": domain,
                        "workspace_id": workspace_id,
                    }
                )
            tool_seen = False


def _extract_success_patterns(
    events, lessons: list[dict], domain: str, workspace_id: str
) -> None:
    """Extrahera lärdomar från lyckade verifieringar efter tidigare fail."""
    # Samla fail-typer först
    failed_kinds: set[str] = set()
    for ev in events:
        if ev.event_type != "verification_completed":
            continue
        payload = ev.payload_redacted
        if payload.get("passed") is False:
            kind = payload.get("verification_kind") or payload.get("kind") or ""
            if kind:
                failed_kinds.add(kind)

    # Hitta success events för tidigare failade typer
    for ev in events:
        if ev.event_type != "verification_completed":
            continue
        payload = ev.payload_redacted
        if payload.get("passed") is not True:
            continue
        kind = payload.get("verification_kind") or payload.get("kind") or ""
        if kind and kind in failed_kinds:
            cmd = payload.get("command") or ""
            lessons.append(
                {
                    "category": "success_pattern",
                    "raw_text": f"{kind} passerade efter tidigare fail: \"{cmd}\"",
                    "confidence": 0.5,
                    "domain": domain,
                    "workspace_id": workspace_id,
                }
            )

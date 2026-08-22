"""Injection trace event emitter — isolated wrapper for prompt injection scanning.

This module bridges the injection scanner (prompt_builder._scan_for_injection_details)
and the trace event system (trace.events.record_event). It is deliberately
separate from both so that:

  1. prompt_builder stays a pure function module (no trace side effects)
  2. trace.events stays a pure persistence layer (no scanning logic)
  3. This module is the single integration point for injection trace emission

Design: best-effort. If trace fails, injection scanning still works.
This module does NOT modify TCB. It is a side-effect wrapper.

Usage by Codex (recommended integration points):
  - prompt_builder.build_system_prompt: after scanning, call emit_from_hits()
  - tool_dispatch.dispatch_tool_call: after tool_call_completed for tool output
"""
from __future__ import annotations

import hashlib
from typing import Any


def emit_injection_events(
    hits: list[dict[str, Any]],
    *,
    workspace_id: str,
    session_id: str,
    run_id: str,
    source: str = "unknown",
    policy_version: str = "1.0.0",
    turn_id: str | None = None,
) -> int:
    """Emit injection_suspected or injection_blocked trace events from scanner hits.

    Args:
        hits: Output from prompt_builder._scan_for_injection_details().
               Each hit has: source, pattern, action_taken, confidence,
               redacted_excerpt_hash.
        workspace_id, session_id, run_id: Trace correlation keys.
        source: Override source label if hits don't carry one.
        policy_version: Current policy version string.
        turn_id: Optional turn correlation.

    Returns:
        Number of events successfully emitted.
    """
    if not hits:
        return 0

    from ..trace.events import record_event

    emitted = 0
    for hit in hits:
        event_type = "injection_blocked" if hit.get("action_taken") == "blocked" else "injection_suspected"
        payload = {
            "source": hit.get("source", source),
            "patterns_matched": [hit["pattern"]] if hit.get("pattern") else [],
            "action_taken": hit.get("action_taken", "warned_only"),
            "confidence": hit.get("confidence", "medium"),
            "redacted_excerpt_hash": hit.get("redacted_excerpt_hash", ""),
        }
        try:
            record_event(
                workspace_id=workspace_id,
                session_id=session_id,
                run_id=run_id,
                turn_id=turn_id,
                actor="system",
                event_type=event_type,
                policy_version=policy_version,
                payload_unredacted=payload,
                risk="blocked" if event_type == "injection_blocked" else "none",
            )
            emitted += 1
        except Exception:
            # Best-effort: trace failure must not break injection scanning.
            pass

    return emitted


def scan_and_emit(
    text: str,
    *,
    source: str,
    workspace_id: str,
    session_id: str,
    run_id: str,
    policy_version: str = "1.0.0",
    turn_id: str | None = None,
) -> int:
    """Scan text for injection patterns and emit trace events.

    Convenience function: scans + emits in one call. Uses the existing
    scanner from prompt_builder. Returns number of events emitted.

    This is the primary integration point for Codex:
      from hund.agent.injection_trace import scan_and_emit
      scan_and_emit(text, source="tool_output", ...)
    """
    try:
        from .prompt_builder import _scan_for_injection_details
    except ImportError:
        return 0

    hits = _scan_for_injection_details(text, source=source)
    return emit_injection_events(
        hits,
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        source=source,
        policy_version=policy_version,
        turn_id=turn_id,
    )

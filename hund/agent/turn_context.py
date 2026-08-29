"""Turn-context composition and typed state resolution for Phase 4.

Composes per-turn dynamic context (task brief, matching capability descriptors,
typed active state, relevant skills, advisory directives) without destabilizing
the session-stable system prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .capability_self_model import CapabilityDescriptor, render_capability_context
from .response_policy import render_advisory_directives
from .task_brief import TaskBrief, TaskType


@dataclass(frozen=True)
class TurnContext:
    """Per-turn dynamic context passed alongside or immediately preceding user turn."""

    task_brief: TaskBrief
    capability_descriptors: tuple[CapabilityDescriptor, ...] = ()
    active_state_summary: Optional[str] = None
    relevant_skills: tuple[str, ...] = ()
    relevant_memory: tuple[str, ...] = ()
    workspace_context: Optional[str] = None
    advisory_directives: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_brief.task_type.value,
            "capability_descriptors_count": len(self.capability_descriptors),
            "has_active_state": bool(self.active_state_summary),
            "relevant_skills_count": len(self.relevant_skills),
            "has_workspace_context": bool(self.workspace_context),
        }


def resolve_typed_state(
    capability_id: str,
    *,
    vault: Any = None,
    profile: Any = None,
    session_metrics: Any = None,
) -> str:
    """Resolve current runtime state from typed in-memory providers without tool inspection."""
    clean_id = capability_id.lower().strip()

    if clean_id == "skills":
        if vault is not None:
            try:
                active = vault.get_active_skills()
                if active:
                    names = [f"- {s.name} ({s.scope}, v{getattr(s, 'version', '1.0.0')})" for s in active]
                    return "## Current Active Skills (Typed State)\n" + "\n".join(names)
                return "## Current Active Skills (Typed State)\nNo domain skills currently equipped."
            except Exception:
                pass
        return "## Current Active Skills (Typed State)\nConstitutional motor skills active."

    if clean_id in ("system", "hardware"):
        if profile is not None:
            try:
                return f"## Host Hardware Snapshot (Typed State)\n- CPU: {profile.processor} ({profile.cpu_count} cores)\n- GPU: {profile.gpu_model}\n- RAM: {profile.total_ram_gb:.1f}GB\n- OS: {profile.os_caption or profile.os}"
            except Exception:
                pass

    if clean_id in ("session", "history"):
        if session_metrics is not None:
            try:
                return f"## Session Metrics (Typed State)\n- Turns: {getattr(session_metrics, 'turn_count', 0)}\n- Total Tokens: {getattr(session_metrics, 'total_tokens', 0)}"
            except Exception:
                pass

    return ""


def compose_turn_context_message(
    turn_context: TurnContext,
    language: str = "sv",
) -> str:
    """Compose the turn-local context block formatted for LLM input."""
    parts: list[str] = []

    # 1. Matching capability descriptors (direct self-knowledge)
    if turn_context.capability_descriptors:
        cap_str = render_capability_context(turn_context.capability_descriptors)
        if cap_str:
            parts.append(cap_str)

    # 2. Active runtime state from typed providers
    if turn_context.active_state_summary:
        parts.append(turn_context.active_state_summary)

    # 3. Relevant domain skills
    if turn_context.relevant_skills:
        parts.append("## Relevant Skills\n" + "\n".join(f"- {s}" for s in turn_context.relevant_skills))

    # 4. Relevant user memory
    if turn_context.relevant_memory:
        parts.append("## Relevant Memory\n" + "\n".join(f"- {m}" for m in turn_context.relevant_memory))

    # 5. Advisory presentation directives
    advisory = turn_context.advisory_directives or render_advisory_directives(turn_context.task_brief, language=language)
    if advisory:
        parts.append(f"## Response Format Directives\n{advisory}")

    # 6. Workspace context (only if explicitly requested by task brief)
    if turn_context.workspace_context and turn_context.task_brief.needs_workspace_context:
        parts.append(f"## Workspace Context\n{turn_context.workspace_context}")

    return "\n\n".join(parts)

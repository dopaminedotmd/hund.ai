"""Pure responsive renderer and rail formatting for Phase 3 Explicit Skill Authoring.

Implements the Skills & Growth design system across 42, 60, 80, and 120 column geometries.
"""
from __future__ import annotations

import textwrap
from typing import Any, Optional, Sequence

from ..skills.authoring import AuthoringSession, AuthoringState, ShapingQuestion
from ..skills.contracts import PublicationReceipt, QualityGateResult
from .unicode_cells import cell_width, slice_cells, wrap_cells


def _fit(line: str, width: int) -> str:
    return slice_cells(line, max(width, 1))[0] if cell_width(line) > width else line


def render_authoring_stepper(
    view: Any,
    selected_index: int = 0,
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render one transient authoring state with the canonical diamond and rail."""
    width = max(32, width)
    rail = "|" if ascii_only else "│"
    diamond = "#" if ascii_only else "◆"
    end = "`" if ascii_only else "└"
    marker = ">" if ascii_only else "›"
    indent = "  "
    prefix = f"{indent}{rail}  "
    body_width = max(16, width - cell_width(prefix) - 2)

    if view.phase == AuthoringState.READY:
        name = view.skill_name or view.subject
        heading = f"SKILL READY · {name}"
    elif view.phase == AuthoringState.SHAPING:
        heading = f"SKILL AUTHORING · Shaping {view.step_index}/{view.step_total}"
    else:
        heading = f"SKILL AUTHORING · {view.title}"
    lines = [_fit(f"{indent}{diamond}  {heading}", width), f"{indent}{rail}"]

    def add(text: str = "") -> None:
        if not text:
            lines.append(f"{indent}{rail}")
            return
        for part in wrap_cells(text, body_width):
            lines.append(_fit(f"{prefix}{part}", width))

    if view.phase == AuthoringState.READY:
        if view.description:
            add(view.description)
            add()
        if getattr(view, "scope", ""):
            add(f"SCOPE  {view.scope.title()}")
        for limitation in getattr(view, "limitations", ())[:2]:
            add(f"LIMITATION  {limitation}")
        add()
        add("Choose what happens to this verified draft:")
    else:
        add(view.title)
        if getattr(view, "description", ""):
            add()
            add(view.description)
    add()

    if view.options:
        selected = selected_index % len(view.options)
        for index, option in enumerate(view.options):
            focus = marker if index == selected else " "
            add(f"{focus} {option.label}")
    elif view.question_key == "clarification":
        add("Type your answer in the input field.")
    else:
        add("Working...")

    if view.question_key == "clarification":
        controls = "Enter Continue · Esc Back"
    else:
        controls = "Up/Down Select · Enter Confirm · Esc Back" if ascii_only else "↑↓ Select · Enter Confirm · Esc Back"
    lines.append(_fit(f"{indent}{end}  {controls}", width))
    return "\n".join(lines)


def render_publication_receipt(
    receipt: PublicationReceipt,
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render one compact receipt from canonical persisted publication state."""
    width = max(32, width)
    diamond = "#" if ascii_only else "◆"
    rail = "|" if ascii_only else "│"
    end = "`" if ascii_only else "└"
    action = "UPDATED" if receipt.action == "updated" else "CREATED"
    if receipt.scope == "project":
        location = "this project"
    else:
        location = "all projects"
    availability = "Active in" if receipt.vault_state == "equipped" else "Saved for"
    lines = [
        f"  {diamond}  SKILL {action} · {receipt.skill_name}",
        f"  {rail}  {availability} {location} · Version {receipt.artifact_version}",
        f"  {end}  View with /skills",
    ]
    return "\n".join(_fit(line, width) for line in lines)


def render_authoring_shaping(
    session: AuthoringSession,
    questions: Sequence[ShapingQuestion] = (),
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render the in-flight Shaping card with context summary and max 3 gap questions."""
    width = max(32, width)
    compact = width < 60
    rail = "|" if ascii_only else "│"
    diamond = "<>" if ascii_only else "◇"
    end = "`" if ascii_only else "└"
    indent = "  "
    prefix = f"{indent}{rail}  "
    body_width = max(16, width - cell_width(prefix) - 2)

    lines = [f"{indent}{diamond}  SKILL AUTHORING · Shaping"]

    def add(text: str = "") -> None:
        if not text:
            lines.append(f"{indent}{rail}")
            return
        wrapped = wrap_cells(text, body_width)
        for part in wrapped:
            lines.append(f"{prefix}{part}")

    add(f"Subject    {session.request_subject}")
    add(f"Scope      {session.target_scope.title()}")
    add()

    if questions:
        for idx, q in enumerate(questions[:3], 1):
            add(f"[{idx}] {q.title}")
            for opt_idx, opt in enumerate(q.options, 1):
                add(f"    ({opt_idx}) {opt}")
            add()
    else:
        add("Context is sufficient. Deriving triggers and procedure...")

    action_bar = "[1-3] Choose  [Enter] Accept  [Esc] Cancel" if compact else "[1-3] Select Option     [Enter] Accept Defaults     [Esc] Cancel"
    lines.append(_fit(f"{indent}{end}  {action_bar}", width))
    return "\n".join(_fit(line, width) for line in lines)


def render_authoring_research(
    session: AuthoringSession,
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render the research decision and authorization card."""
    width = max(32, width)
    compact = width < 60
    rail = "|" if ascii_only else "│"
    diamond = "<>" if ascii_only else "◇"
    end = "`" if ascii_only else "└"
    indent = "  "
    prefix = f"{indent}{rail}  "
    body_width = max(16, width - cell_width(prefix) - 2)

    lines = [f"{indent}{diamond}  SKILL AUTHORING · External Research"]

    def add(text: str = "") -> None:
        if not text:
            lines.append(f"{indent}{rail}")
            return
        wrapped = wrap_cells(text, body_width)
        for part in wrapped:
            lines.append(f"{prefix}{part}")

    add(f"Subject    {session.request_subject}")
    add("Reason     External framework or volatile API detected.")
    add()
    add("Allow Hund to perform targeted web search for official docs?")

    action_bar = "[y] Research  [n] Local only  [Esc] Cancel" if compact else "[y] Search documentation     [n] Use existing context only     [Esc] Cancel"
    lines.append(_fit(f"{indent}{end}  {action_bar}", width))
    return "\n".join(_fit(line, width) for line in lines)


def render_authoring_quality(
    session: AuthoringSession,
    gate_result: QualityGateResult,
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render the Quality Gate feedback or rejection repair card."""
    width = max(32, width)
    compact = width < 60
    rail = "|" if ascii_only else "│"
    diamond = "<>" if ascii_only else "◇"
    chk = "v" if ascii_only else "✓"
    cross = "x" if ascii_only else "✗"
    end = "`" if ascii_only else "└"
    indent = "  "
    prefix = f"{indent}{rail}  "
    body_width = max(16, width - cell_width(prefix) - 2)

    status_title = "Quality Check Passed" if gate_result.passed else "Quality Gate Action Required"
    lines = [f"{indent}{diamond}  SKILL AUTHORING · {status_title}"]

    def add(text: str = "") -> None:
        if not text:
            lines.append(f"{indent}{rail}")
            return
        wrapped = wrap_cells(text, body_width)
        for part in wrapped:
            lines.append(f"{prefix}{part}")

    if gate_result.passed:
        add(f"{chk} Triggers defined and specific")
        add(f"{chk} Actionable procedure steps derived")
        add(f"{chk} Deterministic quality checks passed ({len(gate_result.checks)}/{len(gate_result.checks)})")
    else:
        for fail in gate_result.failures:
            add(f"{cross} {fail}")
        add()
        add("Choose an action to resolve these items:")

    action_bar = "[f] Fix  [e] Edit  [d] Decline" if compact else "[f] Fix with Hund     [e] Edit manually     [d] Decline"
    lines.append(_fit(f"{indent}{end}  {action_bar}", width))
    return "\n".join(_fit(line, width) for line in lines)


def render_authoring_ready(
    session: AuthoringSession,
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render the canonical Revision 2 Ready Card with exact single-use actions."""
    width = max(32, width)
    compact = width < 60
    rail = "|" if ascii_only else "│"
    diamond = "#" if ascii_only else "◆"
    bullet = "*" if ascii_only else "·"
    end = "`" if ascii_only else "└"
    indent = "  "
    prefix = f"{indent}{rail}  "
    body_width = max(16, width - cell_width(prefix) - 2)

    draft = session.draft
    skill = draft.skill if draft else None
    name = skill.name if skill else session.request_subject

    lines = [f"{indent}{diamond}  SKILL READY {bullet} [{name}]"]

    def add(text: str = "") -> None:
        if not text:
            lines.append(f"{indent}{rail}")
            return
        wrapped = wrap_cells(text, body_width)
        for part in wrapped:
            lines.append(f"{prefix}{part}")

    if skill:
        add(skill.name.replace("-", " ").title())
        add(skill.when_to_use)
        add()
        add(f"SCOPE        {skill.scope.title()}")
        disp = "Use now (pending publication)" if session.desired_disposition == "equip" else "Save to vault (pending publication)"
        add(f"ACTION       {disp}")
        if session.draft_hash:
            short_hash = session.draft_hash[:16] + "..." if len(session.draft_hash) > 16 else session.draft_hash
            add(f"DRAFT HASH   {short_hash}")
        add()
        add("Triggers:")
        for t in skill.triggers:
            add(f"  {bullet} {t}")
        add()
        add("Procedure:")
        for idx, s in enumerate(skill.steps, 1):
            add(f"  {idx}. {s}")
        add()
        add("Verification:")
        for v in skill.verification:
            add(f"  {chk_symbol(ascii_only)} {v}")
    else:
        add(session.request_subject)

    add()
    if width >= 100:
        action_bar = "[u] Publish & use now     [v] Publish to vault     [e] Edit     [d] Decline     [f] Fix with Hund     [i] Details"
    elif width >= 60:
        action_bar = "[u] Publish & use  [v] Vault  [e] Edit  [d] Decline  [f] Fix  [i] Details"
    else:
        action_bar = "[u] Use now  [v] Vault  [e] Edit  [d] Decline"

    lines.append(_fit(f"{indent}{end}  {action_bar}", width))
    return "\n".join(_fit(line, width) for line in lines)


def chk_symbol(ascii_only: bool) -> str:
    return "v" if ascii_only else "✓"


def render_batch_banner(
    queue_pos: int,
    queue_total: int,
    capability: str,
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render batch queue progress banner [X of N]."""
    diamond = "#" if ascii_only else "◆"
    return f"  {diamond} Authoring Queue [{queue_pos} of {queue_total}] · {capability}"


def render_collision_banner(
    reserved_name: str,
    suggestions: Sequence[str],
    width: int = 80,
    *,
    ascii_only: bool = False,
) -> str:
    """Render constitutional builtin reserved collision notice and safe alternatives."""
    warn = "!" if ascii_only else "⚠"
    lines = [
        f"  {warn} Name Collision with Constitutional Skill · '{reserved_name}'",
        f"     Constitutional motor skills cannot be shadowed.",
    ]
    if suggestions:
        sug_str = "     Suggested alternatives: " + "  ".join(f"[{i+1}] {s}" for i, s in enumerate(suggestions[:3]))
        lines.append(sug_str)
    return "\n".join(lines)

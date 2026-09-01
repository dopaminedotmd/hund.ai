"""Shared tool-specific confirmation policy for both TUI implementations."""
from __future__ import annotations

from typing import Any
import json

from ..agent.types import ConfirmVerdict


_POLICY: dict[str, tuple[tuple[ConfirmVerdict, str], ...]] = {
    "terminal": (
        (ConfirmVerdict.APPROVE_ONCE, "Run once"),
        (ConfirmVerdict.EDIT, "Edit command"),
        (ConfirmVerdict.ALLOW_TURN, "Allow remaining terminal commands this turn"),
        (ConfirmVerdict.ALLOW_SESSION, "Allow this action type for this session"),
        (ConfirmVerdict.DENY, "Deny"),
    ),
    "write_file": (
        (ConfirmVerdict.APPROVE_ONCE, "Write file"),
        (ConfirmVerdict.EDIT, "Edit change"),
        (ConfirmVerdict.DENY, "Deny"),
    ),
    "delete_file": (
        (ConfirmVerdict.APPROVE_ONCE, "Delete file"),
        (ConfirmVerdict.DENY, "Deny"),
    ),
    "execute_code": (
        (ConfirmVerdict.APPROVE_ONCE, "Run code"),
        (ConfirmVerdict.EDIT, "Edit code"),
        (ConfirmVerdict.DENY, "Deny"),
    ),
    "delegate_task": (
        (ConfirmVerdict.APPROVE_ONCE, "Delegate once"),
        (ConfirmVerdict.EDIT, "Edit task"),
        (ConfirmVerdict.DENY, "Deny"),
    ),
    "cronjob": (
        (ConfirmVerdict.APPROVE_ONCE, "Schedule job"),
        (ConfirmVerdict.EDIT, "Edit schedule"),
        (ConfirmVerdict.DENY, "Deny"),
    ),
}

_EDITABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "terminal": ("command",),
    "write_file": ("path", "content"),
    "execute_code": ("code",),
    "delegate_task": ("goal", "task", "context", "max_iterations"),
    "cronjob": ("schedule", "prompt", "name"),
}


def confirmation_options(
    tool_name: str, *, session_allowable: bool = True, turn_allowable: bool = False
) -> tuple[tuple[ConfirmVerdict, str], ...]:
    """Return the canonical choices, in display order, for a tool."""
    options = _POLICY.get(
        tool_name,
        (
            (ConfirmVerdict.APPROVE_ONCE, "Allow once"),
            (ConfirmVerdict.DENY, "Deny"),
        ),
    )
    return tuple(
        option for option in options
        if (option[0] is not ConfirmVerdict.ALLOW_SESSION or session_allowable)
        and (option[0] is not ConfirmVerdict.ALLOW_TURN or turn_allowable)
    )


def editable_fields(tool_name: str) -> tuple[str, ...]:
    """Return the explicitly supported editable argument fields."""
    return _EDITABLE_FIELDS.get(tool_name, ())


def edited_argument_copy(
    tool_name: str, original: dict[str, Any], updates: dict[str, Any]
) -> dict[str, Any]:
    """Copy arguments and apply only fields covered by the tool editor schema."""
    allowed = set(editable_fields(tool_name))
    if not allowed:
        raise ValueError(f"No safe editor schema for tool '{tool_name}'")
    result = dict(original)
    result.update({key: value for key, value in updates.items() if key in allowed})
    return result


def prompt_edits(request: Any, input_fn: Any = input) -> dict[str, Any] | None:
    """Prompt for fields in a tool's explicit editor schema; cancellation denies."""
    fields = editable_fields(request.tool_name)
    if not fields:
        return None
    updates: dict[str, Any] = {}
    try:
        for name in fields:
            current = request.args.get(name, "")
            shown = current if isinstance(current, str) else json.dumps(current, ensure_ascii=False)
            value = input_fn(f"{name} [{shown}]: ")
            if value.strip() == ":cancel":
                return None
            if value != "":
                updates[name] = value
    except (EOFError, KeyboardInterrupt):
        return None
    return edited_argument_copy(request.tool_name, request.args, updates)

"""Shared types for the agent layer.

Defines the structured confirmation protocol used between tool_dispatch (TCB)
and all UI sink implementations. Types live here — outside TCB files — so that
UI code can import them without depending on tool_dispatch directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConfirmVerdict(str, Enum):
    """Verdict returned by a confirm() implementation."""

    APPROVE_ONCE = "approve_once"
    ALLOW_SESSION = "allow_session"
    EDIT = "edit"
    DENY = "deny"


@dataclass(frozen=True)
class ConfirmRequest:
    """Structured confirmation payload sent to UI sinks.

    tool_name:  the tool being invoked (e.g. "terminal", "write_file")
    args:       the raw arguments dict for the tool call
    risk:       risk level string from PermissionEngine (e.g. "confirm", "dangerous")
    """

    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    risk: str = "confirm"


@dataclass(frozen=True)
class ConfirmResponse:
    """Structured confirmation result returned by UI sinks."""

    verdict: ConfirmVerdict
    edited_args: dict[str, Any] | None = None


def normalize_confirm_response(
    value: ConfirmResponse | ConfirmVerdict | str | None,
) -> ConfirmResponse:
    """Normalize legacy verdict-only sinks to the canonical response type."""
    if isinstance(value, ConfirmResponse):
        return value
    if isinstance(value, ConfirmVerdict):
        return ConfirmResponse(verdict=value)
    try:
        return ConfirmResponse(verdict=ConfirmVerdict(str(value)))
    except (TypeError, ValueError):
        return ConfirmResponse(verdict=ConfirmVerdict.DENY)

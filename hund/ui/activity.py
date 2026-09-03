"""Typed, deterministic tool activity for Hund's quiet TUI rail.

The agent loop supplies observed tool hooks. This module only reduces those
facts into compact UI state; it never invents hidden reasoning or chain of
thought.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import os
from pathlib import Path
import shutil
from typing import Iterable

from ..learning.redactor import redact_text
from .unicode_cells import cell_width, slice_cells


def _fit_width(line: str, width: int) -> str:
    if cell_width(line) <= width:
        return line
    if width <= 1:
        return "…"
    return slice_cells(line, width - 1)[0] + "…"




class ActivityStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    DECLINED = "declined"
    ERROR = "error"


@dataclass(frozen=True)
class ToolActivity:
    event_id: int
    tool_name: str
    group: str
    description: str
    status: ActivityStatus = ActivityStatus.RUNNING
    duration_s: float = 0.0
    detail: str = ""
    required_confirmation: bool = False
    security_relevant: bool | None = None
    attached_diff_lines: tuple[str, ...] | None = None
    attached_error_lines: tuple[str, ...] | None = None
    attached_diff_language: str = ""
    subagent_depth: int = 0
    change_id: int | None = None


@dataclass(frozen=True)
class NarrationActivity:
    text: str
    event_id: int = 0


def activity_group(tool_name: str, *, verification: bool = False) -> str:
    """Map an observed tool to a stable presentation group."""
    if verification:
        return "verification"
    if tool_name == "web_search":
        return "web_search"
    if tool_name in {"web_open", "web_extract", "fetch_web_page", "read_url_content"}:
        return "web_read"
    if tool_name == "read_file":
        return "read"
    if tool_name in {"search_files", "search_code", "grep_search", "find_files"}:
        return "search"
    if tool_name == "session_search":
        return "session_search"
    if tool_name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
        return "edit"
    if tool_name == "terminal":
        return "execution"
    return tool_name


def describe_tool(tool_name: str, args: dict | None = None, *, max_len: int = 45) -> str:
    """Describe only the observable target of a tool call with canonical redaction."""
    args = args or {}

    def sanitize(value: object, fallback: str = "") -> str:
        text = str(value or fallback)
        redacted = redact_text(text).text
        # Presentation helper: convert long absolute workspace path to filename/basename if safe
        if ("\\" in redacted or "/" in redacted) and not redacted.startswith("[REDACTED"):
            try:
                base = Path(redacted).name
                if base:
                    redacted = base
            except Exception:
                pass
        return redacted if len(redacted) <= max_len else redacted[: max_len - 1] + "…"

    if tool_name == "read_file":
        return f"read {sanitize(args.get('path'), 'file')}"
    if tool_name == "search_files":
        pattern = sanitize(args.get("pattern"), "*")
        path = args.get("path")
        if path and path != ".":
            return f"searched {sanitize(path)} for {pattern}"
        return f"searched {pattern}"
    if tool_name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
        return f"modified {sanitize(args.get('path') or args.get('file_path'), 'workspace')}"
    if tool_name == "delete_file":
        return f"deleted {sanitize(args.get('path'), 'file')}"
    if tool_name == "terminal":
        cmd = str(args.get("command", ""))
        try:
            from ..agent.verification import VerificationKind, classify_verification
            if classify_verification(cmd) is not VerificationKind.NONE:
                return "ran targeted tests"
        except Exception:
            pass
        cmd_lines = [l.strip() for l in cmd.splitlines() if l.strip()]
        summary_cmd = cmd_lines[0] if cmd_lines else ""
        if len(cmd_lines) > 1:
            summary_cmd += " …"
        return f"ran {sanitize(summary_cmd, 'command')}"
    if tool_name == "web_search":
        q = sanitize(args.get("query"), "")
        return f"searched the web for {q}" if q else "searched official sources"
    if tool_name in {"web_open", "web_extract", "fetch_web_page", "read_url_content"}:
        url = sanitize(args.get("url"), "")
        return f"read {url}" if url else "read relevant pages"
    if tool_name == "execute_code":
        return "ran python script"
    if tool_name == "delegate_task":
        tasks = args.get("tasks", [])
        n = len(tasks)
        return f"delegated {n} task{'s' if n != 1 else ''}"
    if tool_name == "session_search":
        q = args.get("query")
        return f"searched history for {sanitize(q)}" if q else "searched history"
    if tool_name == "cronjob":
        action = args.get("action", "job")
        target_name = args.get("name", "")
        return f"scheduled {action} {sanitize(target_name)}" if target_name else f"scheduled {action}"
    return f"ran {sanitize(tool_name)}"


class ActivityTimeline:
    """Reduce tool hook events and render a bounded, replaceable activity block."""

    def __init__(self) -> None:
        self._events: list[ToolActivity | NarrationActivity] = []
        self._next_id = 1

    @property
    def events(self) -> tuple[ToolActivity | NarrationActivity, ...]:
        return tuple(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._next_id = 1

    def add_narration(self, text: str) -> int:
        """Record a model narration event chronologically into the activity timeline."""
        if not text or not text.strip():
            return 0
        safe_text = redact_text(text.strip()).text
        if self._events and isinstance(self._events[-1], NarrationActivity):
            event_id = self._events[-1].event_id
            self._events[-1] = NarrationActivity(text=safe_text, event_id=event_id)
            return event_id
        event_id = self._next_id
        self._next_id += 1
        self._events.append(NarrationActivity(text=safe_text, event_id=event_id))
        return event_id

    def start(
        self,
        tool_name: str,
        description: str,
        *,
        group: str | None = None,
        required_confirmation: bool = False,
        security_relevant: bool | None = None,
        subagent_depth: int = 0,
    ) -> int:
        event_id = self._next_id
        self._next_id += 1
        safe_desc = redact_text(description).text
        self._events.append(
            ToolActivity(
                event_id=event_id,
                tool_name=tool_name,
                group=group or activity_group(tool_name),
                description=safe_desc,
                required_confirmation=required_confirmation,
                security_relevant=security_relevant,
                subagent_depth=subagent_depth,
            )
        )
        return event_id

    def mark_confirmation(self, event_id: int) -> None:
        """Mark a specific tool activity as having required user confirmation."""
        for index, event in enumerate(self._events):
            if isinstance(event, ToolActivity) and event.event_id == event_id:
                self._events[index] = replace(event, required_confirmation=True)
                return

    def attach_diff(
        self,
        event_id: int,
        diff_lines: list[str] | tuple[str, ...],
        language: str = "",
        change_id: int | None = None,
    ) -> None:
        """Attach formatted diff lines directly to an existing tool event."""
        for index, event in enumerate(self._events):
            if isinstance(event, ToolActivity) and event.event_id == event_id:
                self._events[index] = replace(
                    event,
                    attached_diff_lines=tuple(diff_lines),
                    attached_diff_language=language,
                    change_id=change_id if change_id is not None else event.change_id,
                )
                return

    def attach_error(
        self,
        event_id: int,
        error_lines: list[str] | tuple[str, ...],
    ) -> None:
        """Attach error lines directly to an existing tool event."""
        for index, event in enumerate(self._events):
            if isinstance(event, ToolActivity) and event.event_id == event_id:
                self._events[index] = replace(
                    event,
                    attached_error_lines=tuple(error_lines),
                )
                return

    def finish(
        self,
        event_id: int,
        status: ActivityStatus,
        *,
        duration_s: float = 0.0,
        detail: str = "",
    ) -> None:
        safe_detail = redact_text(detail).text if detail else ""
        for index, event in enumerate(self._events):
            if isinstance(event, ToolActivity) and event.event_id == event_id:
                # Invariant: An ERROR status cannot be downgraded back to COMPLETE
                new_status = status
                if event.status is ActivityStatus.ERROR and status is ActivityStatus.COMPLETE:
                    new_status = ActivityStatus.ERROR
                self._events[index] = replace(
                    event,
                    status=new_status,
                    duration_s=max(0.0, duration_s),
                    detail=safe_detail or event.detail,
                )
                return

    def render_flow(self, width: int | None = None, *, past_intent: str = "") -> tuple[Any, ...]:
        from .render import format_tool_flow
        available_width = width or max(shutil.get_terminal_size((80, 24)).columns - 1, 1)
        return format_tool_flow(self._events, available_width, past_intent=past_intent)

    def render_lines(self, width: int | None = None, *, past_intent: str = "") -> list[str]:
        flow_rows = self.render_flow(width, past_intent=past_intent)
        return [row.text for row in flow_rows]

    def render(self, width: int | None = None, *, past_intent: str = "") -> str:
        lines = self.render_lines(width, past_intent=past_intent)
        return "\n".join(lines) + ("\n" if lines else "")

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
        return f"ran {sanitize(cmd, 'command')}"
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
        self._events: list[ToolActivity] = []
        self._next_id = 1

    @property
    def events(self) -> tuple[ToolActivity, ...]:
        return tuple(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._next_id = 1

    def start(
        self,
        tool_name: str,
        description: str,
        *,
        group: str | None = None,
        required_confirmation: bool = False,
        security_relevant: bool | None = None,
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
            )
        )
        return event_id

    def mark_confirmation(self, event_id: int) -> None:
        """Mark a specific tool activity as having required user confirmation."""
        for index, event in enumerate(self._events):
            if event.event_id == event_id:
                self._events[index] = replace(event, required_confirmation=True)
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
            if event.event_id == event_id:
                self._events[index] = replace(
                    event,
                    status=status,
                    duration_s=max(0.0, duration_s),
                    detail=safe_detail,
                )
                return

    def render_lines(self, width: int | None = None) -> list[str]:
        if not self._events:
            return []

        # 8-point Fast-Turn Collapse constraint check (TUI Facit §5.7)
        if len(self._events) == 1:
            ev = self._events[0]
            is_readonly = ev.group in {"read", "inspection", "web_read", "search", "web_search"}
            is_safe_complete = ev.status is ActivityStatus.COMPLETE
            is_fast = ev.duration_s <= 0.70
            is_not_verif = ev.group != "verification"
            is_not_error = ev.status not in {ActivityStatus.ERROR, ActivityStatus.BLOCKED, ActivityStatus.DECLINED}
            no_confirm = not ev.required_confirmation
            is_explicitly_not_security = (ev.security_relevant is False)
            no_detail = not ev.detail

            if (
                is_readonly
                and is_safe_complete
                and is_fast
                and is_not_verif
                and is_not_error
                and no_confirm
                and is_explicitly_not_security
                and no_detail
            ):
                dur_str = f"{ev.duration_s:.1f}s" if ev.duration_s > 0 else "0.1s"
                desc = redact_text(ev.description).text
                return [f"  hund {desc}.            {dur_str}"]

        # Presentation-only consecutive event grouping
        raw_items: list[tuple[str, str, float, ActivityStatus, str]] = []
        # (symbol, desc, duration, status, detail)

        i = 0
        n = len(self._events)
        while i < n:
            ev = self._events[i]

            # Group consecutive compatible completed events in "read", "inspection", "search", "web_read", "web_search"
            if (
                ev.status is ActivityStatus.COMPLETE
                and ev.group in {"read", "inspection", "search", "web_read", "web_search"}
            ):
                group_name = ev.group
                group_events = [ev]
                j = i + 1
                while j < n and self._events[j].status is ActivityStatus.COMPLETE and self._events[j].group == group_name:
                    group_events.append(self._events[j])
                    j += 1

                if len(group_events) > 1:
                    tot_dur = sum(e.duration_s for e in group_events)
                    if group_name in {"read", "inspection"}:
                        desc = f"read relevant files    {len(group_events)} files"
                    elif group_name == "search":
                        desc = f"searched workspace     {len(group_events)} queries"
                    elif group_name == "web_search":
                        desc = f"searched official sources    {len(group_events)} queries"
                    elif group_name == "web_read":
                        desc = f"read relevant pages          {len(group_events)} sources"
                    else:
                        desc = f"inspected {len(group_events)} items"
                    raw_items.append(("✓", desc, tot_dur, ActivityStatus.COMPLETE, ""))
                    i = j
                    continue

            symbol = "⟳" if ev.status is ActivityStatus.RUNNING else "✓"
            if ev.status in {ActivityStatus.ERROR, ActivityStatus.BLOCKED, ActivityStatus.DECLINED}:
                symbol = "✗"
            raw_items.append((symbol, ev.description, ev.duration_s, ev.status, ev.detail))
            i += 1

        # Enforce bounded presentation cap (max 8 visible events) while preserving running events
        if len(raw_items) > 8:
            running_items = [it for it in raw_items if it[3] is ActivityStatus.RUNNING]
            completed_items = [it for it in raw_items if it[3] is not ActivityStatus.RUNNING]
            keep_completed_count = max(8 - len(running_items), 1)
            raw_items = completed_items[-keep_completed_count:] + running_items

        lines: list[str] = []
        for symbol, desc, duration, status, detail in raw_items:
            suffix = f" · {duration:.1f}s" if duration > 0 and status is not ActivityStatus.RUNNING else ""
            if detail and status is not ActivityStatus.COMPLETE:
                desc = f"{desc} — {detail}"
            lines.append(f"  ┊ {symbol} {desc}{suffix}")

        # Completion summary capsule
        if self._events and all(ev.status is not ActivityStatus.RUNNING for ev in self._events):
            statuses = {ev.status for ev in self._events}
            total = sum(event.duration_s for event in self._events)
            has_verification = any(ev.group == "verification" for ev in self._events)
            has_edits = any(ev.group == "edit" for ev in self._events)
            has_web = any(ev.group in {"web_search", "web_read"} for ev in self._events)

            if statuses & {ActivityStatus.ERROR, ActivityStatus.BLOCKED, ActivityStatus.DECLINED}:
                lines.append(f"  ╰─ stopped · {total:.1f}s")
            elif has_edits and has_verification:
                lines.append(f"  ╰─ change holds · {total:.1f}s")
            elif has_verification:
                lines.append(f"  ╰─ clean run · {total:.1f}s")
            elif has_web and len(self._events) >= 2:
                lines.append(f"  ╰─ cross-checked · {total:.1f}s")
            elif len(self._events) >= 3:
                lines.append(f"  ╰─ completed · {len(self._events)} steps · {total:.1f}s")

        available_width = width or max(shutil.get_terminal_size((80, 24)).columns - 1, 1)
        return [_fit_width(line, available_width) for line in lines]

    def render(self) -> str:
        lines = self.render_lines()
        return "\n".join(lines) + ("\n" if lines else "")

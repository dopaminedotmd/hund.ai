"""Typed, deterministic tool activity for Hund's quiet TUI rail.

The agent loop supplies observed tool hooks. This module only reduces those
facts into compact UI state; it never invents hidden reasoning or chain of
thought.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


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


def activity_group(tool_name: str, *, verification: bool = False) -> str:
    """Map an observed tool to a stable presentation group."""
    if verification:
        return "verification"
    if tool_name == "web_search":
        return "web_search"
    if tool_name in {"web_open", "web_extract", "fetch_web_page", "read_url_content"}:
        return "web_read"
    if tool_name in {"read_file", "search_files", "session_search"}:
        return "inspection"
    if tool_name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
        return "edit"
    if tool_name == "terminal":
        return "execution"
    return tool_name


def describe_tool(tool_name: str, args: dict | None = None, *, max_len: int = 45) -> str:
    """Describe only the observable target of a tool call."""
    args = args or {}

    def short(value: object, fallback: str = "") -> str:
        text = str(value or fallback)
        return text if len(text) <= max_len else text[: max_len - 1] + "…"

    if tool_name == "read_file":
        return f"read {short(args.get('path'), 'file')}"
    if tool_name == "search_files":
        pattern = short(args.get("pattern"), "*")
        path = args.get("path")
        if path and path != ".":
            return f"searched {short(path)} for {pattern}"
        return f"searched {pattern}"
    if tool_name in {"write_file", "edit_file", "patch", "apply_patch", "replace_file_content"}:
        return f"modified {short(args.get('path') or args.get('file_path'), 'workspace')}"
    if tool_name == "delete_file":
        return f"deleted {short(args.get('path'), 'file')}"
    if tool_name == "terminal":
        cmd = str(args.get("command", ""))
        try:
            from ..agent.verification import VerificationKind, classify_verification
            if classify_verification(cmd) is not VerificationKind.NONE:
                return "ran targeted tests"
        except Exception:
            pass
        return f"ran {short(cmd, 'command')}"
    if tool_name == "web_search":
        q = short(args.get("query"), "")
        return f"searched the web for {q}" if q else "searched official sources"
    if tool_name in {"web_open", "web_extract", "fetch_web_page", "read_url_content"}:
        url = short(args.get("url"), "")
        return f"read {url}" if url else "read relevant pages"
    if tool_name == "execute_code":
        return "ran python script"
    if tool_name == "delegate_task":
        tasks = args.get("tasks", [])
        n = len(tasks)
        return f"delegated {n} task{'s' if n != 1 else ''}"
    if tool_name == "session_search":
        q = args.get("query")
        return f"searched history for {short(q)}" if q else "searched history"
    if tool_name == "cronjob":
        action = args.get("action", "job")
        target_name = args.get("name", "")
        return f"scheduled {action} {short(target_name)}" if target_name else f"scheduled {action}"
    return f"ran {tool_name}"


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

    def start(self, tool_name: str, description: str, *, group: str | None = None) -> int:
        event_id = self._next_id
        self._next_id += 1
        self._events.append(
            ToolActivity(
                event_id=event_id,
                tool_name=tool_name,
                group=group or activity_group(tool_name),
                description=description,
            )
        )
        return event_id

    def finish(
        self,
        event_id: int,
        status: ActivityStatus,
        *,
        duration_s: float = 0.0,
        detail: str = "",
    ) -> None:
        for index, event in enumerate(self._events):
            if event.event_id == event_id:
                self._events[index] = replace(
                    event,
                    status=status,
                    duration_s=max(0.0, duration_s),
                    detail=detail,
                )
                return

    def render_lines(self) -> list[str]:
        lines: list[str] = []
        for event in self._events:
            symbol = "⟳" if event.status is ActivityStatus.RUNNING else "✓"
            if event.status in {ActivityStatus.ERROR, ActivityStatus.BLOCKED, ActivityStatus.DECLINED}:
                symbol = "✗"
            desc = event.description
            duration = event.duration_s
            suffix = f" · {duration:.1f}s" if duration > 0 and event.status is not ActivityStatus.RUNNING else ""
            detail = event.detail
            if detail and event.status is not ActivityStatus.COMPLETE:
                desc = f"{desc} — {detail}"
            lines.append(f"  ┊ {symbol} {desc}{suffix}")

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
        return lines

    def render(self) -> str:
        lines = self.render_lines()
        return "\n".join(lines) + ("\n" if lines else "")

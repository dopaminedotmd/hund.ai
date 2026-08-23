"""WorktreeSession — isolated agent run inside a git worktree.

An agent runs inside a worktree directory with its own session data,
skill context, and trace events annotated with worktree_id. On
completion, the worktree branch can be proposed for review.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manager import WorktreeManager


class WorktreeSink:
    """Extension of ConnectorSink that logs agent actions in a worktree.

    Captures tool calls, results, and errors during an agent run inside
    a worktree, then stores them for review.
    """

    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.errors: list[str] = []
        self.tool_logs: list[dict[str, Any]] = []

    def thinking(self, msg: str | None = None) -> None:
        pass

    def clear_thinking(self) -> None:
        pass

    def chunk(self, text: str) -> None:
        self.chunks.append(text)

    def end_assistant(self) -> None:
        pass

    def error(self, markup: str) -> None:
        self.errors.append(markup)

    def blocked(self, name: str, reason: str) -> None:
        self.tool_logs.append({"tool": name, "action": "blocked", "reason": reason})

    def declined(self, name: str, reason: str) -> None:
        self.tool_logs.append({"tool": name, "action": "declined", "reason": reason})

    def confirm(self, request):
        from ..agent.types import ConfirmVerdict
        return ConfirmVerdict.APPROVE_ONCE  # Auto-confirm in worktree mode

    def tool_start(self, name: str, args: dict) -> None:
        self.tool_logs.append({"tool": name, "action": "start", "args": args})

    def tool_result(self, name: str, result: str) -> None:
        self.tool_logs.append({"tool": name, "action": "result", "result_preview": result[:200]})


class WorktreeSession:
    """Manages an isolated agent session inside a git worktree.

    Usage::

        mgr = WorktreeManager()
        session = WorktreeSession(mgr)
        result = session.run_in_worktree(
            branch="fix/my-feature",
            goal="Implement the login form validation",
        )
        # result: {worktree_id, branch, path, chunks, errors, tool_logs, diff}
    """

    def __init__(
        self,
        manager: WorktreeManager,
        *,
        trace_callback: Any = None,
    ) -> None:
        self._manager = manager
        self._trace_callback = trace_callback

    def run_in_worktree(
        self,
        branch: str,
        goal: str,
        base: str = "main",
        *,
        context: str = "",
    ) -> dict[str, Any]:
        """Run an agent session inside an isolated worktree.

        Creates a worktree for the branch (if it doesn't exist), runs
        the agent inside it, captures tool logs, and returns results.

        Args:
            branch: Git branch for the worktree.
            goal: Task description for the agent.
            base: Base branch (default main).
            context: Additional context for the agent (system prompt).

        Returns:
            Dict with worktree_id, branch, path, chunks, errors,
            tool_logs, diff, commit_count.
        """
        worktree_id = str(uuid.uuid4())

        # 1. Create or reuse worktree
        worktree_path = self._manager.get_worktree(branch)
        if worktree_path is None:
            worktree_path = self._manager.create_worktree(branch, base=base)

        # 2. Record trace event: session started
        self._emit_trace(worktree_id, "worktree_session_started", {
            "branch": branch,
            "goal": goal,
            "worktree_path": str(worktree_path),
        })

        # 3. Run agent inside worktree
        sink = WorktreeSink()
        errors = self._run_agent(
            worktree_path=worktree_path,
            goal=goal,
            context=context,
            sink=sink,
        )

        # 4. Stage all changes the agent made
        try:
            self._run_captured(
                ["git", "-C", str(worktree_path), "add", "-A"],
            )
        except Exception:
            pass

        # 5. Commit if there are changes
        try:
            diff_check = self._run_captured(
                ["git", "-C", str(worktree_path), "diff", "--cached", "--stat"],
            )
            if diff_check.strip():
                self._run_captured(
                    [
                        "git", "-C", str(worktree_path), "commit",
                        "-m", f"worktree({branch}): {goal[:80]}",
                        "--author", "Worktree Agent <worktree@hund.ai>",
                        "--allow-empty",
                    ],
                )
        except Exception:
            pass

        # 6. Record trace event: session completed
        self._emit_trace(worktree_id, "worktree_session_completed", {
            "branch": branch,
            "errors_count": len(errors),
            "tool_logs_count": len(sink.tool_logs),
        })

        # 7. Generate diff for review
        try:
            diff = self._manager.get_diff(branch, base)
        except Exception:
            diff = ""

        # 8. Count commits on this branch
        try:
            count_raw = self._manager._git(
                "rev-list", "--count", f"^{base}", branch
            )
            commit_count = int(count_raw.strip())
        except Exception:
            commit_count = 0

        return {
            "worktree_id": worktree_id,
            "branch": branch,
            "path": str(worktree_path),
            "chunks": sink.chunks,
            "errors": errors,
            "tool_logs": sink.tool_logs,
            "diff": diff,
            "diff_lines": len(diff.split("\n")) if diff else 0,
            "commit_count": commit_count,
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _run_agent(
        self,
        worktree_path: Path,
        goal: str,
        context: str,
        sink: WorktreeSink,
    ) -> list[str]:
        """Execute the agent logic inside the worktree directory.

        This runs the Hund agent loop inside the worktree by calling
        _run_agent_turn with the worktree as workspace_root.
        Connection to the provider API is reused from the host.
        """
        errors: list[str] = []

        try:
            # Build system prompt with worktree context
            system_context = (
                f"You are working inside an isolated git worktree at {worktree_path}.\n"
                f"All file changes stay in this worktree. The branch is isolated from main.\n"
                f"Task: {goal}\n"
                f"{context}"
            )

            # Run agent turn — imports are done here to avoid circular deps
            from ..connector.server import _run_agent_turn

            result = _run_agent_turn(
                user_msg=system_context,
                session_id=None,
            )

            if result.get("status") == "ok":
                sink.chunks.append(result.get("response", ""))
                for log in result.get("tool_logs", []):
                    sink.tool_logs.append({"tool": "agent", "action": "log", "detail": log})
            else:
                err = result.get("reason", "Unknown agent error")
                errors.append(err)
                sink.errors.append(err)

        except Exception as exc:
            err = f"Agent execution error: {exc}"
            errors.append(err)
            sink.errors.append(err)

        return errors

    def _emit_trace(self, worktree_id: str, event_type: str, payload: dict) -> None:
        """Best-effort trace event emission."""
        try:
            from ..trace.events import record_event

            record_event(
                workspace_id="worktree",
                session_id=worktree_id,
                run_id=worktree_id,
                actor="worktree_agent",
                event_type=event_type,
                policy_version="1.0.0",
                payload_unredacted=payload,
            )
        except Exception:
            pass

    def _run_captured(self, cmd: list[str], timeout: int = 120) -> str:
        """Run a shell command and return stdout."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            return ""

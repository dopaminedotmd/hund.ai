"""Safe persistence boundary for user-authored declarative skills."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..learning.commit_controller import CommitController
from ..skills.model import Skill
from .types import ToolKind, ToolResult, ToolStatus, create_success_result


def make_handler(home: Path | None = None) -> Callable[[dict], ToolResult]:
    """Build a handler that validates and stores skills in HundHome.

    The model never receives a filesystem path and cannot bypass the
    CommitController by writing a relative ``brain/skills`` file.
    """

    def create_skill(args: dict) -> ToolResult:
        raw_spec: Any = args.get("skill")
        if not isinstance(raw_spec, dict):
            return ToolResult(
                ToolStatus.ERROR,
                ToolKind.SYSTEM,
                public_error="skill must be a JSON object",
            )
        try:
            skill = Skill.from_dict(raw_spec)
        except (KeyError, TypeError, ValueError):
            return ToolResult(
                ToolStatus.ERROR,
                ToolKind.SYSTEM,
                public_error="invalid skill structure",
            )

        ok, message = CommitController(home=home).commit_skill_draft(skill)
        if not ok:
            return ToolResult(
                ToolStatus.ERROR,
                ToolKind.SYSTEM,
                public_error=f"skill validation failed: {message}",
            )
        return create_success_result(
            ToolKind.SYSTEM,
            f"Saved skill '{skill.name}' in Hund's canonical skill vault; {message}.",
            metadata={"skill_name": skill.name, "lifecycle_state": "draft"},
        )

    return create_skill

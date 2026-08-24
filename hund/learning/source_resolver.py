"""Pure source-priority and observe-before-assume planning."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


@dataclass(frozen=True)
class ObservationRequest:
    tool_name: str
    args: dict[str, object]
    rationale: str


@dataclass(frozen=True)
class SourceDecision:
    source_type: str
    inspection_target: str = ""
    observations: tuple[ObservationRequest, ...] = ()
    rationale: str = ""


_PATH = re.compile(
    r'(?P<path>(?:[A-Za-z]:[\\/])?[^\s"\x27]+\.(?:py|toml|json|md|yaml|yml|txt|ini))',
    re.IGNORECASE,
)


class SourceResolver:
    PRIORITY = (
        "workspace", "project_history", "user_file",
        "official_web", "general_web", "model_prior",
    )

    def plan(
        self,
        user_message: str,
        workspace_state: Iterable[str] | None = None,
    ) -> SourceDecision:
        known = {str(path).casefold() for path in (workspace_state or ())}
        match = _PATH.search(user_message)
        if match:
            target = match.group("path").rstrip(".,;:")
            exists = target.casefold() in known or Path(target).name.casefold() in {
                Path(path).name.casefold() for path in known
            }
            request = ObservationRequest(
                "read_file" if exists else "search_files",
                {"path": target} if exists else {
                    "path": ".", "pattern": f"**/{Path(target).name}"
                },
                "Verify the user-referenced file in current workspace state.",
            )
            return SourceDecision(
                "workspace", target, (request,),
                "Current workspace evidence outranks memory or web.",
            )
        lower = user_message.casefold()
        if any(term in lower for term in ("latest", "current", "senaste", "deprecated")):
            return SourceDecision(
                "official_web", rationale="Volatile facts require an official current source."
            )
        if any(term in lower for term in ("installed", "installerat", "version", "package", "paket")):
            return SourceDecision(
                "workspace",
                "environment",
                (
                    ObservationRequest(
                        "search_files",
                        {"path": ".", "pattern": "pyproject.toml"},
                        "Locate Python dependency declarations.",
                    ),
                    ObservationRequest(
                        "search_files",
                        {"path": ".", "pattern": "requirements*.txt"},
                        "Locate Python lock or requirements declarations.",
                    ),
                    ObservationRequest(
                        "search_files",
                        {"path": ".", "pattern": "package.json"},
                        "Locate JavaScript dependency declarations.",
                    ),
                ),
                "Installed state must be observed locally.",
            )
        if any(term in lower for term in ("förra gången", "last time", "vi gjorde")):
            return SourceDecision(
                "project_history", rationale="The question explicitly references prior work."
            )
        return SourceDecision("model_prior", rationale="No higher-priority observation cue found.")

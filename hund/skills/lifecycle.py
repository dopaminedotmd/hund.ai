"""Skill Lifecycle Engine — deterministic promotion, sandbox gate, and quarantine.

Adheres strictly to §8 of PLAN_2026-08-24_learning_engine.md:
`draft → schema_valid → sandbox_tested → active → proven`
(→ `deprecated` / `quarantined` / `rolled_back`)

Invariant: Tool-access skills cannot transition to ACTIVE without
passing sandbox dry-run testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Optional

SKILL_STATUS_DRAFT = "draft"
SKILL_STATUS_SCHEMA_VALID = "schema_valid"
SKILL_STATUS_SANDBOX_TESTED = "sandbox_tested"
SKILL_STATUS_ACTIVE = "active"
SKILL_STATUS_PROVEN = "proven"
SKILL_STATUS_DEPRECATED = "deprecated"
SKILL_STATUS_QUARANTINED = "quarantined"
SKILL_STATUS_ROLLED_BACK = "rolled_back"

VALID_SKILL_STATUSES = {
    SKILL_STATUS_DRAFT,
    SKILL_STATUS_SCHEMA_VALID,
    SKILL_STATUS_SANDBOX_TESTED,
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_PROVEN,
    SKILL_STATUS_DEPRECATED,
    SKILL_STATUS_QUARANTINED,
    SKILL_STATUS_ROLLED_BACK,
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    SKILL_STATUS_DRAFT: {SKILL_STATUS_SCHEMA_VALID, SKILL_STATUS_DEPRECATED},
    SKILL_STATUS_SCHEMA_VALID: {
        SKILL_STATUS_SANDBOX_TESTED,
        SKILL_STATUS_ACTIVE,  # only allowed if skill has NO tool access
        SKILL_STATUS_QUARANTINED,
        SKILL_STATUS_DEPRECATED,
    },
    SKILL_STATUS_SANDBOX_TESTED: {
        SKILL_STATUS_ACTIVE,
        SKILL_STATUS_QUARANTINED,
        SKILL_STATUS_DEPRECATED,
    },
    SKILL_STATUS_ACTIVE: {
        SKILL_STATUS_PROVEN,
        SKILL_STATUS_QUARANTINED,
        SKILL_STATUS_DEPRECATED,
        SKILL_STATUS_ROLLED_BACK,
    },
    SKILL_STATUS_PROVEN: {
        SKILL_STATUS_QUARANTINED,
        SKILL_STATUS_DEPRECATED,
        SKILL_STATUS_ROLLED_BACK,
    },
    SKILL_STATUS_QUARANTINED: {
        SKILL_STATUS_DRAFT,
        SKILL_STATUS_DEPRECATED,
        SKILL_STATUS_ROLLED_BACK,
    },
    SKILL_STATUS_DEPRECATED: {SKILL_STATUS_ROLLED_BACK},
    SKILL_STATUS_ROLLED_BACK: set(),
}


@dataclass
class SkillState:
    skill_id: str
    name: str
    version: str = "1.0.0"
    status: str = SKILL_STATUS_DRAFT
    tools: list[str] = field(default_factory=list)
    success_runs: int = 0
    failure_runs: int = 0
    last_error: Optional[str] = None


def validate_skill_schema(skill_data: dict[str, Any]) -> tuple[bool, str]:
    """Validate structural schema of a skill definition."""
    if not isinstance(skill_data, dict):
        return False, "skill definition must be a dictionary"

    name = skill_data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) < 2:
        return False, "skill 'name' is required and must be at least 2 characters"

    version = skill_data.get("version", "1.0.0")
    if not isinstance(version, str):
        return False, "skill 'version' must be a string"

    tools = skill_data.get("required_tools", skill_data.get("tools", []))
    if not isinstance(tools, list):
        return False, "skill 'tools' must be a list of tool names"

    return True, "schema is valid"


def run_skill_sandbox_test(
    skill_data: dict[str, Any],
    dry_run_executor: Optional[Callable[[dict[str, Any]], bool]] = None,
) -> tuple[bool, str]:
    """Run sandbox test / dry-run for a tool-access skill."""
    is_valid, msg = validate_skill_schema(skill_data)
    if not is_valid:
        return False, f"sandbox test failed on schema: {msg}"

    tools = skill_data.get("tools", [])
    if not tools:
        # Pure instruction skill without tools passes sandbox automatically
        return True, "instruction skill passes sandbox without tool execution"

    if dry_run_executor is not None:
        try:
            ok = dry_run_executor(skill_data)
            if not ok:
                return False, "sandbox dry-run executor reported failure"
            return True, "sandbox dry-run executed successfully"
        except Exception as e:
            return False, f"sandbox dry-run crashed with exception: {e}"

    return False, "tool-access skill requires an executing dry-run executor"


def can_transition_skill(
    current_status: str,
    target_status: str,
    has_tools: bool = False,
) -> tuple[bool, str]:
    """Check if skill status transition is permissible under safety invariants."""
    if current_status not in VALID_SKILL_STATUSES:
        return False, f"unknown current status: {current_status}"
    if target_status not in VALID_SKILL_STATUSES:
        return False, f"unknown target status: {target_status}"

    allowed_targets = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        return (
            False,
            f"illegal transition from '{current_status}' to '{target_status}'",
        )

    # Invariant: Tool-access skills cannot bypass sandbox_tested to become active
    if (
        has_tools
        and current_status == SKILL_STATUS_SCHEMA_VALID
        and target_status == SKILL_STATUS_ACTIVE
    ):
        return (
            False,
            "tool-access skill cannot transition from schema_valid to active without sandbox_tested verification",
        )

    return True, f"transition to '{target_status}' allowed"

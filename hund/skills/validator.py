"""Skill validator — ensures declarative skills are structurally complete and secure.

An invalid skill (missing safety/verification, requiring banned actions, invalid schema)
must not be loaded, published, or matched.
"""
from __future__ import annotations

import re
from typing import Any

from .model import BANNED_ACTIONS, SAFETY_LEVELS, STATUSES, Skill

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9._-]+)?$")


def validate(skill: Skill) -> list[str]:
    """Return English validation error messages (empty list = valid)."""
    errors: list[str] = []

    if skill.schema_version != 1:
        errors.append("schema_version must be 1")

    if not _NAME_RE.match(skill.name):
        errors.append(f"invalid name '{skill.name}' (lowercase alphanumeric, underscores, hyphens, 2-64 chars)")

    if skill.status not in STATUSES:
        errors.append(f"unknown status '{skill.status}'")

    if not skill.when_to_use or not skill.when_to_use.strip():
        errors.append("missing when_to_use")

    if not skill.steps:
        errors.append("missing steps")
    else:
        for idx, step in enumerate(skill.steps):
            if not step or not str(step).strip():
                errors.append(f"step {idx} is empty")

    if not skill.triggers:
        errors.append("missing triggers")
    else:
        for idx, trigger in enumerate(skill.triggers):
            if not trigger or not str(trigger).strip():
                errors.append(f"trigger {idx} is empty")

    if skill.safety_level not in SAFETY_LEVELS:
        errors.append(f"unknown safety_level '{skill.safety_level}'")

    if skill.scope not in ("global", "project"):
        errors.append(f"unknown scope '{skill.scope}' (must be 'global' or 'project')")

    if not _VERSION_RE.match(skill.version):
        errors.append(f"invalid version format '{skill.version}' (must be semver e.g. 1.0.0)")

    # Boundaries and verification
    if not skill.forbidden_actions:
        errors.append("missing forbidden_actions (must declare safety boundaries)")
    if not skill.verification:
        errors.append("missing verification (must declare verification steps)")

    # Banned actions
    bad_tools = set(skill.required_tools) & BANNED_ACTIONS
    if bad_tools:
        errors.append(f"required_tools contains banned action: {sorted(bad_tools)}")

    missing_bans = BANNED_ACTIONS - set(skill.forbidden_actions)
    if missing_bans:
        errors.append(f"forbidden_actions MUST include all BANNED_ACTIONS, missing: {sorted(missing_bans)}")

    # Validate source references
    for ref in skill.source_knowledge_refs:
        if not ref.knowledge_id or not str(ref.knowledge_id).strip():
            errors.append("source_knowledge_refs entry missing knowledge_id")
        if not ref.version or not str(ref.version).strip():
            errors.append("source_knowledge_refs entry missing version")

    return errors


def validate_dict(data: dict[str, Any]) -> list[str]:
    """Validate raw dictionary before model deserialization to catch conflicting fields."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["skill definition must be a dictionary"]

    # Reject deprecated/conflicting tools field if present
    if "tools" in data and "required_tools" in data:
        errors.append("conflicting 'tools' and 'required_tools' fields present; use 'required_tools' exclusively")
    elif "tools" in data:
        errors.append("deprecated 'tools' field present; use 'required_tools' exclusively")

    try:
        skill = Skill.from_dict(data)
        errors.extend(validate(skill))
    except Exception as exc:
        errors.append(f"skill deserialization error: {exc}")

    return errors

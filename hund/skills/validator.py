"""Skill-validator — säkerställer att en skill är säker och komplett.

En ogiltig skill (saknar safety/verification, kräver förbjudna handlingar) får
inte laddas eller matchas.
"""
from __future__ import annotations

import re

from .model import BANNED_ACTIONS, SAFETY_LEVELS, STATUSES, Skill

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def validate(skill: Skill) -> list[str]:
    """Returnera felmeddelanden (tom lista = giltig)."""
    errors: list[str] = []

    if skill.schema_version != 1:
        errors.append("schema_version måste vara 1")

    if not _NAME_RE.match(skill.name):
        errors.append(f"ogiltigt name '{skill.name}' (gemener, siffror, _/-)")

    if skill.status not in STATUSES:
        errors.append(f"okänd status '{skill.status}'")

    if not skill.when_to_use:
        errors.append("saknar when_to_use")

    if not skill.steps:
        errors.append("saknar steps")

    if skill.safety_level not in SAFETY_LEVELS:
        errors.append(f"okänd safety_level '{skill.safety_level}'")

    # Kritiskt: en skill måste deklarera gränser och verifiering.
    if not skill.forbidden_actions:
        errors.append("saknar forbidden_actions (måste deklarera gränser)")
    if not skill.verification:
        errors.append("saknar verification (måste deklarera verifiering)")

    # Får ej kräva TCB/förbjudna verktyg (forbidden_actions som listar dem är bra).
    bad_tools = set(skill.required_tools) & BANNED_ACTIONS
    if bad_tools:
        errors.append(f"required_tools innehåller förbjudet: {sorted(bad_tools)}")

    # All BANNED_ACTIONS must be present in forbidden_actions (positive validation).
    missing_bans = BANNED_ACTIONS - set(skill.forbidden_actions)
    if missing_bans:
        errors.append(f"forbidden_actions MUST include all BANNED_ACTIONS, missing: {sorted(missing_bans)}")

    return errors

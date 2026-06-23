"""Loader + validator för runtime policy.

load_policy(): lokal HundHome/policy.json om den finns OCH validerar, annars
default. Vid ogiltig lokal fil faller vi tyst tillbaka till default så Hund
aldrig kör mot en skadad policy.

validate(): struktur + att inga locked default-regler raderats eller låsts upp
i en lokal policy.
"""
from __future__ import annotations

import json
from pathlib import Path

from .defaults import default_policy
from .model import Policy

_VALID_SCOPES = {"prompt", "behavior"}


def policy_path(home: Path | None = None) -> Path:
    """Sökväg till lokal policy.json — brain/policy.json (fas 9.5 Del C)."""
    from ..paths import hund_home

    base = home if home is not None else hund_home()
    return base / "brain" / "policy.json"


def validate(policy: Policy, *, baseline: Policy | None = None) -> list[str]:
    """Returnera lista av felmeddelanden (tom lista = giltig)."""
    errors: list[str] = []

    if policy.version < 1:
        errors.append("version måste vara >= 1")

    ids = [r.id for r in policy.rules]
    if len(ids) != len(set(ids)):
        errors.append("regel-id:n är inte unika")

    for r in policy.rules:
        if not r.id.strip():
            errors.append("regel saknar id")
        if r.scope not in _VALID_SCOPES:
            errors.append(f"regel '{r.id}' har okänd scope '{r.scope}'")
        if not r.text.strip():
            errors.append(f"regel '{r.id}' saknar text")

    base = baseline if baseline is not None else default_policy()
    for br in base.rules:
        if not br.locked:
            continue
        local = policy.rule(br.id)
        if local is None:
            errors.append(f"locked regel '{br.id}' saknas (får ej tas bort)")
        elif not local.locked:
            errors.append(f"regel '{br.id}' avlåst (får ej avlåsas)")
        elif local.text != br.text:
            errors.append(f"locked regel '{br.id}' text ändrad (får ej ändras)")

    return errors


def load_policy(home: Path | None = None) -> Policy:
    """Aktiv policy: lokal om giltig, annars default."""
    p = policy_path(home)
    if p.exists():
        try:
            policy = Policy.from_dict(
                json.loads(p.read_text(encoding="utf-8"))
            )
            if not validate(policy):
                return policy
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    return default_policy()


def load_file(path: Path) -> tuple[Policy | None, list[str]]:
    """Ladda + validera en specifik policyfil. Return (policy, errors)."""
    try:
        policy = Policy.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return None, [f"ogiltig JSON/struktur: {e}"]
    return policy, validate(policy)

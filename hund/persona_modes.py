"""Representation modes for Hund's self-presentation (agyC/3, Spår 11).

ADR-004: identity invariants (third person, canonical logo/colour tokens, no
prompt mechanics) live in hund.md / persona files and are NOT changed here.
This module only offers *modes* as data plus a request→mode selector, so the
agent can vary how it presents the same canonical identity when the user asks
for a style. Opening examples are review candidates for William (copy gate).
"""
from __future__ import annotations

from typing import Any

_REPRESENTATION_MODES: list[dict[str, Any]] = [
    {
        "key": "static",
        "aliases": ("vanlig", "statisk", "standard", "default"),
        "constraint": "Kanonisk självpresentation: rakt på sak, essens + förmågor.",
        "example": "Jag är hund — en lokal AI-assistent byggd för att få saker gjorda på William skrivbord.",
    },
    {
        "key": "technical",
        "aliases": ("teknisk", "tekniskt", "technical", "spec"),
        "constraint": "Teknisk självpresentation: arkitektur, verktyg, gränser — inga metaforer.",
        "example": "Hund är en lokal agent som kör kommandon, läser/skriver filer i workspace och lär sig preferenser i en session-databas.",
    },
    {
        "key": "minimal",
        "aliases": ("minimal", "minimalistisk", "kort", "kortfattad"),
        "constraint": "Minimalistisk: en eller två meningar, inga listor.",
        "example": "Jag är hund — lokalt körande assistent för arbete i din workspace.",
    },
    {
        "key": "poetic",
        "aliases": ("poetisk", "poetiskt", "poetic"),
        "constraint": "Poetisk men mekanikfri: bildspråk om identitet och hjälp — aldrig prompt-detaljer, aldrig emojis.",
        "example": "Hund är den tysta hjälparen i hörnet av din maskin: ser vad du bygger, påminner om vad du glömmer.",
    },
    {
        "key": "interactive",
        "aliases": ("interaktiv", "dialog", "frågande"),
        "constraint": "Interaktiv: kort självpresentation som bjuder in till frågor.",
        "example": "Jag är hund. Fråga mig vad som helst om vad jag kan göra i den här workspacen.",
    },
]


def list_modes() -> list[dict[str, Any]]:
    """All valid representation modes (data for tests/tools)."""
    return [dict(m) for m in _REPRESENTATION_MODES]


def mode_for_request(query: str) -> dict[str, Any]:
    """Pick a representation mode from a user request, defaulting to 'static'.

    Pure + deterministic: lowercased substring match against aliases.
    """
    lowered = (query or "").lower()
    for mode in _REPRESENTATION_MODES:
        for alias in mode["aliases"]:
            if alias in lowered:
                return mode
    return next(m for m in _REPRESENTATION_MODES if m["key"] == "static")


def select_variant(query: str, recent_keys: list[str] | None = None) -> tuple[dict[str, Any], str | None]:
    """Mode + variation hint.

    recent_keys = previously used mode keys (per session). When the user asks
    for variation without a specific style, prefer a mode not recently used.
    Returns (mode, alternate_key) — alternate_key suggests a different valid
    mode when the requested one was just used.
    """
    requested = mode_for_request(query)
    recent = list(recent_keys or [])
    want_variation = any(w in (query or "").lower() for w in ("variera", "variant", "annat sätt", "annorlunda", "again", "another"))
    if not want_variation:
        return requested, None
    alternates = [m for m in _REPRESENTATION_MODES if m["key"] not in recent and m["key"] != requested["key"]]
    if not alternates:
        alternates = [m for m in _REPRESENTATION_MODES if m["key"] != requested["key"]]
    if not alternates:
        return requested, None
    return requested, alternates[0]["key"]

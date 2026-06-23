"""Skill-matcher — poängsätt skills mot fritext, returnera top-K.

Enkel trigger-overlap (inte tung semantik). Endast aktiva skills matchas.
"""
from __future__ import annotations

from .model import Skill


def score(skill: Skill, text: str) -> int:
    low = text.lower()
    return sum(1 for t in skill.triggers if t and t.lower() in low)


def match(skills: list[Skill], text: str, *, top_k: int = 3) -> list[Skill]:
    """Returnera max top_k aktiva skills med ≥1 triggerträff, högst poäng först."""
    scored = [
        (score(s, text), s)
        for s in skills
        if s.status == "active"
    ]
    scored = [(p, s) for p, s in scored if p > 0]
    scored.sort(key=lambda ps: (-ps[0], ps[1].name))
    return [s for _, s in scored[:top_k]]


def summaries(skills: list[Skill], text: str, *, top_k: int = 3) -> list[str]:
    """Kompakta sammanfattningar för prompt-injektion (ej full dump)."""
    return [s.summary() for s in match(skills, text, top_k=top_k)]

"""Skill matcher — score equipped, lifecycle-eligible skills against text."""
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
        if s.lifecycle_state in {"active", "proven"} and s.vault_state == "equipped"
    ]
    scored = [(p, s) for p, s in scored if p > 0]
    scored.sort(key=lambda ps: (-ps[0], ps[1].name))
    return [s for _, s in scored[:top_k]]


def summaries(skills: list[Skill], text: str, *, top_k: int = 3) -> list[str]:
    """Kompakta sammanfattningar för prompt-injektion (ej full dump)."""
    return [s.summary() for s in match(skills, text, top_k=top_k)]


def instructions(skills: list[Skill], text: str, *, top_k: int = 3) -> list[str]:
    """Render structured instruction blocks for turn-local prompt injection."""
    blocks: list[str] = []
    for s in match(skills, text, top_k=top_k):
        lines = [
            f"### Active Skill: {s.name} (Scope: {s.scope}, Version: {s.version})",
            f"When to use: {s.when_to_use}",
        ]
        if s.steps:
            lines.append("Required Procedure Steps:")
            lines.extend(f"  - {st}" for st in s.steps)
        if s.verification:
            lines.append("Verification Criteria:")
            lines.extend(f"  - {v}" for v in s.verification)
        blocks.append("\n".join(lines))
    return blocks

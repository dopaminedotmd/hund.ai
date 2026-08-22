"""Skill v1 — strukturerad instruktion + safety + verification.

Viktigt: en Skill är INTE exekverbar kod. Den är en deklarativ beskrivning av
när och hur Hund ska agera, med inbyggda gränser (forbidden_actions) och
verifiering. Ingen skill får höja permissions eller kringgå PermissionEngine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# safety_level: hur mycket mänsklig bekräftelse ett steg i skillen kräver.
SAFETY_LEVELS = frozenset({"read_only", "confirm", "confirm_for_write"})
STATUSES = frozenset({"active", "draft", "disabled", "deprecated", "vaulted"})

MAX_ACTIVE_SKILLS = 6

# Verktyg/handlingar som en skill ALDRIG får kräva eller tillåta — dessa är TCB.
BANNED_ACTIONS = frozenset(
    {"self_update", "apply_update", "modify_tcb", "elevate_permissions"}
)



@dataclass(frozen=True)
class Skill:
    schema_version: int
    name: str
    domain: str
    status: str
    triggers: tuple[str, ...]
    when_to_use: str
    steps: tuple[str, ...]
    required_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    safety_level: str
    verification: tuple[str, ...]
    examples: tuple[str, ...] = ()

    def summary(self) -> str:
        """Kompakt rad för prompt-injektion (ej full skill-dump)."""
        return f"[{self.name}] ({self.domain}) {self.when_to_use}"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "domain": self.domain,
            "status": self.status,
            "triggers": list(self.triggers),
            "when_to_use": self.when_to_use,
            "steps": list(self.steps),
            "required_tools": list(self.required_tools),
            "forbidden_actions": list(self.forbidden_actions),
            "safety_level": self.safety_level,
            "verification": list(self.verification),
            "examples": list(self.examples),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Skill":
        return cls(
            schema_version=int(d.get("schema_version", 0)),
            name=str(d.get("name", "")).strip(),
            domain=str(d.get("domain", "")).strip(),
            status=str(d.get("status", "draft")).strip(),
            triggers=tuple(str(t) for t in d.get("triggers", [])),
            when_to_use=str(d.get("when_to_use", "")).strip(),
            steps=tuple(str(s) for s in d.get("steps", [])),
            required_tools=tuple(str(t) for t in d.get("required_tools", [])),
            forbidden_actions=tuple(str(a) for a in d.get("forbidden_actions", [])),
            safety_level=str(d.get("safety_level", "")).strip(),
            verification=tuple(str(v) for v in d.get("verification", [])),
            examples=tuple(str(e) for e in d.get("examples", [])),
        )

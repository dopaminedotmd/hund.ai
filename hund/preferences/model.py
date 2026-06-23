"""Preferences — Behavioral vs Contextual, alltid lokal."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Preference:
    key: str
    value: str
    mode: str = "contextual"  # "always" | "behavioral" | "contextual"

@dataclass
class Preferences:
    items: list[Preference] = field(default_factory=list)

    def get_always(self) -> list[Preference]:
        return [p for p in self.items if p.mode == "always"]

    def get_behavioral(self) -> list[Preference]:
        return [p for p in self.items if p.mode in ("always", "behavioral")]

    def get_contextual(self) -> list[Preference]:
        return [p for p in self.items if p.mode in ("always", "contextual")]

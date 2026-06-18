"""Runtime Policy v1 — deklarativt beteendelager (ej core-kod).

Policy styr Hundens beteende via strukturerade regler + forbidden_core_paths,
utan att röra TCB (safety/redactor/updater). Laddas från HundHome om en lokal
fil finns och validerar, annars från default.

Format v1 = JSON, ingen egen DSL (plan §9).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    scope: str            # prompt | behavior
    text: str
    locked: bool = False  # locked regler får ej tas bort/avlåsas av lokal policy


@dataclass(frozen=True)
class Policy:
    version: int
    rules: tuple[Rule, ...]
    forbidden_core_paths: tuple[str, ...] = ()

    def prompt_rules(self) -> list[str]:
        """Text för regler med scope=prompt (injiceras i systemprompt)."""
        return [r.text for r in self.rules if r.scope == "prompt"]

    def rule(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "rules": [
                {
                    "id": r.id,
                    "scope": r.scope,
                    "text": r.text,
                    "locked": r.locked,
                }
                for r in self.rules
            ],
            "forbidden_core_paths": list(self.forbidden_core_paths),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Policy":
        rules = tuple(
            Rule(
                id=str(r["id"]),
                scope=str(r["scope"]),
                text=str(r["text"]),
                locked=bool(r.get("locked", False)),
            )
            for r in data.get("rules", [])
        )
        return cls(
            version=int(data.get("version", 1)),
            rules=rules,
            forbidden_core_paths=tuple(
                str(p) for p in data.get("forbidden_core_paths", [])
            ),
        )

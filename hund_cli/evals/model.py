"""Eval-modell — resultat av ett enskilt eval-case."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    detail: str = ""

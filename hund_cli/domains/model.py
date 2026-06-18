"""Domain-modell — signals + detection, grov confidence (low|medium|high).

Status-flow: candidate -> active -> primary -> stale. Ingen falsk precision:
confidence är ordinal, inte decimal.
"""
from __future__ import annotations

from dataclasses import dataclass

CONFIDENCE_LEVELS = ("low", "medium", "high")
_CONF_RANK = {lvl: i for i, lvl in enumerate(CONFIDENCE_LEVELS)}

# Käll-prioritet vid tiebreak (manual starkast).
_SOURCE_RANK = {"manual": 5, "manifest": 4, "command": 3, "filetype": 2, "cwd": 1}


@dataclass(frozen=True)
class DomainSignal:
    domain: str
    confidence: str   # low|medium|high
    source: str       # cwd|manifest|filetype|manual|command


@dataclass(frozen=True)
class DomainDetection:
    signals: tuple[DomainSignal, ...]

    @property
    def primary(self) -> str:
        if not self.signals:
            return "unknown"
        return max(
            self.signals,
            key=lambda s: (_CONF_RANK.get(s.confidence, 0), _SOURCE_RANK.get(s.source, 0)),
        ).domain

    @property
    def primary_confidence(self) -> str:
        if not self.signals:
            return "low"
        return max(self.signals, key=lambda s: _CONF_RANK.get(s.confidence, 0)).confidence

    @property
    def candidates(self) -> tuple[str, ...]:
        # unika domäner, bevarad ordning
        return tuple(dict.fromkeys(s.domain for s in self.signals))

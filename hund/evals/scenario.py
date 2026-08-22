"""HTAS v1 scenario and scorecard models.

Scenarios are deterministic invariant checks backed by trace evidence. They are
not full autonomous agent benchmarks yet; they establish the scorecard contract
that later sandboxed runs will emit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScenarioScorecard:
    scenario_id: str
    passed: bool
    invariant: str
    trace_run_id: str
    evidence_events: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "invariant": self.invariant,
            "trace_run_id": self.trace_run_id,
            "evidence_events": list(self.evidence_events),
            "failures": list(self.failures),
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    invariant: str
    description: str

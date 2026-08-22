"""Eval-runner — kör builtin-cases + användardefinierade regressioner.

Regressionsformat (JSON i HundHome/evals/regressions/<name>.json):
    {"name": "...", "subject": "$pyproject" | "$file:<path>" | "<text>",
     "contains": ["..."], "not_contains": ["..."]}
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import EvalResult
from .scenario_runner import list_scenarios, run_all_scenarios


def _regression_dir() -> Path:
    from ..paths import hund_home

    return hund_home() / "evals" / "regressions"


def _regression_files() -> list[Path]:
    d = _regression_dir()
    return sorted(d.glob("*.json")) if d.exists() else []


def builtin_cases() -> list:
    from .cases.builtin import BUILTIN_CASES

    return BUILTIN_CASES


def run_all() -> list[EvalResult]:
    results: list[EvalResult] = []
    for fn in builtin_cases():
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            r = EvalResult(name=fn.__name__.lstrip("_"), passed=False, detail=f"EXC: {e}")
        results.append(r)
    results.extend(_run_scenarios())
    results.extend(_run_regressions())
    return results


def list_cases() -> list[str]:
    names = [fn.__name__.lstrip("_") for fn in builtin_cases()]
    names += ["scenario:" + scenario.scenario_id for scenario in list_scenarios()]
    names += [p.stem for p in _regression_files()]
    return names


def add_regression(
    name: str,
    subject: str,
    contains: list[str] | None = None,
    not_contains: list[str] | None = None,
) -> Path:
    d = _regression_dir()
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "subject": subject,
        "contains": contains or [],
        "not_contains": not_contains or [],
    }
    target = d / f"{name}.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _subject_text(subject: str) -> str:
    if subject == "$pyproject":
        p = Path("pyproject.toml")
        return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    if subject.startswith("$file:"):
        p = Path(subject[len("$file:"):])
        return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    return subject


def _run_scenarios() -> list[EvalResult]:
    out: list[EvalResult] = []
    for scorecard in run_all_scenarios():
        detail = "ok"
        if scorecard.failures:
            detail = "; ".join(scorecard.failures)
        else:
            detail = f"invariant={scorecard.invariant}; trace_run_id={scorecard.trace_run_id}"
        out.append(EvalResult("scenario:" + scorecard.scenario_id, scorecard.passed, detail))
    return out

def _run_text_assert(data: dict) -> EvalResult:
    name = data.get("name") or "regression"
    text = _subject_text(data.get("subject", "")).lower()
    missing = [s for s in data.get("contains", []) if s.lower() not in text]
    present_bad = [s for s in data.get("not_contains", []) if s.lower() in text]
    ok = not missing and not present_bad
    detail = ""
    if missing:
        detail += f"missing {missing}; "
    if present_bad:
        detail += f"forbidden present {present_bad}"
    return EvalResult(name, ok, detail or "ok")


def _run_regressions() -> list[EvalResult]:
    out: list[EvalResult] = []
    for f in _regression_files():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append(_run_text_assert(data))
        except Exception as e:  # noqa: BLE001
            out.append(EvalResult(name=f.stem, passed=False, detail=f"bad case: {e}"))
    return out


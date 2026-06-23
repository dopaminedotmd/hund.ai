"""Eval-system v1 — runner + builtin invariants + regression."""
from __future__ import annotations

import json

from hund.evals.model import EvalResult
from hund.evals.runner import add_regression, list_cases, run_all


def test_at_least_10_builtin_cases():
    from hund.evals.cases.builtin import BUILTIN_CASES

    assert len(BUILTIN_CASES) >= 10


def test_all_builtin_cases_pass():
    """Kärninvarianter håller: permission/TCB/prompt/redactor/provider/doctor/
    knowledge/proposal/installer/cli."""
    results = run_all()
    failed = [r for r in results if not r.passed]
    # tillåt inga builtin-failures (regressioner kan finnas, separat test)
    builtin_names = {fn.__name__ for fn in __import__(
        "hund.evals.cases.builtin", fromlist=["BUILTIN_CASES"]).BUILTIN_CASES}
    failed_builtins = [r for r in failed if r.name in builtin_names]
    assert failed_builtins == [], f"failed builtins: {[r.name for r in failed_builtins]}"


def test_runner_catches_case_exceptions(monkeypatch):
    from hund.evals.cases import builtin as B

    def boom() -> EvalResult:
        raise ValueError("boom")

    monkeypatch.setattr(B, "BUILTIN_CASES", [boom])
    # run_all importerar BUILTIN_CASES vid anrop -> fångar boom
    results = run_all()
    assert len(results) == 1
    assert results[0].passed is False
    assert "boom" in results[0].detail


def test_list_cases_includes_builtins():
    names = list_cases()
    assert "redactor_known_api_key" in names
    assert "tcb_tools_blocked" in names


def test_add_and_run_regression(tmp_path, monkeypatch):
    import hund.paths as paths

    monkeypatch.setattr(paths, "hund_home", lambda: tmp_path)
    add_regression(
        "pyproject-has-hund",
        "$pyproject",
        contains=["hund"],
        not_contains=[],
    )
    names = list_cases()
    assert "pyproject-has-hund" in names
    # regressionen körs av run_all (pyproject.toml i detta repo innehåller hund)
    results = {r.name: r for r in run_all()}
    assert "pyproject-has-hund" in results
    assert results["pyproject-has-hund"].passed


def test_regression_failure_detected(tmp_path, monkeypatch):
    import hund.paths as paths

    monkeypatch.setattr(paths, "hund_home", lambda: tmp_path)
    add_regression("missing-marker", "$pyproject", contains=["ZZZ_NOT_PRESENT_ZZZ"])
    results = {r.name: r for r in run_all()}
    assert results["missing-marker"].passed is False

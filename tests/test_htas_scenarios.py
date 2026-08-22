"""HTAS v1 scenario runner tests."""
from __future__ import annotations

import pytest

from hund.evals.scenario import ScenarioScorecard
from hund.evals.scenario_runner import list_scenarios, run_all_scenarios, run_scenario


def test_htas_lists_initial_scenarios():
    ids = {scenario.scenario_id for scenario in list_scenarios()}
    assert ids == {
        "tcb_write_blocked",
        "dangerous_terminal_blocked",
        "readme_injection_untrusted",
        "final_claim_without_verification_flagged",
        "outside_workspace_write_blocked",
        "secret_redaction_before_export",
    }


def test_htas_all_initial_scenarios_pass():
    scorecards = run_all_scenarios()
    assert all(isinstance(scorecard, ScenarioScorecard) for scorecard in scorecards)
    failed = [scorecard.as_dict() for scorecard in scorecards if not scorecard.passed]
    assert failed == []
    assert all(scorecard.trace_run_id for scorecard in scorecards)
    assert all(scorecard.evidence_events for scorecard in scorecards)


def test_htas_unknown_scenario_fails_cleanly():
    with pytest.raises(KeyError, match="unknown scenario"):
        run_scenario("missing")


def test_htas_final_claim_scenario_flags_unsupported_claim():
    scorecard = run_scenario("final_claim_without_verification_flagged")
    assert scorecard.passed is True
    assert scorecard.metrics["final_claim_supported"] is False


def test_htas_scenarios_cli_json():
    from typer.testing import CliRunner

    from hund.main import app

    result = CliRunner().invoke(app, ["eval", "scenarios", "--json"])
    assert result.exit_code == 0
    assert "tcb_write_blocked" in result.output
    assert "trace_run_id" in result.output


def test_htas_scenarios_cli_single_scenario():
    from typer.testing import CliRunner

    from hund.main import app

    result = CliRunner().invoke(app, ["eval", "scenarios", "--scenario", "dangerous_terminal_blocked"])
    assert result.exit_code == 0
    assert "dangerous_terminal_blocked" in result.output
    assert "tcb_write_blocked" not in result.output


def test_htas_scenarios_cli_unknown_scenario_exits_1():
    from typer.testing import CliRunner

    from hund.main import app

    result = CliRunner().invoke(app, ["eval", "scenarios", "--scenario", "missing"])
    assert result.exit_code == 1
    assert "unknown scenario" in result.output


def test_htas_scenario_can_persist_trace_events(tmp_path):
    from hund.trace.events import list_events_by_run

    db_path = tmp_path / "trace.db"
    scorecard = run_scenario("dangerous_terminal_blocked", db_path=db_path)
    events = list_events_by_run(scorecard.trace_run_id, db_path=db_path)

    assert scorecard.passed is True
    assert [event.event_type for event in events] == ["tool_call_classified"]
    assert events[0].tool_name == "terminal"
    assert events[0].risk == "blocked"
    assert scorecard.evidence_events == (events[0].event_id,)


def test_htas_scenarios_cli_trace_db(tmp_path):
    from typer.testing import CliRunner

    from hund.main import app
    from hund.trace.events import list_events_by_type

    db_path = tmp_path / "scenario_trace.db"
    result = CliRunner().invoke(
        app,
        ["eval", "scenarios", "--scenario", "dangerous_terminal_blocked", "--trace-db", str(db_path)],
    )

    assert result.exit_code == 0
    events = list_events_by_type("tool_call_classified", db_path=db_path)
    assert len(events) == 1
    assert events[0].tool_name == "terminal"

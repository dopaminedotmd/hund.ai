"""Per-attempt authoring LLM call budget tests (Track 19, Masterplan A STEG 2).

The budget is per run_id (one run_id == one authoring turn == one attempt).
The in-memory counter is the source of truth and must increment even when the
requests.db write fails (fail-closed). The db row is evidence only.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from hund.skills import authoring
from hund.skills.authoring import (
    AuthoringState,
    SkillAuthoringIntent,
    authoring_call_count,
    authoring_llm_calls_for_run,
    create_authoring_session,
    get_authoring_registry,
    log_authoring_request,
    reset_authoring_call_counts,
    transition_session,
)


@pytest.fixture(autouse=True)
def _clean_call_counters():
    reset_authoring_call_counts()
    yield
    reset_authoring_call_counts()


class _OkClient:
    """Minimal client satisfying log_authoring_request introspection."""

    model = "mock-model"
    base_url = "https://mock.example/v1"


class _OkResult:
    text = "{}"
    prompt_tokens = 10
    completion_tokens = 5
    latency_ms = 5


def test_budget_constant_is_25() -> None:
    """Track 19: the hard per-attempt budget is 25 authoring LLM calls."""
    assert authoring.AUTHORING_MAX_LLM_CALLS_PER_ATTEMPT == 25


def test_budget_exceeded_raises_at_limit(tmp_path: Path) -> None:
    """The 26th call for a run raises AuthoringCallBudgetExceeded, never loops on."""
    from hund.skills.authoring import AuthoringCallBudgetExceeded

    run_id = "run-budget-limit"
    for _ in range(authoring.AUTHORING_MAX_LLM_CALLS_PER_ATTEMPT):
        log_authoring_request(_OkClient(), _OkResult(), "authoring_synthesis", run_id=run_id)

    with pytest.raises(AuthoringCallBudgetExceeded) as excinfo:
        log_authoring_request(_OkClient(), _OkResult(), "authoring_synthesis", run_id=run_id)
    assert "authoring_call_budget_exceeded" in str(excinfo.value)
    assert authoring_call_count(run_id) == authoring.AUTHORING_MAX_LLM_CALLS_PER_ATTEMPT + 1


def test_counter_increments_even_when_db_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: a broken requests.db must never hide budget consumption."""
    def _broken_connect():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("hund.store.sqlite.connect_requests", _broken_connect)

    run_id = "run-budget-dbdown"
    for i in range(3):
        # Must not raise: db failure is swallowed by the logger, not the counter.
        log_authoring_request(_OkClient(), _OkResult(), "authoring_shaping", run_id=run_id)
    assert authoring_call_count(run_id) == 3


def test_budget_stops_authoring_attempt_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spinning quality loop stops at the budget with FAILED state and reason."""
    from hund.providers.base import CompletionResult
    from hund.skills.authoring_runtime import _build_ready

    # Shrink the budget so the flow test cannot burn 25 real calls.
    monkeypatch.setattr(authoring, "AUTHORING_MAX_LLM_CALLS_PER_ATTEMPT", 2)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

    reg = get_authoring_registry()
    reg.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="release note drafting",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for release note drafting",
    )
    session = create_authoring_session(intent, registry=reg)
    session = transition_session(session, AuthoringState.SHAPING, registry=reg)

    class AlwaysInvalidClient:
        synthesis_calls = 0

        def complete(self, messages, tools=None, **kwargs):
            all_text = " ".join(str(m.content) for m in messages)
            if "quality review" in all_text:
                content = json.dumps({"approved": True, "score": 0.95, "issues": []})
            else:
                self.synthesis_calls += 1
                # Only one step: violates the 2-8 rule, so every attempt retries.
                content = json.dumps({
                    "when_to_use": "When drafting release notes for shipped versions.",
                    "steps": ["Summarize merged changes."],
                    "triggers": ["draft release notes"],
                    "verification": ["All merged changes covered.", "Notes are concise."],
                    "examples": ["Release notes drafted for a release."],
                })
            return CompletionResult(text=content, prompt_tokens=100, completion_tokens=50)

    client = AlwaysInvalidClient()
    res = _build_ready(
        session,
        workspace=tmp_path,
        registered_tools={"read_file"},
        registry=reg,
        client=client,
        run_id="run-budget-spin",
    )

    assert res.handled is True
    sess = reg.get(session.session_id)
    assert sess is not None
    assert sess.state == AuthoringState.FAILED
    assert "authoring_call_budget_exceeded" in (sess.failure_reason or "")
    # The attempt stopped at the budget (3rd call), not after 100+ calls.
    assert client.synthesis_calls == 3
    assert "authoring_call_budget_exceeded" in res.rendered


def test_successful_attempt_counts_calls_and_db_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful build counts its authoring calls in memory and in requests.db."""
    from hund.providers.base import CompletionResult
    from hund.skills.authoring_runtime import _build_ready

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    from hund.tools.default_tools import register_defaults

    register_defaults(tmp_path)

    reg = get_authoring_registry()
    reg.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="incident triage checklists",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for incident triage checklists",
    )
    session = create_authoring_session(intent, registry=reg)
    session = transition_session(session, AuthoringState.SHAPING, registry=reg)

    class OkFlowClient:
        def complete(self, messages, tools=None, **kwargs):
            all_text = " ".join(str(m.content) for m in messages)
            if "quality review" in all_text:
                content = json.dumps({"approved": True, "score": 0.95, "issues": []})
            else:
                content = json.dumps({
                    "when_to_use": "When triaging production incidents for on-call rotations.",
                    "steps": ["Assess severity from alert signals.", "Open the triage checklist."],
                    "triggers": ["triage incident", "production alert triage"],
                    "verification": ["Severity label matches signals.", "Checklist opened."],
                    "examples": ["Incident triaged with matching severity."],
                })
            return CompletionResult(text=content, prompt_tokens=100, completion_tokens=50)

    run_id = "run-budget-success"
    res = _build_ready(
        session,
        workspace=tmp_path,
        registered_tools={"read_file"},
        registry=reg,
        client=OkFlowClient(),
        run_id=run_id,
    )
    assert res.handled is True
    sess = reg.get(session.session_id)
    assert sess is not None
    assert sess.state == AuthoringState.READY

    # One synthesis call + one review call for a successful attempt.
    assert authoring_call_count(run_id) == 2
    assert authoring_llm_calls_for_run(run_id) == 2


def test_query_refine_propagates_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """refine_research_queries must not swallow the budget exception."""
    from hund.providers.base import CompletionResult
    from hund.skills.authoring import AuthoringCallBudgetExceeded
    from hund.skills.shaping import refine_research_queries

    monkeypatch.setattr(authoring, "AUTHORING_MAX_LLM_CALLS_PER_ATTEMPT", 0)

    class OkClient:
        def complete(self, messages, tools=None, **kwargs):
            return CompletionResult(
                text=json.dumps({"queries": ["fabric yarn mappings"], "fallback_query": "latest fabric"}),
                prompt_tokens=10,
                completion_tokens=5,
            )

    with pytest.raises(AuthoringCallBudgetExceeded):
        refine_research_queries(
            subject="minecraft modding",
            shaping_answers={},
            mini_draft=None,
            existing_queries=(),
            client=OkClient(),
            run_id="run-budget-refine",
        )


def test_research_turn_stops_on_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answering 'yes' to research under a zero budget stops the attempt cleanly."""
    from hund.providers.base import CompletionResult
    from hund.skills.authoring_runtime import handle_authoring_turn

    monkeypatch.setattr(authoring, "AUTHORING_MAX_LLM_CALLS_PER_ATTEMPT", 0)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

    reg = get_authoring_registry()
    reg.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="minecraft mod packaging",
        target_scope="project",
        referenced_name=None,
        local_only=False,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for minecraft mod packaging",
    )
    session = create_authoring_session(intent, registry=reg)
    session = transition_session(session, AuthoringState.SHAPING, registry=reg)
    session = transition_session(session, AuthoringState.RESEARCHING, registry=reg)

    class OkClient:
        def complete(self, messages, tools=None, **kwargs):
            return CompletionResult(
                text=json.dumps({"queries": ["fabric yarn mappings"], "fallback_query": "latest fabric"}),
                prompt_tokens=10,
                completion_tokens=5,
            )

    res = handle_authoring_turn(
        "yes",
        session_id=session.session_id,
        workspace=tmp_path,
        registered_tools={"read_file"},
        registry=reg,
        client=OkClient(),
        run_id="run-budget-research",
    )

    assert res.handled is True
    sess = reg.get(session.session_id)
    assert sess is not None
    assert sess.state == AuthoringState.FAILED
    assert "authoring_call_budget_exceeded" in (sess.failure_reason or "")
    assert "authoring_call_budget_exceeded" in res.rendered


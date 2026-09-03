"""RED/GREEN tests for Gate 2 Task 3: Quality Loop, LLM Review Gate & Lineage."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from hund.providers.base import CompletionResult
from hund.skills.authoring import (
    AuthoringSession,
    AuthoringState,
    LocalSkillProposal,
    ReviewCallOutput,
    SkillDraft,
    run_deterministic_quality_checks,
    run_llm_review_gate,
)
from hund.skills.authoring_runtime import _build_ready
from hund.skills.factory import SkillFactory
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.scope import ScopeResolution


class _ScriptedQualityClient:
    def __init__(self, synthesis_responses: list[str], review_responses: list[str]):
        self.synthesis_responses = list(synthesis_responses)
        self.review_responses = list(review_responses)
        self.synthesis_calls = []
        self.review_calls = []

    def complete(self, messages, tools=None, **kwargs):
        system_content = messages[0].content if messages else ""
        if "quality review gate" in system_content:
            self.review_calls.append(messages)
            text = self.review_responses.pop(0) if self.review_responses else '{"approved": true, "score": 1.0, "issues": []}'
            return CompletionResult(text=text)
        else:
            self.synthesis_calls.append(messages)
            text = self.synthesis_responses.pop(0) if self.synthesis_responses else "{}"
            return CompletionResult(text=text)


def _valid_skill() -> Skill:
    return Skill(
        schema_version=1,
        name="k8s-pod-triage",
        domain="general",
        status="draft",
        triggers=("crashloop", "pod crash"),
        when_to_use="When diagnosing Kubernetes CrashLoopBackOff pod failures and restarts.",
        steps=(
            "Inspect pod status and recent restart events using kubectl describe.",
            "Fetch previous container logs using kubectl logs --previous.",
            "Analyze exit code and OOMKilled indicators to isolate failure cause.",
        ),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=(
            "Pod logs and termination message confirm root cause exit code.",
            "Diagnostic report specifies whether crash is application panic or OOM.",
        ),
        examples=("CrashLoopBackOff with ExitCode 137 identified as OOMKilled.",),
        lifecycle_state="draft",
        vault_state="vaulted",
        version="1.0.0",
        capability_id="general/k8s-pod-triage",
        scope="project",
    )


def test_deterministic_checks_extended_contracts():
    """RED/GREEN: Deterministic checks enforce triggers, collision, and banned actions."""
    valid_draft = SkillDraft(action="CREATE", skill=_valid_skill())
    res = run_deterministic_quality_checks(valid_draft)
    assert res.passed is True

    # 1. Trigger collision with same-scope skill
    other_skill = Skill(
        schema_version=1,
        name="other-skill",
        domain="general",
        status="active",
        triggers=("crashloop",),  # Collides with valid_draft's "crashloop"
        when_to_use="When inspecting general cluster events.",
        steps=("Step 1.", "Step 2."),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Check 1.", "Check 2."),
        lifecycle_state="active",
        vault_state="vaulted",
        version="1.0.0",
        capability_id="general/other-skill",
        scope="project",
    )
    res_collision = run_deterministic_quality_checks(valid_draft, existing_skills=[other_skill])
    assert res_collision.passed is False
    assert any("collision" in f.lower() for f in res_collision.failures)

    # 2. Missing banned actions
    from dataclasses import replace
    bad_skill = replace(_valid_skill(), forbidden_actions=("delete",))
    res_banned = run_deterministic_quality_checks(SkillDraft(action="CREATE", skill=bad_skill))
    assert res_banned.passed is False
    assert any("banned" in f.lower() for f in res_banned.failures)


def test_llm_review_gate_schema_and_call():
    """RED/GREEN: LLM review gate enforces ReviewCallOutput Pydantic schema."""
    draft = SkillDraft(action="CREATE", skill=_valid_skill())

    client_approved = _ScriptedQualityClient(
        synthesis_responses=[],
        review_responses=['{"approved": true, "score": 0.95, "issues": []}'],
    )
    rev_ok = run_llm_review_gate(draft, client=client_approved)
    assert rev_ok.approved is True
    assert rev_ok.score == 0.95
    assert rev_ok.issues == []

    client_rejected = _ScriptedQualityClient(
        synthesis_responses=[],
        review_responses=['{"approved": false, "score": 0.5, "issues": ["Verification is not binary pass/fail."]}'],
    )
    rev_rej = run_llm_review_gate(draft, client=client_rejected)
    assert rev_rej.approved is False
    assert rev_rej.score == 0.5
    assert len(rev_rej.issues) == 1


def test_llm_review_gate_recovers_from_an_empty_length_limited_response():
    """A reasoning-only first response must not surface as a Pydantic EOF error."""
    class LengthThenJsonClient:
        def __init__(self) -> None:
            self.budgets: list[int | None] = []

        def complete(self, messages, tools=None, **kwargs):
            self.budgets.append(kwargs.get("max_tokens"))
            if len(self.budgets) == 1:
                return CompletionResult(text="", finish_reason="length", completion_tokens=2500)
            return CompletionResult(text='{"approved": true, "score": 0.95, "issues": []}')

    client = LengthThenJsonClient()

    review = run_llm_review_gate(SkillDraft(action="CREATE", skill=_valid_skill()), client=client)

    assert review.approved is True
    assert review.score == 0.95
    assert client.budgets == [2500, 8000]


def test_llm_review_gate_fails_closed_after_an_empty_retry():
    class EmptyReviewClient:
        def complete(self, messages, tools=None, **kwargs):
            return CompletionResult(text="", finish_reason="length", completion_tokens=kwargs["max_tokens"])

    with pytest.raises(ValueError, match="Provider review returned no JSON after retry"):
        run_llm_review_gate(SkillDraft(action="CREATE", skill=_valid_skill()), client=EmptyReviewClient())


def test_quality_loop_redrafts_on_review_rejection_and_succeeds_on_second_attempt(tmp_path: Path):
    """RED/GREEN: Max 3 attempts quality loop redrafts with feedback and recovers."""
    from hund.skills.authoring import AuthoringSessionRegistry, SkillAuthoringIntent, create_authoring_session

    synthesis_attempt1 = json.dumps({
        "when_to_use": "When diagnosing pod crashes in Kubernetes cluster.",
        "steps": ["Look at pods.", "Fix errors."],
        "triggers": ["pod crash", "crashloop"],
        "verification": ["Make sure it works.", "Verify output."],
        "examples": ["Pod crash resolved."],
    })
    review_attempt1 = json.dumps({
        "approved": False,
        "score": 0.55,
        "issues": ["Verification checks are vague and not decidable."],
    })

    synthesis_attempt2 = json.dumps({
        "when_to_use": "When diagnosing Kubernetes CrashLoopBackOff pod failures and restarts.",
        "steps": [
            "Inspect pod status and recent restart events using kubectl describe.",
            "Fetch previous container logs using kubectl logs --previous.",
            "Analyze exit code and OOMKilled indicators to isolate failure cause.",
        ],
        "triggers": ["pod crash", "crashloop"],
        "verification": [
            "Pod logs and termination message confirm root cause exit code.",
            "Diagnostic report specifies whether crash is application panic or OOM.",
        ],
        "examples": ["CrashLoopBackOff with ExitCode 137 identified as OOMKilled."],
    })
    review_attempt2 = json.dumps({
        "approved": True,
        "score": 0.95,
        "issues": [],
    })

    client = _ScriptedQualityClient(
        synthesis_responses=[synthesis_attempt1, synthesis_attempt2],
        review_responses=[review_attempt1, review_attempt2],
    )

    reg = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="k8s pod crash triage",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for k8s pod crash triage",
    )
    session = create_authoring_session(
        intent,
        session_id="loop-test",
        queue_position=1,
        queue_total=1,
        queue_items=(intent,),
        registry=reg,
    )

    result = _build_ready(
        session,
        workspace=tmp_path,
        registered_tools={"read_file"},
        registry=reg,
        width=80,
        ascii_only=False,
        client=client,
        run_id="run_loop_test",
    )

    assert result.view is not None
    assert result.view.phase == AuthoringState.READY
    # Synthesis was called twice (initial + 1 redraft with feedback)
    assert len(client.synthesis_calls) == 2
    # Second synthesis prompt contained gate feedback!
    assert "Verification checks are vague" in client.synthesis_calls[1][1].content
    # Trace lineage event attached
    saved_session = reg.get("loop-test")
    assert saved_session.draft is not None
    assert len(saved_session.draft.skill.created_from_event_ids) > 0


def test_quality_loop_fails_closed_after_three_rejected_attempts(tmp_path: Path):
    """RED/GREEN: Quality loop fails closed after 3 rejected attempts without publishing."""
    from hund.skills.authoring import AuthoringSessionRegistry, SkillAuthoringIntent, create_authoring_session

    synthesis_payload = json.dumps({
        "when_to_use": "When diagnosing pod crashes in Kubernetes cluster.",
        "steps": ["Look at pods.", "Fix errors."],
        "triggers": ["pod crash", "crashloop"],
        "verification": ["Make sure it works.", "Verify output."],
        "examples": ["Pod crash resolved."],
    })
    review_reject = json.dumps({
        "approved": False,
        "score": 0.4,
        "issues": ["Steps are not concrete and actionable."],
    })

    client = _ScriptedQualityClient(
        synthesis_responses=[synthesis_payload, synthesis_payload, synthesis_payload],
        review_responses=[review_reject, review_reject, review_reject],
    )

    reg = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="k8s pod crash triage",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for k8s pod crash triage",
    )
    session = create_authoring_session(
        intent,
        session_id="loop-fail-test",
        queue_position=1,
        queue_total=1,
        queue_items=(intent,),
        registry=reg,
    )

    result = _build_ready(
        session,
        workspace=tmp_path,
        registered_tools={"read_file"},
        registry=reg,
        width=80,
        ascii_only=False,
        client=client,
    )

    assert result.view is not None
    assert result.view.phase == AuthoringState.FAILED
    saved = reg.get("loop-fail-test")
    assert saved.state == AuthoringState.FAILED
    assert "3 attempts" in saved.failure_reason


def test_deterministic_quality_check_fails_on_swedish_canonical_content() -> None:
    from dataclasses import replace
    valid = _valid_skill()
    draft = SkillDraft(
        action="CREATE",
        skill=valid,
    )
    result_valid = run_deterministic_quality_checks(draft)
    assert result_valid.passed is True

    # Test Swedish in when_to_use
    swedish_when = replace(valid, when_to_use="Använd när du vill felsöka kraschande poddar i Kubernetes.")
    draft_swedish_when = replace(draft, skill=swedish_when)
    result_when = run_deterministic_quality_checks(draft_swedish_when)
    assert result_when.passed is False
    assert any("english_canonical_content" == c.name and not c.passed for c in result_when.checks)

    # Test Swedish in steps
    swedish_steps = replace(valid, steps=("Etablera baseline: läs versionsmanifest och inventera.", "Kör kubectl logs."))
    draft_swedish_steps = replace(draft, skill=swedish_steps)
    result_steps = run_deterministic_quality_checks(draft_swedish_steps)
    assert result_steps.passed is False
    assert any("english_canonical_content" == c.name and not c.passed for c in result_steps.checks)


def test_deterministic_quality_check_failure_feedback_in_loop(tmp_path: Path) -> None:
    from hund.skills.authoring import AuthoringSessionRegistry, SkillAuthoringIntent, create_authoring_session

    bad_synthesis = json.dumps({
        "when_to_use": "When diagnosing pod crashes in Kubernetes cluster properly.",
        "steps": ["Etablera baseline: läs versionsmanifest och inventera.", "Kör kubectl logs för att felsöka."],
        "triggers": ["k8s pod crash triage"],
        "verification": ["Check pod status completes with zero.", "Pod logs confirm crash cause."],
        "examples": ["Example crash triage passes."],
    })
    good_synthesis = json.dumps({
        "when_to_use": "When diagnosing pod crashes in Kubernetes cluster properly.",
        "steps": ["Inspect pod status and recent restart events using kubectl.", "Fetch previous container logs using kubectl logs."],
        "triggers": ["k8s pod crash triage"],
        "verification": ["Check pod status completes with zero.", "Pod logs confirm crash cause."],
        "examples": ["Example crash triage passes."],
    })
    review_accept = json.dumps({
        "approved": True,
        "score": 0.95,
        "issues": [],
    })

    client = _ScriptedQualityClient(
        synthesis_responses=[bad_synthesis, good_synthesis],
        review_responses=[review_accept],
    )

    reg = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="k8s pod crash triage",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for k8s pod crash triage",
    )
    session = create_authoring_session(
        intent,
        session_id="det-feedback-test",
        queue_position=1,
        queue_total=1,
        queue_items=(intent,),
        registry=reg,
    )

    result = _build_ready(
        session,
        workspace=tmp_path,
        registered_tools={"read_file"},
        registry=reg,
        width=80,
        ascii_only=False,
        client=client,
        run_id="det-test-run",
    )

    assert result.view is not None
    assert result.view.phase == AuthoringState.READY
    assert len(client.synthesis_calls) == 2
    # Verify the second synthesis call received the deterministic failure in untrusted_data
    second_prompt = client.synthesis_calls[1][1].content
    assert "Canonical skill content must be in English" in second_prompt

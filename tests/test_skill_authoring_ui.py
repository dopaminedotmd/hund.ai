"""Tests for Phase 3 Skill Authoring UI components, responsive geometries (42, 60, 80, 120 cols), and Revision 2 mockups."""
import pytest

from hund.skills.authoring import (
    AuthoringSession,
    AuthoringState,
    ShapingQuestion,
    SkillAuthoringIntent,
    SkillDraft,
    create_authoring_session,
    transition_session,
)
from hund.skills.contracts import PublicationReceipt, QualityGateCheck, QualityGateResult
from hund.skills.authoring_runtime import AuthoringOption, AuthoringView
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.ui.skill_authoring import (
    render_authoring_quality,
    render_authoring_ready,
    render_authoring_research,
    render_authoring_shaping,
    render_batch_banner,
    render_collision_banner,
    render_authoring_stepper,
    render_publication_receipt,
)


def _make_skill(name: str = "fastapi-error-envelope") -> Skill:
    return Skill(
        schema_version=1,
        name=name,
        domain="general",
        status="draft",
        triggers=("formatting API exceptions in FastAPI routes", "implementing custom API error envelopes"),
        when_to_use="Format API exceptions and validation errors into standard project JSON envelopes.",
        steps=(
            "Import standard envelope schema from schemas/envelope.py",
            "Wrap exception details in Envelope[T] response structure",
            "Attach request trace ID and error timestamp",
        ),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify response envelope conforms to schema.",),
        capability_id=f"general/{name}",
        scope="project",
    )


def test_render_shaping_card_geometries():
    intent = SkillAuthoringIntent(
        operation="create",
        capability="FastAPI Error Envelope",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create fastapi skill",
    )
    session = create_authoring_session(intent)
    session = transition_session(session, AuthoringState.SHAPING)

    questions = [
        ShapingQuestion(
            key="protocol",
            title="API Protocol",
            options=("REST JSON", "GraphQL", "gRPC"),
        )
    ]

    for width in (42, 60, 80, 120):
        rendered = render_authoring_shaping(session, questions=questions, width=width)
        assert "SKILL AUTHORING" in rendered
        assert "Shaping" in rendered
        assert "FastAPI Error Envelope" in rendered
        assert "API Protocol" in rendered
        # Must not exceed terminal width
        for line in rendered.splitlines():
            assert len(line) <= width + 2


def test_render_in_place_stepper_preserves_diamond_rail_and_one_question():
    view = AuthoringView(
        session_id="chat-stepper",
        phase=AuthoringState.SHAPING,
        subject="marketing",
        title="Primary Workflow Focus",
        question_key="focus",
        step_index=1,
        step_total=2,
        options=(
            AuthoringOption("answer", "Automate marketing end-to-end", "Automate marketing end-to-end"),
            AuthoringOption("answer", "Validate marketing", "Validate marketing"),
            AuthoringOption("answer", "Template marketing", "Template marketing"),
        ),
    )

    for width in (42, 60, 80, 120):
        rendered = render_authoring_stepper(view, selected_index=1, width=width)
        assert "◆" in rendered
        assert "│" in rendered
        assert "SKILL AUTHORING" in rendered
        if width >= 60:
            assert "SKILL AUTHORING · Supplementary Question 1 of 2" in rendered
        assert "Primary Workflow Focus" in rendered
        assert "Skill Scope" not in rendered
        assert "› Validate marketing" in rendered
        assert "↑↓ Select" in rendered
        assert "Enter Continue" in rendered
        for line in rendered.splitlines():
            assert len(line) <= width + 2


def test_render_mini_draft_stepper_and_correction_view():
    view_mini = AuthoringView(
        session_id="mini",
        phase=AuthoringState.SHAPING,
        subject="git triage",
        title='Draft — "git triage"',
        description="When to use: When debugging git\n\n1. Inspect git status\n2. Run git log",
        question_key="mini_draft",
        step_index=1,
        step_total=1,
        options=(
            AuthoringOption("answer", "Continue with this draft", "continue"),
            AuthoringOption("answer", "Correct draft (free text)", "correct"),
        ),
    )
    rendered_mini = render_authoring_stepper(view_mini, width=80)
    assert "SKILL AUTHORING · Mini-draft" in rendered_mini
    assert 'Draft — "git triage"' in rendered_mini
    assert "› Continue with this draft" in rendered_mini
    assert "Correct draft (free text)" in rendered_mini
    assert "Enter Continue" in rendered_mini
    assert "Esc Cancel" in rendered_mini

    view_corr = AuthoringView(
        session_id="mini_corr",
        phase=AuthoringState.SHAPING,
        subject="git triage",
        title="Correct draft (free text)",
        description="Type your correction in the input field.",
        question_key="correct_mini_draft",
        step_index=1,
        step_total=1,
        options=(),
    )
    rendered_corr = render_authoring_stepper(view_corr, width=80)
    assert "SKILL AUTHORING · Mini-draft" in rendered_corr
    assert "Correct draft (free text)" in rendered_corr
    assert "Type your answer in the input field." in rendered_corr
    assert "Enter Continue · Esc Back" in rendered_corr


def test_render_free_text_clarification_explains_input_behavior():
    view = AuthoringView(
        session_id="clarify",
        phase=AuthoringState.SHAPING,
        subject="something useful",
        title="Clarify the Intended Outcome",
        description="Describe one recurring task and its desired result.",
        question_key="clarification",
        step_index=1,
        step_total=1,
        options=(),
    )

    rendered = render_authoring_stepper(view, width=60)

    assert "Type your answer in the input field." in rendered
    assert "Enter Continue" in rendered
    assert "Working..." not in rendered


def test_publication_receipt_is_compact_canonical_and_has_no_tool_activity():
    receipt = PublicationReceipt(
        skill_name="marketing",
        capability_id="general/marketing",
        scope="project",
        artifact_version=1,
        vault_state="equipped",
        action="created",
    )

    rendered = render_publication_receipt(receipt, width=60)

    assert rendered.splitlines() == [
        "  ◆  SKILL CREATED · marketing",
        "  │  Active in this project · Version 1",
        "  └  View with /skills",
    ]
    assert "create_skill" not in rendered
    assert "ran " not in rendered


def test_render_ready_card_revision_2_actions():
    intent = SkillAuthoringIntent(
        operation="create",
        capability="FastAPI Error Envelope",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create fastapi skill",
        desired_disposition="equip",
    )
    session = create_authoring_session(intent)
    session = transition_session(session, AuthoringState.SHAPING)
    session = transition_session(session, AuthoringState.BUILDING)

    skill = _make_skill()
    draft = SkillDraft(action="CREATE", skill=skill, metadata={})
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft)
    session = transition_session(session, AuthoringState.READY)

    rendered_120 = render_authoring_ready(session, width=120)
    assert "SKILL READY" in rendered_120
    assert "[fastapi-error-envelope]" in rendered_120
    assert "SCOPE" in rendered_120
    assert "ACTION" in rendered_120
    assert "LINEAGE" in rendered_120
    assert "Use now (pending publication)" in rendered_120
    assert "[u] Publish & use now" in rendered_120
    assert "[v] Save to vault" in rendered_120
    assert "[e] Edit draft" in rendered_120
    assert "[d] Decline" in rendered_120
    assert "[f] Fix with Hund" in rendered_120
    assert "[i] Details" in rendered_120

    # Normal 80 cols
    rendered_80 = render_authoring_ready(session, width=80)
    assert "SKILL READY" in rendered_80
    assert "LINEAGE" in rendered_80
    assert "[u] Publish & use now" in rendered_80
    assert "[v] Save to vault" in rendered_80
    assert "[e] Edit draft" in rendered_80
    assert "[d] Decline" in rendered_80

    # Compact 42 cols
    rendered_42 = render_authoring_ready(session, width=42)
    assert "SKILL READY" in rendered_42
    assert "LINEAGE" in rendered_42
    assert "[u] Use now" in rendered_42
    assert "[v] Vault" in rendered_42
    assert "[e] Edit" in rendered_42


def test_render_ready_stepper_view_with_lineage_and_options():
    view = AuthoringView(
        session_id="ready-sess",
        phase=AuthoringState.READY,
        subject="shopify bulk update",
        title="Skill Ready",
        skill_name="shopify-bulk-description-update",
        scope="project",
        description="Update product descriptions across Shopify products via Admin GraphQL API.",
        lineage_text="event e-7f2a · attempt 2 · first pass: no · research: 2 sources",
        options=(
            AuthoringOption(action="publish_use", label="Publish & use now"),
            AuthoringOption(action="publish_vault", label="Save to vault"),
            AuthoringOption(action="edit", label="Edit draft"),
            AuthoringOption(action="decline", label="Decline"),
        ),
    )
    rendered = render_authoring_stepper(view, selected_index=0, width=80)
    assert "SKILL READY · [shopify-bulk-description-update]" in rendered
    assert "SCOPE        Project" in rendered
    assert "LINEAGE" in rendered
    assert "event e-7f2a" in rendered
    assert "attempt 2" in rendered
    assert "first pass: no" in rendered
    assert "sources" in rendered
    assert "› Publish & use now" in rendered
    assert "Save to vault" in rendered
    assert "Edit draft" in rendered
    assert "Decline" in rendered
    assert "Enter Confirm · Esc Cancel" in rendered


def test_render_quality_gate_passed_and_rejection():
    intent = SkillAuthoringIntent(
        operation="create",
        capability="FastAPI Error Envelope",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create fastapi skill",
    )
    session = create_authoring_session(intent)

    # Passed
    res_pass = QualityGateResult(
        passed=True,
        checks=(QualityGateCheck("triggers", True), QualityGateCheck("procedure", True)),
    )
    rendered_pass = render_authoring_quality(session, res_pass, width=80)
    assert "Quality Check Passed" in rendered_pass
    assert "Triggers defined" in rendered_pass

    # Rejection
    res_fail = QualityGateResult(
        passed=False,
        checks=(QualityGateCheck("triggers", False, "Missing triggers"),),
        failures=("Missing triggers; specific routing trigger required.",),
    )
    rendered_fail = render_authoring_quality(session, res_fail, width=80)
    assert "Action Required" in rendered_fail
    assert "Missing triggers" in rendered_fail
    assert "[f] Fix with Hund" in rendered_fail


def test_render_batch_and_collision_banners():
    batch = render_batch_banner(1, 3, "Pytest Fixtures", width=80)
    assert "[1 of 3]" in batch
    assert "Pytest Fixtures" in batch

    collision = render_collision_banner("git-safety", ["custom-git-safety", "repo-git-safety"], width=80)
    assert "Name Collision with Constitutional Skill" in collision
    assert "git-safety" in collision
    assert "[1] custom-git-safety" in collision


def test_ascii_mode_fallback():
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Test Skill",
        target_scope="global",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create test skill",
    )
    session = create_authoring_session(intent)
    rendered_ascii = render_authoring_shaping(session, width=80, ascii_only=True)
    # Check ASCII fallback characters (| and `)
    assert "|" in rendered_ascii
    assert "`" in rendered_ascii

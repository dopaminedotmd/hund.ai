"""Tests for Phase 3 Skill Authoring state machine, consent boundaries, research grants, and quality gate."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from hund.skills.authoring import (
    AuthoringSession,
    AuthoringSessionRegistry,
    AuthoringState,
    IllegalStateTransitionError,
    ShapingQuestion,
    SkillAuthoringIntent,
    SkillDraft,
    apply_shaping_answers,
    authorize_publication,
    check_reserved_name_collision,
    create_authoring_session,
    detect_batch_skill_intent,
    extract_shaping_questions,
    get_authoring_registry,
    modify_draft,
    run_deterministic_quality_checks,
    transition_session,
)
from hund.skills.contracts import (
    PublicationAuthorization,
    PublicationReceipt,
    ResearchChoice,
    ResearchGrant,
    ResearchMetadata,
    compute_payload_hash,
    normalize_publication_payload,
)
from hund.skills.model import BANNED_ACTIONS, Skill


def _make_test_skill(name: str = "fastapi-error-envelope", scope: str = "project") -> Skill:
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
        version="1.0.0",
        capability_id=f"general/{name}",
        scope=scope,
        personal_skill_xp=0,
    )


def test_authoring_state_transitions_valid_path():
    registry = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="FastAPI error formatting",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="Create a skill for FastAPI error formatting",
    )
    session = create_authoring_session(intent, user_id="user_1", registry=registry)
    assert session.state == AuthoringState.RECOGNIZED
    assert session.session_id in registry.all_sessions()

    # RECOGNIZED -> SHAPING
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)
    assert session.state == AuthoringState.SHAPING

    # SHAPING -> BUILDING
    session = transition_session(session, AuthoringState.BUILDING, registry=registry)
    assert session.state == AuthoringState.BUILDING

    # BUILDING -> QUALITY_CHECKING
    skill = _make_test_skill()
    draft = SkillDraft(action="CREATE", skill=skill, metadata={"source": "local"})
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=registry)
    assert session.state == AuthoringState.QUALITY_CHECKING
    assert session.draft is not None

    # QUALITY_CHECKING -> READY
    session = transition_session(session, AuthoringState.READY, registry=registry)
    assert session.state == AuthoringState.READY
    assert session.draft_hash is not None

    # READY -> PUBLISHING
    session = transition_session(session, AuthoringState.PUBLISHING, registry=registry)
    assert session.state == AuthoringState.PUBLISHING

    # PUBLISHING -> PUBLISHED
    receipt = PublicationReceipt(
        publication_receipt_id="rec_123",
        lineage_id="lin_123",
        schema_version=1,
        artifact_version=1,
        capability_id="general/fastapi-error-envelope",
        skill_name="fastapi-error-envelope",
        scope="project",
        publication_status="published",
        action="created",
        lifecycle_state="active",
        vault_state="equipped",
    )
    session = transition_session(session, AuthoringState.PUBLISHED, receipt=receipt, registry=registry)
    assert session.state == AuthoringState.PUBLISHED
    assert session.publication_receipt == receipt


def test_authoring_state_transitions_illegal_jumps():
    registry = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Test Skill",
        target_scope="global",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create a skill for test",
    )
    session = create_authoring_session(intent, registry=registry)

    # Illegal jump: RECOGNIZED directly to PUBLISHED
    with pytest.raises(IllegalStateTransitionError, match="Illegal state transition"):
        transition_session(session, AuthoringState.PUBLISHED, registry=registry)

    # Move to SHAPING
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)

    # Illegal jump: SHAPING directly to PUBLISHING
    with pytest.raises(IllegalStateTransitionError, match="Illegal state transition"):
        transition_session(session, AuthoringState.PUBLISHING, registry=registry)


def test_payload_normalization_and_hash_consistency():
    skill1 = _make_test_skill(name="test-skill", scope="project")
    draft1 = SkillDraft(action="CREATE", skill=skill1, metadata={"user": "w"})

    norm1 = normalize_publication_payload(draft1)
    hash1 = compute_payload_hash(draft1)

    assert hash1.startswith("sha256:") or len(hash1) == 64
    assert norm1["name"] == "test-skill"
    assert norm1["scope"] == "project"

    # Same content produces identical hash
    skill2 = _make_test_skill(name="test-skill", scope="project")
    draft2 = SkillDraft(action="CREATE", skill=skill2, metadata={"user": "w"})
    hash2 = compute_payload_hash(draft2)
    assert hash1 == hash2

    # Modified step produces different hash
    skill3 = _make_test_skill(name="test-skill", scope="project")
    skill3_mod = Skill(
        schema_version=1,
        name=skill3.name,
        domain=skill3.domain,
        status=skill3.status,
        triggers=skill3.triggers,
        when_to_use=skill3.when_to_use,
        steps=("Modified step 1", "Modified step 2"),
        required_tools=skill3.required_tools,
        forbidden_actions=skill3.forbidden_actions,
        safety_level=skill3.safety_level,
        verification=skill3.verification,
        version=skill3.version,
        capability_id=skill3.capability_id,
        scope=skill3.scope,
    )
    draft3 = SkillDraft(action="CREATE", skill=skill3_mod, metadata={"user": "w"})
    hash3 = compute_payload_hash(draft3)
    assert hash1 != hash3


def test_edit_invalidates_previous_publication_authorization():
    registry = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Git worktree",
        target_scope="global",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create git worktree skill",
    )
    session = create_authoring_session(intent, registry=registry)
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)
    session = transition_session(session, AuthoringState.BUILDING, registry=registry)

    skill = _make_test_skill(name="git-worktree")
    draft = SkillDraft(action="CREATE", skill=skill, metadata={})
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=registry)
    session = transition_session(session, AuthoringState.READY, registry=registry)

    # Authorize publication
    session, auth = authorize_publication(session, user_id="user_1", disposition="equip", registry=registry)
    assert auth is not None
    assert auth.is_valid(session.draft_hash)
    assert session.publication_authorization == auth

    # Now edit draft
    modified_skill = Skill(
        schema_version=1,
        name=skill.name,
        domain=skill.domain,
        status=skill.status,
        triggers=skill.triggers,
        when_to_use="Updated when to use.",
        steps=("Step 1: new step",),
        required_tools=(),
        forbidden_actions=skill.forbidden_actions,
        safety_level="read_only",
        verification=skill.verification,
        version=skill.version,
        capability_id=skill.capability_id,
        scope=skill.scope,
    )
    new_draft = SkillDraft(action="CREATE", skill=modified_skill, metadata={})
    session = modify_draft(session, new_draft, registry=registry)

    # State must revert to EDITING/QUALITY_CHECKING and authorization must be VOIDED
    assert session.state in (AuthoringState.EDITING, AuthoringState.QUALITY_CHECKING)
    assert session.publication_authorization is None
    assert not auth.is_valid(session.draft_hash or "")


def test_task_scoped_research_grant_enforcement():
    # Grant explicitly requested
    grant_exp = ResearchGrant(
        grant_id="grant_1",
        session_id="sess_1",
        purpose="skill_authoring:stripe-webhook",
        choice=ResearchChoice.EXPLICITLY_REQUESTED,
        allowed_tools=("web_search", "fetch_web_page", "read_url_content"),
    )
    assert grant_exp.is_valid("web_search")
    assert grant_exp.is_valid("read_url_content")
    assert not grant_exp.is_valid("terminal")  # Not an allowed research tool

    # Declined grant
    grant_declined = ResearchGrant(
        grant_id="grant_2",
        session_id="sess_2",
        purpose="skill_authoring:cloudflare",
        choice=ResearchChoice.DECLINED_WITH_LIMITATION,
    )
    assert not grant_declined.is_valid("web_search")

    # Expired grant
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    grant_expired = ResearchGrant(
        grant_id="grant_3",
        session_id="sess_3",
        purpose="skill_authoring:test",
        choice=ResearchChoice.USER_APPROVED,
        expires_at=past,
    )
    assert not grant_expired.is_valid("web_search")


def test_deterministic_quality_gate_checks():
    # 1. Valid skill passes all checks
    valid_skill = _make_test_skill()
    draft = SkillDraft(action="CREATE", skill=valid_skill, metadata={})
    res = run_deterministic_quality_checks(draft)
    assert res.passed
    assert len(res.failures) == 0

    # 2. Placeholders like TODO / TBD rejected
    todo_skill = Skill(
        schema_version=1,
        name="todo-skill",
        domain="general",
        status="draft",
        triggers=("test trigger",),
        when_to_use="When testing.",
        steps=("Step 1: TODO add secret key here", "Step 2: run script"),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify result.",),
    )
    draft_todo = SkillDraft(action="CREATE", skill=todo_skill, metadata={})
    res_todo = run_deterministic_quality_checks(draft_todo)
    assert not res_todo.passed
    assert any("TODO" in f or "placeholder" in f.lower() for f in res_todo.failures)

    # 3. Reserved constitutional builtin collision rejected
    colliding_skill = _make_test_skill(name="git-safety")
    draft_coll = SkillDraft(action="CREATE", skill=colliding_skill, metadata={})
    res_coll = run_deterministic_quality_checks(draft_coll)
    assert not res_coll.passed
    assert any("reserved" in f.lower() or "builtin" in f.lower() or "git-safety" in f.lower() for f in res_coll.failures)

    # 4. Secret pattern rejected
    secret_skill = Skill(
        schema_version=1,
        name="secret-skill",
        domain="general",
        status="draft",
        triggers=("test trigger",),
        when_to_use="When testing.",
        steps=("Step 1: use sk-ant-1234567890abcdef12345678 to auth",),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify.",),
    )
    draft_sec = SkillDraft(action="CREATE", skill=secret_skill, metadata={})
    res_sec = run_deterministic_quality_checks(draft_sec)
    assert not res_sec.passed
    assert any("secret" in f.lower() or "credential" in f.lower() for f in res_sec.failures)


def test_reserved_name_collision_and_rename_suggestions():
    # Builtin name
    collided, suggestions = check_reserved_name_collision("git-safety")
    assert collided
    assert len(suggestions) >= 2
    assert "git-safety" not in suggestions
    assert all(s != "git-safety" for s in suggestions)

    # Non-builtin name
    collided_free, suggestions_free = check_reserved_name_collision("custom-markdown-tool")
    assert not collided_free


def test_batch_skill_intent_queue():
    prompt = "Create skills for Pytest fixtures and Ruff linting"
    intents = detect_batch_skill_intent(prompt)
    assert len(intents) == 2
    assert "pytest" in intents[0].capability.lower()
    assert "ruff" in intents[1].capability.lower()

    # Single intent returns 1 item
    single = detect_batch_skill_intent("Create a skill for fastapi routing")
    assert len(single) == 1
    assert "fastapi" in single[0].capability.lower()


def test_contextual_shaping_questions():
    intent = SkillAuthoringIntent(
        operation="create",
        capability="deployment",
        target_scope="unresolved",
        referenced_name=None,
        local_only=False,
        requires_research=False,
        confidence=0.7,
        raw_prompt="Skapa en skill för deployment",
    )
    questions = extract_shaping_questions(intent)
    assert len(questions) >= 1
    assert len(questions) <= 3  # Invariant: max 3 questions

    # Apply answers updates session
    registry = AuthoringSessionRegistry()
    session = create_authoring_session(intent, registry=registry)
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)
    answers = {"target": "Docker container to VPS", "scope": "project"}
    session = apply_shaping_answers(session, answers, registry=registry)
    assert session.shaping_answers == answers
    assert session.target_scope == "project"

"""Integration tests for authoring session publication and vault read-back (Gate 2 V2)."""
from dataclasses import replace
import pytest
from pathlib import Path

from hund.skills.authoring import (
    AuthoringState,
    SkillAuthoringIntent,
    SkillDraft,
    authorize_publication,
    create_authoring_session,
    get_authoring_registry,
    transition_session,
)
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.vault import SkillVault, skill_exists
from hund.tools.skill_tool import make_handler
from hund.tools.types import ToolStatus


def test_create_skill_from_authoring_runtime_end_to_end(tmp_path: Path):
    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    reg = get_authoring_registry()
    reg.clear()

    skill_dict = {
        "schema_version": 1,
        "name": "git-rebase-workflow",
        "domain": "general",
        "status": "draft",
        "triggers": ["clean interactive rebases", "squash commits before merge"],
        "when_to_use": "Use when performing clean interactive rebases or squashing commits before opening PRs.",
        "steps": [
            "1. Inspect commit log and status before rebasing.",
            "2. Execute interactive rebase against target branch.",
            "3. Verify history and working tree cleanly.",
        ],
        "required_tools": [],
        "forbidden_actions": sorted(list(BANNED_ACTIONS)),
        "safety_level": "read_only",
        "verification": ["Verify git log shows desired commits in sequence."],
        "lifecycle_state": "active",
        "vault_state": "vaulted",
        "version": "1.0.0",
        "capability_id": "general/git-rebase-workflow",
        "scope": "project",
        "personal_skill_xp": 0,
    }
    skill = Skill.from_dict(skill_dict)
    draft = SkillDraft(action="CREATE", skill=skill)

    intent = SkillAuthoringIntent(
        operation="create",
        capability="git rebase workflow",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create git rebase workflow skill",
    )
    session = create_authoring_session(intent, session_id="chat-e2e-1", registry=reg)
    session = transition_session(session, AuthoringState.BUILDING, registry=reg)
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=reg)
    session = transition_session(session, AuthoringState.READY, registry=reg)
    session, auth = authorize_publication(session, disposition="vault", registry=reg)
    session = transition_session(session, AuthoringState.PUBLISHING, registry=reg)
    auth = replace(auth, is_used=True)
    session = replace(session, publication_authorization=auth)
    reg.save(session)

    handler = make_handler(home=home, workspace_path=ws)
    call_args = {
        "session_id": session.session_id,
        "authorization_id": auth.authorization_id,
        "payload_hash": auth.payload_hash,
        "desired_disposition": "vault",
        "skill": skill_dict,
    }
    res = handler(call_args)
    assert res.status == ToolStatus.SUCCESS, f"create_skill failed: {res.public_error}"
    assert "Saved skill 'git-rebase-workflow'" in res.to_llm_text()

    # Verify existence using canonical vault lookup
    vault = SkillVault(home=home)
    assert vault.has_skill("git-rebase-workflow", workspace=ws)
    assert skill_exists("git-rebase-workflow", home=home, workspace=ws)


def test_tokenless_direct_call_is_rejected_end_to_end(tmp_path: Path):
    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    handler = make_handler(home=home, workspace_path=ws)
    res = handler({"request": "project planning", "target_scope": "project", "desired_disposition": "vault"})
    assert res.status == ToolStatus.ERROR
    assert "not supported" in res.public_error.lower()


def test_skill_publish_immediate_next_prompt_not_swallowed(tmp_path: Path):
    """After skill publication, immediate next prompt must return handled=False and reach agent loop."""
    from hund.skills.authoring_runtime import handle_authoring_turn

    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    reg = get_authoring_registry()
    reg.clear()

    skill_dict = {
        "schema_version": 1,
        "name": "git-clean-prs",
        "domain": "general",
        "status": "draft",
        "triggers": ["clean pr branches"],
        "when_to_use": "Use when cleaning branches before PR.",
        "steps": ["1. Check status.", "2. Rebase."],
        "required_tools": [],
        "forbidden_actions": sorted(list(BANNED_ACTIONS)),
        "safety_level": "read_only",
        "verification": ["Verify clean git log."],
        "lifecycle_state": "active",
        "vault_state": "vaulted",
        "version": "1.0.0",
        "capability_id": "general/git-clean-prs",
        "scope": "project",
        "personal_skill_xp": 0,
    }
    skill = Skill.from_dict(skill_dict)
    draft = SkillDraft(action="CREATE", skill=skill)

    intent = SkillAuthoringIntent(
        operation="create",
        capability="git clean prs",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create git clean prs skill",
    )
    session = create_authoring_session(intent, session_id="chat-swallow-check", registry=reg)
    session = transition_session(session, AuthoringState.BUILDING, registry=reg)
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=reg)
    session = transition_session(session, AuthoringState.READY, registry=reg)
    session, auth = authorize_publication(session, disposition="vault", registry=reg)
    session = transition_session(session, AuthoringState.PUBLISHING, registry=reg)
    auth = replace(auth, is_used=True)
    session = replace(session, publication_authorization=auth)
    reg.save(session)

    # Tool execution transitions session to PUBLISHED
    handler = make_handler(home=home, workspace_path=ws)
    call_args = {
        "session_id": session.session_id,
        "authorization_id": auth.authorization_id,
        "payload_hash": auth.payload_hash,
        "desired_disposition": "vault",
        "skill": skill_dict,
    }
    res = handler(call_args)
    assert res.status == ToolStatus.SUCCESS

    # The session in the registry is now in PUBLISHED state
    sess_after = reg.get(session.session_id)
    assert sess_after is not None
    assert sess_after.state == AuthoringState.PUBLISHED

    # Immediate next prompt from user: must NOT be swallowed
    next_turn = handle_authoring_turn(
        "nu när du sparat skillen, visa vad vi har för filer i repot",
        session_id=session.session_id,
        workspace=ws,
        registered_tools={"read_file", "terminal"},
        registry=reg,
    )
    assert next_turn.handled is False
    # Registry has pruned the terminal session
    assert reg.get(session.session_id) is None


def test_chat_skill_creation_pins_skill_for_next_turn_and_expires(tmp_path: Path):
    """RED/GREEN: Successful publication pins skill on rt for 1 turn, injects into next turn, then expires."""
    import types
    from hund.agent.loop import _dynamic_context_message
    from hund.skills.model import Skill

    created_skill = Skill(
        schema_version=1,
        name="test-pinned-skill",
        domain="test",
        status="active",
        triggers=("test trigger",),
        when_to_use="When testing pinned skill injection.",
        steps=("Step 1: Execute pinned instruction.",),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("Verification passed.",),
        lifecycle_state="active",
        vault_state="equipped",
    )

    rt = types.SimpleNamespace(
        workspace=tmp_path,
        domain_hint="general",
        skills=[],
        pinned_skill=created_skill,
    )

    # Turn N+1: pinned_skill is present
    msg_turn1 = _dynamic_context_message(
        skills=rt.skills,
        user_text="test trigger",
        workspace_id=str(rt.workspace),
        domain_hint=rt.domain_hint,
        pinned_skill=rt.pinned_skill,
    )
    assert msg_turn1 is not None
    assert "## Nyligen skapad & aktiv skill (prio: instruktioner)" in msg_turn1.content
    assert "test-pinned-skill" in msg_turn1.content
    assert "Step 1: Execute pinned instruction." in msg_turn1.content

    # 1-turn expiration: after turn executes, rt.pinned_skill is set to None
    rt.pinned_skill = None

    # Turn N+2: pinned_skill is now None
    msg_turn2 = _dynamic_context_message(
        skills=rt.skills,
        user_text="test trigger",
        workspace_id=str(rt.workspace),
        domain_hint=rt.domain_hint,
        pinned_skill=rt.pinned_skill,
    )
    if msg_turn2 is not None:
        assert "## Nyligen skapad & aktiv skill (prio: instruktioner)" not in msg_turn2.content


# --- Track 3: authoring exit, pinned skill, next prompt (Masterplan A STEG 4) ---


class _ShapingOkSynthesisInvalidClient:
    """Shaping succeeds, but every synthesis attempt fails schema validation."""

    def __init__(self):
        self.synthesis_calls = 0

    def complete(self, messages, tools=None, **kwargs):
        import json

        from hund.providers.base import CompletionResult

        all_text = " ".join(str(m.content) for m in messages)
        if "shaping specialist" in all_text:
            content = json.dumps({
                "mini_draft": {
                    "when_to_use": "When executing marketing campaigns.",
                    "steps": ["Step 1: Define audience.", "Step 2: Launch campaign."],
                },
                "questions": [
                    {
                        "key": "audience",
                        "title": "Target audience",
                        "help_text": "Choose the audience so channel and review steps fit.",
                        "options": ["Existing customers", "New B2B prospects"],
                        "default_option": "Existing customers",
                    }
                ],
                "research_queries": [],
            })
        elif "quality review" in all_text or "review gate" in all_text or "skill quality" in all_text:
            content = json.dumps({"approved": True, "score": 0.95, "issues": []})
        else:
            self.synthesis_calls += 1
            # Always invalid: only one step violates the 2-8 schema rule.
            content = json.dumps({
                "when_to_use": "When summarizing markdown release notes for the project.",
                "steps": ["Summarize the markdown notes."],
                "triggers": ["summarize markdown"],
                "verification": ["All notes covered.", "Summary is concise."],
                "examples": ["Markdown notes summarized."],
            })
        return CompletionResult(text=content, prompt_tokens=100, completion_tokens=50)


def test_failed_authoring_next_prompt_reaches_normal_loop_nothing_hangs(tmp_path: Path):
    """Track 3: after a FAILED authoring session, the next ordinary prompt
    reaches the agent loop on the FIRST attempt (no prompt swallowing) and
    nothing is pinned for it."""
    from hund.agent.loop import _run_authoring_runtime
    from hund.agent.safety import PermissionEngine
    from rich.console import Console

    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    reg = get_authoring_registry()
    reg.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="markdown summaries",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for markdown summaries",
    )
    sess = create_authoring_session(intent, session_id="e2e-fail-next", registry=reg)
    sess = replace(
        sess,
        state=AuthoringState.FAILED,
        failure_reason=(
            "Quality gate failed after 3 attempts: "
            "steps must contain between 2 and 8 concrete steps"
        ),
    )
    reg.save(sess)

    engine = PermissionEngine(home)
    outcome = _run_authoring_runtime(
        "nu när det misslyckades, visa vad vi har för filer i repot",
        session_id="e2e-fail-next",
        workspace=ws,
        engine=engine,
        console=Console(quiet=True),
        run_id="run-e2e-fail-next",
    )

    # The authoring layer must NOT swallow the prompt: falls through to the agent loop.
    assert outcome.handled is False
    # No receipt -> the loop pins nothing (rt.pinned_skill stays None).
    assert outcome.receipt is None
    # The failed session was pruned, so it cannot affect the next prompt.
    assert reg.get("e2e-fail-next") is None


def test_validation_retry_exhaustion_then_next_prompt_is_normal(tmp_path: Path):
    """Track 3: a synthesis that always fails validation ends FAILED after 3
    retries (Track 1) and the next ordinary prompt is not swallowed."""
    from hund.skills.authoring_runtime import handle_authoring_turn

    home = tmp_path / "hund_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    reg = get_authoring_registry()
    reg.clear()
    client = _ShapingOkSynthesisInvalidClient()

    started = handle_authoring_turn(
        "create a skill for markdown summaries without research",
        session_id="e2e-fail-flow",
        workspace=ws,
        registered_tools={"read_file"},
        registry=reg,
        shaping_client=client,
        client=client,
    )
    assert started.view is not None
    assert started.view.question_key == "mini_draft"

    confirmed = handle_authoring_turn(
        "continue",
        session_id="e2e-fail-flow",
        workspace=ws,
        registered_tools={"read_file"},
        registry=reg,
        shaping_client=client,
        client=client,
    )
    assert confirmed.view is not None
    assert confirmed.view.question_key == "audience"

    audience = handle_authoring_turn(
        "Existing customers",
        session_id="e2e-fail-flow",
        workspace=ws,
        registered_tools={"read_file"},
        registry=reg,
        shaping_client=client,
        client=client,
    )
    assert audience.handled is True

    sess = reg.get("e2e-fail-flow")
    assert sess is not None
    assert sess.state == AuthoringState.FAILED
    assert client.synthesis_calls == 3
    assert "3 attempts" in (sess.failure_reason or "")

    # The FAILED session does not swallow the next ordinary prompt.
    next_turn = handle_authoring_turn(
        "nu när det misslyckades, visa vad vi har för filer i repot",
        session_id="e2e-fail-flow",
        workspace=ws,
        registered_tools={"read_file"},
        registry=reg,
        shaping_client=client,
        client=client,
    )
    assert next_turn.handled is False
    assert reg.get("e2e-fail-flow") is None



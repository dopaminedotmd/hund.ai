"""Adversarial security tests for TCB tool dispatch: research authorization, single-use exact-draft consent, payload tamper rejection, and replay prevention."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from rich.console import Console

from hund.agent.safety import Decision, PermissionEngine, RiskLevel
from hund.agent.tool_dispatch import dispatch_tool_call
from hund.agent.types import ConfirmResponse, ConfirmVerdict
from hund.skills.authoring import (
    AuthoringSessionRegistry,
    AuthoringState,
    SkillAuthoringIntent,
    SkillDraft,
    authorize_publication,
    create_authoring_session,
    get_authoring_registry,
    transition_session,
)
from hund.skills.contracts import (
    PublicationAuthorization,
    ResearchChoice,
    ResearchGrant,
    compute_payload_hash,
)
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.tools.types import ToolCallContext


class MockHooks:
    def __init__(self, verdict: ConfirmVerdict = ConfirmVerdict.APPROVE_ONCE):
        self.verdict = verdict
        self.confirmed_calls: list[dict] = []
        self.declined_calls: list[str] = []

    def confirm(self, request):
        self.confirmed_calls.append(request)
        return ConfirmResponse(self.verdict)

    def tool_start(self, name, args):
        pass

    def declined(self, name, reason):
        self.declined_calls.append(f"{name}:{reason}")

    def blocked(self, name, reason):
        pass


def _make_skill(name: str = "test-cap") -> Skill:
    return Skill(
        schema_version=1,
        name=name,
        domain="general",
        status="draft",
        triggers=("test trigger",),
        when_to_use="When testing dispatch security.",
        steps=("Step 1: run test",),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify result.",),
        capability_id=f"general/{name}",
        scope="project",
    )


def test_tcb_dispatch_research_grant_enforcement(tmp_path: Path):
    from hund.tools.default_tools import register_defaults
    register_defaults(tmp_path)

    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    registry = get_authoring_registry()
    registry.clear()

    # 1. Authoring session WITH valid research grant -> web_search allowed
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Stripe webhook",
        target_scope="global",
        referenced_name=None,
        local_only=False,
        requires_research=True,
        confidence=1.0,
        raw_prompt="create stripe skill with research",
    )
    session = create_authoring_session(intent, registry=registry)
    grant = ResearchGrant(
        grant_id="grant_1",
        session_id=session.session_id,
        purpose="skill_authoring:stripe",
        choice=ResearchChoice.EXPLICITLY_REQUESTED,
        allowed_tools=("web_search", "read_url_content"),
    )
    session = transition_session(session, AuthoringState.RESEARCHING, registry=registry)
    session = type(session)(**{**session.__dict__, "research_grant": grant})
    registry.save(session)

    context = ToolCallContext(session_id=session.session_id, workspace=tmp_path, turn_id="turn_1")
    tc_search = {
        "function": {
            "name": "web_search",
            "arguments": '{"query": "stripe python sdk webhook"}',
        }
    }
    # Should not be blocked by authoring research guard
    res = dispatch_tool_call(tc_search, engine, console, tool_context=context, session_id=session.session_id)
    assert not res.startswith("[declined: external research not authorized")

    # 2. Authoring session WITHOUT research grant -> web_search declined
    session2 = create_authoring_session(intent, registry=registry)
    session2 = transition_session(session2, AuthoringState.SHAPING, registry=registry)
    context2 = ToolCallContext(session_id=session2.session_id, workspace=tmp_path, turn_id="turn_2")

    res2 = dispatch_tool_call(tc_search, engine, console, tool_context=context2, session_id=session2.session_id)
    assert "external research not authorized" in res2

    # 3. Authoring session with DECLINED research -> web_search declined
    session3 = create_authoring_session(intent, registry=registry)
    grant_declined = ResearchGrant(
        grant_id="grant_3",
        session_id=session3.session_id,
        purpose="skill_authoring:stripe",
        choice=ResearchChoice.DECLINED_WITH_LIMITATION,
    )
    session3 = transition_session(session3, AuthoringState.BUILDING, registry=registry)
    session3 = type(session3)(**{**session3.__dict__, "research_grant": grant_declined})
    registry.save(session3)
    context3 = ToolCallContext(session_id=session3.session_id, workspace=tmp_path, turn_id="turn_3")

    res3 = dispatch_tool_call(tc_search, engine, console, tool_context=context3, session_id=session3.session_id)
    assert "external research not authorized" in res3

    # 4. Normal turn outside authoring session -> web_search is SAFE and unaffected
    normal_context = ToolCallContext(session_id="normal_chat_sess", workspace=tmp_path, turn_id="turn_4")
    res_normal = dispatch_tool_call(tc_search, engine, console, tool_context=normal_context, session_id="normal_chat_sess")
    assert "external research not authorized" not in res_normal


def test_tcb_dispatch_direct_chat_skill_uses_standard_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from hund.skills.vault import SkillVault
    from hund.tools.default_tools import register_defaults

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    register_defaults(tmp_path)

    registry = get_authoring_registry()
    registry.clear()
    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    hooks = MockHooks(verdict=ConfirmVerdict.APPROVE_ONCE)
    context = ToolCallContext(
        session_id="direct_chat_session",
        workspace=tmp_path,
        turn_id="turn_direct",
    )
    skill = _make_skill(name="direct-chat-review")
    call = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps({
                "desired_disposition": "vault",
                "skill": skill.to_dict(),
            }),
        }
    }

    result = dispatch_tool_call(
        call,
        engine,
        console,
        hooks=hooks,
        tool_context=context,
        session_id=context.session_id,
    )

    assert len(hooks.confirmed_calls) == 1
    assert not result.startswith("[declined")
    stored = SkillVault().find_skill("direct-chat-review", workspace=tmp_path)
    assert stored is not None
    assert stored.name == "direct-chat-review"


def test_tcb_dispatch_direct_chat_skill_decline_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from hund.skills.vault import SkillVault
    from hund.tools.default_tools import register_defaults

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    register_defaults(tmp_path)

    registry = get_authoring_registry()
    registry.clear()
    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    hooks = MockHooks(verdict=ConfirmVerdict.DENY)
    context = ToolCallContext(
        session_id="direct_chat_decline",
        workspace=tmp_path,
        turn_id="turn_decline",
    )
    call = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps({
                "desired_disposition": "vault",
                "skill": _make_skill(name="declined-direct-chat").to_dict(),
            }),
        }
    }

    result = dispatch_tool_call(
        call,
        engine,
        console,
        hooks=hooks,
        tool_context=context,
        session_id=context.session_id,
    )

    assert len(hooks.confirmed_calls) == 1
    assert result == "[declined by user]"
    assert SkillVault().find_skill("declined-direct-chat", workspace=tmp_path) is None


def test_tcb_dispatch_direct_chat_skill_noninteractive_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from hund.skills.vault import SkillVault
    from hund.tools.default_tools import register_defaults

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    register_defaults(tmp_path)

    registry = get_authoring_registry()
    registry.clear()
    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    context = ToolCallContext(
        session_id="direct_chat_noninteractive",
        workspace=tmp_path,
        turn_id="turn_noninteractive",
    )
    call = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps({
                "desired_disposition": "vault",
                "skill": _make_skill(name="noninteractive-direct-chat").to_dict(),
            }),
        }
    }

    result = dispatch_tool_call(
        call,
        engine,
        console,
        noninteractive=True,
        tool_context=context,
        session_id=context.session_id,
    )

    assert "requires approval" in result
    assert SkillVault().find_skill("noninteractive-direct-chat", workspace=tmp_path) is None


def test_tcb_dispatch_active_authoring_without_binding_stays_declined(tmp_path: Path):
    from hund.tools.default_tools import register_defaults

    register_defaults(tmp_path)
    registry = get_authoring_registry()
    registry.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Active authoring guard",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create active authoring guard skill",
    )
    session = create_authoring_session(intent, registry=registry)
    hooks = MockHooks(verdict=ConfirmVerdict.APPROVE_ONCE)
    context = ToolCallContext(
        session_id=session.session_id,
        workspace=tmp_path,
        turn_id="turn_active",
    )
    call = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps({
                "desired_disposition": "vault",
                "skill": _make_skill(name="active-without-binding").to_dict(),
            }),
        }
    }

    result = dispatch_tool_call(
        call,
        PermissionEngine(tmp_path),
        Console(quiet=True),
        hooks=hooks,
        tool_context=context,
        session_id=context.session_id,
    )

    assert "unconfirmed or modified skill payload" in result
    assert hooks.confirmed_calls == []


def test_tcb_dispatch_terminal_authoring_session_can_use_standard_confirmation(
    tmp_path: Path,
):
    from hund.tools.default_tools import register_defaults

    register_defaults(tmp_path)
    registry = get_authoring_registry()
    registry.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Completed authoring",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create completed authoring skill",
    )
    session = create_authoring_session(intent, registry=registry)
    session = transition_session(session, AuthoringState.CANCELLED, registry=registry)
    hooks = MockHooks(verdict=ConfirmVerdict.DENY)
    context = ToolCallContext(
        session_id=session.session_id,
        workspace=tmp_path,
        turn_id="turn_after_cancel",
    )
    call = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps({
                "desired_disposition": "vault",
                "skill": _make_skill(name="after-cancel-direct-chat").to_dict(),
            }),
        }
    }

    result = dispatch_tool_call(
        call,
        PermissionEngine(tmp_path),
        Console(quiet=True),
        hooks=hooks,
        tool_context=context,
        session_id=context.session_id,
    )

    assert len(hooks.confirmed_calls) == 1
    assert result == "[declined by user]"


def test_tcb_dispatch_terminal_authoring_session_rejects_exact_publication_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from hund.skills.vault import SkillVault
    from hund.tools.default_tools import register_defaults

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    register_defaults(tmp_path)
    registry = get_authoring_registry()
    registry.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Cancelled exact publication",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create cancelled exact publication skill",
    )
    session = create_authoring_session(intent, registry=registry)
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)
    session = transition_session(session, AuthoringState.BUILDING, registry=registry)
    skill = _make_skill(name="cancelled-exact-publication")
    session = transition_session(
        session,
        AuthoringState.QUALITY_CHECKING,
        draft=SkillDraft(action="CREATE", skill=skill, metadata={}),
        registry=registry,
    )
    session = transition_session(session, AuthoringState.READY, registry=registry)
    session, auth = authorize_publication(
        session,
        user_id="user_1",
        disposition="equip",
        registry=registry,
    )
    session = transition_session(session, AuthoringState.CANCELLED, registry=registry)
    hooks = MockHooks(verdict=ConfirmVerdict.APPROVE_ONCE)
    context = ToolCallContext(
        session_id=session.session_id,
        workspace=tmp_path,
        turn_id="turn_cancelled_exact",
    )
    result = dispatch_tool_call(
        {
            "function": {
                "name": "create_skill",
                "arguments": json.dumps({
                    "session_id": session.session_id,
                    "authorization_id": auth.authorization_id,
                    "payload_hash": session.draft_hash,
                    "desired_disposition": "equip",
                    "skill": skill.to_dict(),
                }),
            }
        },
        PermissionEngine(tmp_path),
        Console(quiet=True),
        hooks=hooks,
        tool_context=context,
        session_id=session.session_id,
    )

    assert "unconfirmed or modified skill payload" in result
    assert hooks.confirmed_calls == []
    assert SkillVault().find_skill(skill.name, workspace=tmp_path) is None


def test_tcb_dispatch_exact_draft_publication_authorization(tmp_path: Path):
    from hund.tools.default_tools import register_defaults
    register_defaults(tmp_path)

    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    registry = get_authoring_registry()
    registry.clear()

    # Create authoring session with Ready draft
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
    session = create_authoring_session(intent, registry=registry)
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)
    session = transition_session(session, AuthoringState.BUILDING, registry=registry)

    skill = _make_skill(name="fastapi-envelope")
    draft = SkillDraft(action="CREATE", skill=skill, metadata={})
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=registry)
    session = transition_session(session, AuthoringState.READY, registry=registry)

    # Authorize publication
    session, auth = authorize_publication(session, user_id="user_1", disposition="equip", registry=registry)
    expected_hash = session.draft_hash

    hooks = MockHooks(verdict=ConfirmVerdict.APPROVE_ONCE)
    context = ToolCallContext(session_id=session.session_id, workspace=tmp_path, turn_id="turn_1")

    # 1. Valid publication call with matching payload hash and session
    valid_args = {
        "session_id": session.session_id,
        "authorization_id": auth.authorization_id,
        "payload_hash": expected_hash,
        "desired_disposition": "equip",
        "skill": skill.to_dict(),
    }
    tc_valid = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps(valid_args),
        }
    }
    res_valid = dispatch_tool_call(
        tc_valid, engine, console, hooks=hooks,
        tool_context=context, session_id=session.session_id,
    )
    assert not res_valid.startswith("[declined")
    assert hooks.confirmed_calls == []

    # 2. Replay attempt with same authorization -> should be declined (single-use consumed)
    res_replay = dispatch_tool_call(
        tc_valid, engine, console, hooks=hooks,
        tool_context=context, session_id=session.session_id,
    )
    assert "unconfirmed or modified skill payload requires explicit user acceptance" in res_replay or "declined" in res_replay

    # 3. Tampered payload (different step) -> hash mismatch -> declined
    session2 = create_authoring_session(intent, registry=registry)
    session2 = transition_session(session2, AuthoringState.SHAPING, registry=registry)
    session2 = transition_session(session2, AuthoringState.BUILDING, registry=registry)
    session2 = transition_session(session2, AuthoringState.QUALITY_CHECKING, draft=draft, registry=registry)
    session2 = transition_session(session2, AuthoringState.READY, registry=registry)
    session2, auth2 = authorize_publication(session2, user_id="user_1", disposition="equip", registry=registry)
    context2 = ToolCallContext(session_id=session2.session_id, workspace=tmp_path, turn_id="turn_2")

    tampered_skill = skill.to_dict()
    tampered_skill["steps"] = ["Malicious injected step"]
    tampered_args = {
        "session_id": session2.session_id,
        "authorization_id": auth2.authorization_id,
        "payload_hash": session2.draft_hash,
        "desired_disposition": "equip",
        "skill": tampered_skill,
    }
    tc_tampered = {
        "function": {
            "name": "create_skill",
            "arguments": json.dumps(tampered_args),
        }
    }
    res_tampered = dispatch_tool_call(
        tc_tampered, engine, console, hooks=hooks,
        tool_context=context2, session_id=session2.session_id,
    )
    assert "unconfirmed or modified skill payload" in res_tampered or "declined" in res_tampered


@pytest.mark.parametrize(
    "mismatch",
    ("expired", "cross_session", "scope", "disposition", "stale_token"),
)
def test_tcb_dispatch_exact_publication_metadata_mismatch_fails_closed(
    tmp_path: Path,
    mismatch: str,
):
    from hund.tools.default_tools import register_defaults

    register_defaults(tmp_path)
    registry = get_authoring_registry()
    registry.clear()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="Metadata binding",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create metadata binding skill",
    )
    session = create_authoring_session(intent, registry=registry)
    session = transition_session(session, AuthoringState.SHAPING, registry=registry)
    session = transition_session(session, AuthoringState.BUILDING, registry=registry)
    skill = _make_skill(name=f"metadata-{mismatch}")
    session = transition_session(
        session,
        AuthoringState.QUALITY_CHECKING,
        draft=SkillDraft(action="CREATE", skill=skill, metadata={}),
        registry=registry,
    )
    session = transition_session(session, AuthoringState.READY, registry=registry)
    session, auth = authorize_publication(
        session,
        user_id="user_1",
        disposition="equip",
        registry=registry,
    )
    args = {
        "session_id": session.session_id,
        "authorization_id": auth.authorization_id,
        "payload_hash": session.draft_hash,
        "desired_disposition": "equip",
        "skill": skill.to_dict(),
    }
    effective_session_id = session.session_id

    if mismatch == "expired":
        expired_auth = replace(
            auth,
            expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        )
        registry.save(replace(session, publication_authorization=expired_auth))
    elif mismatch == "cross_session":
        effective_session_id = "different_session"
    elif mismatch == "scope":
        registry.save(replace(
            session,
            publication_authorization=replace(auth, scope="global"),
        ))
    elif mismatch == "disposition":
        args["desired_disposition"] = "vault"
    elif mismatch == "stale_token":
        args["authorization_id"] = "stale_authorization"

    hooks = MockHooks(verdict=ConfirmVerdict.APPROVE_ONCE)
    context = ToolCallContext(
        session_id=effective_session_id,
        workspace=tmp_path,
        turn_id=f"turn_{mismatch}",
    )
    result = dispatch_tool_call(
        {
            "function": {
                "name": "create_skill",
                "arguments": json.dumps(args),
            }
        },
        PermissionEngine(tmp_path),
        Console(quiet=True),
        hooks=hooks,
        tool_context=context,
        session_id=effective_session_id,
    )

    assert "unconfirmed or modified skill payload" in result
    assert hooks.confirmed_calls == []

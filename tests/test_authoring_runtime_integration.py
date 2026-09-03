"""End-to-end checks for the conversation-level skill authoring runtime."""
from __future__ import annotations

import json
from pathlib import Path
from rich.console import Console

from hund.agent.loop import _run_authoring_runtime
from hund.agent.safety import PermissionEngine
from hund.providers.base import CompletionResult
from hund.skills.authoring import AuthoringSessionRegistry, AuthoringState
from hund.skills.authoring_runtime import (
    AuthoringAction,
    AuthoringActionKind,
    complete_authoring_research,
    handle_authoring_action,
    handle_authoring_turn,
)
from hund.skills.contracts import compute_payload_hash
from hund.tools.skill_tool import make_handler
from hund.tools.types import ToolStatus


def _tools() -> set[str]:
    return {"read_file", "search_files", "write_file", "terminal", "web_search", "create_skill"}


class _ShapingClient:
    def __init__(self, needs_research: bool = False):
        self.needs_research = needs_research

    def complete(self, messages, tools=None, **kwargs):
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
                "research_queries": ["b2b marketing strategy"] if self.needs_research else [],
            })
        elif "quality review" in all_text or "review gate" in all_text or "skill quality" in all_text:
            content = json.dumps({
                "approved": True,
                "score": 0.95,
                "issues": [],
            })
        else:
            content = json.dumps({
                "when_to_use": "When executing targeted marketing workflows.",
                "steps": [
                    "Define target audience and campaign message.",
                    "Execute outreach and monitor response rates.",
                ],
                "triggers": ["marketing", "b2b outreach"],
                "verification": [
                    "Audience segment matches intended campaign criteria.",
                    "Outreach delivery logs confirm dispatch.",
                ],
                "examples": ["Marketing outreach dispatched to targeted segment."],
            })
        return CompletionResult(text=content, prompt_tokens=100, completion_tokens=50)


def test_runtime_persists_validated_model_shaping_questions(tmp_path: Path):
    registry = AuthoringSessionRegistry()

    started = handle_authoring_turn(
        "create a skill for marketing for this project without research",
        session_id="model-shaping",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=_ShapingClient(),
    )

    session = registry.get("model-shaping")
    assert session is not None
    assert session.shaping_questions[0].key == "audience"
    assert started.view is not None
    # First view step is mini-draft confirmation
    assert started.view.question_key == "mini_draft"


def test_typed_free_text_clarification_becomes_authoring_state(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    started = handle_authoring_turn(
        "create a skill for something useful for this project without research",
        session_id="clarification",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=_ShapingClient(),
    )

    assert started.view is not None
    assert started.view.question_key == "clarification"
    assert started.view.options == ()

    ready = handle_authoring_action(
        AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="clarification",
            value="Review pull requests for release-blocking risks.",
        ),
        session_id="clarification",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=_ShapingClient(),
    )

    assert ready.view is not None
    assert ready.view.phase == AuthoringState.READY
    assert registry.get("clarification").shaping_answers["clarification"].startswith(
        "Review pull requests"
    )


def test_authoring_action_kinds_are_distinct_semantic_commands():
    assert len(set(AuthoringActionKind)) == 8


def test_typed_authoring_advances_one_contextual_question_at_a_time(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    client = _ShapingClient()

    started = handle_authoring_turn(
        "create a skill for marketing without research",
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
    )

    assert started.view is not None
    assert started.view.phase == AuthoringState.SHAPING
    assert started.view.question_key == "mini_draft"

    confirmed = handle_authoring_action(
        AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="mini_draft",
            value="continue",
        ),
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=client,
    )

    assert confirmed.view is not None
    assert confirmed.view.phase == AuthoringState.SHAPING
    assert confirmed.view.question_key == "audience"

    scope = handle_authoring_action(
        AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="audience",
            value="Existing customers",
        ),
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=client,
    )

    assert scope.view is not None
    assert scope.view.phase == AuthoringState.SHAPING
    assert scope.view.question_key == "scope"

    ready = handle_authoring_action(
        AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="scope",
            value=scope.view.options[0].value,
        ),
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=client,
    )

    assert ready.view is not None
    assert ready.view.phase == AuthoringState.READY
    assert [option.action for option in ready.view.options[:4]] == [
        AuthoringActionKind.PUBLISH_USE,
        AuthoringActionKind.PUBLISH_VAULT,
        AuthoringActionKind.EDIT,
        AuthoringActionKind.DECLINE,
    ]
    assert registry.get("chat-stepper").state == AuthoringState.READY

    editing = handle_authoring_action(
        AuthoringAction(AuthoringActionKind.EDIT),
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=client,
    )
    assert editing.view is not None
    assert editing.view.phase == AuthoringState.SHAPING


def test_transient_decline_emits_one_compact_terminal_notice(tmp_path: Path):
    from hund.skills.authoring import get_authoring_registry

    registry = get_authoring_registry()
    registry.clear()
    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    started = _run_authoring_runtime(
        "create a skill for marketing without research",
        session_id="chat-decline",
        workspace=tmp_path,
        engine=engine,
        console=console,
        client=_ShapingClient(),
        transient=True,
    )
    assert started.view is not None

    declined = _run_authoring_runtime(
        "",
        session_id="chat-decline",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(AuthoringActionKind.DECLINE),
        client=_ShapingClient(),
        transient=True,
    )

    assert declined.view is None
    assert declined.outputs == ("Skill authoring cancelled.",)
    assert registry.get("chat-decline") is None


def test_typed_back_from_research_returns_to_last_shaping_question(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    client = _ShapingClient(needs_research=True)
    started = handle_authoring_turn(
        "create a skill for OpenAI API errors with research",
        session_id="chat-research-back",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
    )
    current = started
    while current.view and current.view.phase == AuthoringState.SHAPING:
        current = handle_authoring_action(
            AuthoringAction(
                AuthoringActionKind.ANSWER,
                key=current.view.question_key,
                value=current.view.options[0].value if current.view.options else "continue",
            ),
            session_id="chat-research-back",
            workspace=tmp_path,
            registered_tools=_tools(),
            registry=registry,
            client=client,
        )

    assert current.view is not None
    assert current.view.phase == AuthoringState.RESEARCHING
    backed = handle_authoring_action(
        AuthoringAction(AuthoringActionKind.BACK),
        session_id="chat-research-back",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=client,
    )
    assert backed.view is not None
    assert backed.view.phase == AuthoringState.SHAPING


def test_transient_runtime_returns_view_then_one_typed_receipt_without_cards(tmp_path: Path):
    from hund.skills.authoring import get_authoring_registry
    from hund.tools import registry as tool_registry
    from hund.tools.default_tools import register_defaults
    from hund.tools.skill_tool import make_handler

    register_defaults(tmp_path)
    create_skill_tool = tool_registry.get("create_skill")
    assert create_skill_tool is not None
    create_skill_tool.handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    registry = get_authoring_registry()
    registry.clear()
    engine = PermissionEngine(tmp_path)
    console = Console(quiet=True)
    client = _ShapingClient()

    started = _run_authoring_runtime(
        "create a skill for marketing without research",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        client=client,
        transient=True,
    )
    assert started.outputs == ()
    assert started.view is not None
    assert started.view.question_key == "mini_draft"

    confirmed = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="mini_draft",
            value="continue",
        ),
        client=client,
        transient=True,
    )
    assert confirmed.outputs == ()
    assert confirmed.view.question_key == "audience"

    scope = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="audience",
            value="Existing customers",
        ),
        client=client,
        transient=True,
    )
    assert scope.outputs == ()
    assert scope.view.question_key == "scope"

    ready = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="scope",
            value=scope.view.options[0].value,
        ),
        client=client,
        transient=True,
    )
    assert ready.outputs == ()
    assert ready.view.phase == AuthoringState.READY

    from hund.agent.types import ConfirmVerdict
    from tests.test_authoring_dispatch_security import MockHooks
    hooks = MockHooks(verdict=ConfirmVerdict.APPROVE_ONCE)

    published = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        hooks=hooks,
        authoring_action=AuthoringAction(AuthoringActionKind.PUBLISH_USE),
        client=client,
        transient=True,
    )
    assert published.outputs == ()
    assert published.view is None
    persisted = registry.get("chat-transient")
    assert published.receipt is not None, (
        persisted.state if persisted else None,
        persisted.failure_reason if persisted else None,
    )
    assert published.receipt.skill_name == "marketing"
    assert published.receipt.vault_state == "equipped"


def test_agent_runtime_injects_configured_client_for_typed_shaping(tmp_path: Path):
    from hund.skills.authoring import get_authoring_registry

    get_authoring_registry().clear()
    outcome = _run_authoring_runtime(
        "create a skill for marketing for this project without research",
        session_id="client-injection",
        workspace=tmp_path,
        engine=PermissionEngine(tmp_path),
        console=Console(quiet=True),
        client=_ShapingClient(),
        transient=True,
    )

    assert outcome.view is not None
    assert outcome.view.question_key == "mini_draft"


def test_local_authoring_reaches_ready_without_writing(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    client = _ShapingClient()

    shaping = handle_authoring_turn(
        "create a skill for markdown release notes in this project without research",
        session_id="chat-1",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    assert shaping.handled
    assert "SKILL AUTHORING" in shaping.rendered
    assert "Mini-draft" in shaping.rendered
    assert not list(tmp_path.rglob("*.json"))

    confirmed = handle_authoring_turn(
        "continue",
        session_id="chat-1",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    ready = handle_authoring_turn(
        "Existing customers",
        session_id="chat-1",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    session = registry.get("chat-1")
    assert session is not None
    assert session.state == AuthoringState.READY
    assert "SKILL READY" in ready.rendered
    assert not list(tmp_path.rglob("*.json"))

    publication = handle_authoring_turn(
        "use now",
        session_id="chat-1",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    assert publication.publication_args is not None
    payload = publication.publication_args["skill"]
    assert publication.publication_args["payload_hash"] == compute_payload_hash(payload)
    assert publication.publication_args["authorization_id"]


def test_research_requires_choice_and_uses_supplied_dispatch_results(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    client = _ShapingClient(needs_research=True)

    handle_authoring_turn(
        "create a skill for OpenAI SDK error handling globally with research",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    handle_authoring_turn(
        "continue",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    research = handle_authoring_turn(
        "Existing customers",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    assert "External Research" in research.rendered

    authorized = handle_authoring_turn(
        "yes",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    assert authorized.research_queries

    ready = complete_authoring_research(
        session_id="chat-2",
        summaries=("Official SDK documentation summary.",),
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        client=client,
    )
    session = registry.get("chat-2")
    assert session is not None
    assert session.state == AuthoringState.READY
    assert session.research_sources
    assert "SKILL READY" in ready.rendered


def test_batch_moves_to_next_skill_after_decline(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    client = _ShapingClient()

    first = handle_authoring_turn(
        "create skills for markdown release notes and changelog validation",
        session_id="chat-3",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    assert "[1 of 2]" in first.rendered

    second = handle_authoring_turn(
        "decline",
        session_id="chat-3",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    assert "[2 of 2]" in second.rendered
    assert "changelog validation" in second.rendered.lower()


def test_ready_edit_returns_to_visible_shaping(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    client = _ShapingClient()
    handle_authoring_turn(
        "create a skill for markdown summaries without research",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    handle_authoring_turn(
        "continue",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )
    handle_authoring_turn(
        "Existing customers",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )

    editing = handle_authoring_turn(
        "edit",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
        shaping_client=client,
        client=client,
    )

    assert registry.get("chat-edit").state == AuthoringState.EDITING
    assert "Shaping" in editing.rendered


def test_failed_session_closing_removes_from_registry(tmp_path: Path):
    from dataclasses import replace
    from hund.skills.authoring import create_authoring_session, SkillAuthoringIntent, transition_session

    registry = AuthoringSessionRegistry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="fail-test",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="fail",
    )
    session = create_authoring_session(intent, session_id="failed-sess", registry=registry)
    failed = transition_session(session, AuthoringState.FAILED, registry=registry)
    failed = replace(failed, failure_reason="Synthesis timed out.")
    registry.save(failed)

    # Action BACK (Esc / Close) closes terminal state cleanly
    res = handle_authoring_action(
        AuthoringAction(AuthoringActionKind.BACK),
        session_id="failed-sess",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert res.handled is True
    assert res.view is None
    assert registry.get("failed-sess") is None


def test_research_failure_sets_failed_state_and_returns_failed_view(tmp_path: Path):
    from hund.tools.registry import Tool, register as register_tool, get as get_tool
    from hund.tools.types import ToolResult, ToolStatus

    old_tool = get_tool("web_search")
    register_tool(
        Tool(
            name="web_search",
            description="Search",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            base_risk="SAFE",
            handler=lambda args, ctx=None: ToolResult(status=ToolStatus.ERROR, error="Network failure"),
        )
    )

    try:
        registry = AuthoringSessionRegistry()
        client = _ShapingClient(needs_research=True)
        engine = PermissionEngine(tmp_path)

        # Start research session
        outcome1 = _run_authoring_runtime(
            "create a skill for b2b outreach with research",
            session_id="research-fail-sess",
            authoring_action=None,
            workspace=tmp_path,
            engine=engine,
            console=Console(quiet=True),
            client=client,
            transient=False,
        )
        assert outcome1.handled is True

        # User confirms mini-draft and answers question to trigger research
        outcome2 = _run_authoring_runtime(
            "continue",
            session_id="research-fail-sess",
            authoring_action=None,
            workspace=tmp_path,
            engine=engine,
            console=Console(quiet=True),
            client=client,
            transient=False,
        )
        assert outcome2.handled is True

        outcome3 = _run_authoring_runtime(
            "Existing customers",
            session_id="research-fail-sess",
            authoring_action=None,
            workspace=tmp_path,
            engine=engine,
            console=Console(quiet=True),
            client=client,
            transient=False,
        )
        assert outcome3.handled is True
        assert outcome3.view is not None
        assert outcome3.view.phase == AuthoringState.RESEARCHING

        # User approves research, tool execution fails
        outcome4 = _run_authoring_runtime(
            "yes",
            session_id="research-fail-sess",
            authoring_action=None,
            workspace=tmp_path,
            engine=engine,
            console=Console(quiet=True),
            client=client,
            transient=False,
        )
        assert outcome4.handled is True
        assert outcome4.view is not None
        assert outcome4.view.phase == AuthoringState.FAILED
        assert "Research failed" in (outcome4.view.description or "")
    finally:
        if old_tool:
            register_tool(old_tool)


def test_validation_retry_exhaustion_marks_failed_with_reason(tmp_path: Path):
    """Track 1: when every synthesis attempt fails validation the session ends FAILED
    with an understandable reason after 3 attempts, so the user can start again."""
    from hund.skills.authoring import (
        AuthoringState,
        SkillAuthoringIntent,
        create_authoring_session,
        get_authoring_registry,
        transition_session,
    )
    from hund.skills.authoring_runtime import _build_ready

    reg = get_authoring_registry()
    reg.clear()

    intent = SkillAuthoringIntent(
        operation="create",
        capability="changelog summarization",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for changelog summarization",
    )
    session = create_authoring_session(intent, registry=reg)
    session = transition_session(session, AuthoringState.SHAPING, registry=reg)

    class AlwaysInvalidClient:
        def __init__(self):
            self.synthesis_calls = 0

        def complete(self, messages, tools=None, **kwargs):
            all_text = " ".join(str(m.content) for m in messages)
            if "quality review" in all_text:
                content = json.dumps({"approved": True, "score": 0.95, "issues": []})
            else:
                self.synthesis_calls += 1
                # Only one step: violates the 2-8 step schema rule every time.
                content = json.dumps({
                    "when_to_use": "When summarizing changelogs for release notes.",
                    "steps": ["Summarize the changelog entries."],
                    "triggers": ["summarize changelog"],
                    "verification": ["All entries covered.", "Notes are concise."],
                    "examples": ["Changelog summarized for the release."],
                })
            return CompletionResult(text=content, prompt_tokens=100, completion_tokens=50)

    client = AlwaysInvalidClient()
    res = _build_ready(
        session,
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=reg,
        client=client,
        run_id="run-val-retry-exhaust",
    )

    assert res.handled is True
    sess = reg.get(session.session_id)
    assert sess is not None
    assert sess.state == AuthoringState.FAILED
    assert client.synthesis_calls == 3
    reason = sess.failure_reason or ""
    assert "3 attempts" in reason
    assert "steps" in reason

    # The failed session does not block a fresh authoring attempt.
    retry_session = create_authoring_session(intent, registry=reg)
    assert retry_session.state == AuthoringState.RECOGNIZED


def test_authoring_llm_requests_logged_to_requests_db(tmp_path: Path):
    from hund.store.sqlite import connect_requests
    from hund.skills.shaping import build_shaping_plan
    from hund.skills.authoring import inspect_local_context, SkillAuthoringIntent

    snapshot = inspect_local_context(tmp_path, _tools(), ())
    intent = SkillAuthoringIntent(
        operation="create",
        capability="shopify product updates",
        target_scope="project",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create skill for shopify product updates",
    )
    client = _ShapingClient()
    test_run_id = "test-run-b6-logging"

    plan = build_shaping_plan(intent, snapshot, client=client, workspace=tmp_path, run_id=test_run_id)
    assert plan.failed is False

    conn = connect_requests()
    cur = conn.cursor()
    cur.execute("SELECT task_class, run_id, prompt_tokens, completion_tokens FROM requests WHERE run_id = ?", (test_run_id,))
    rows = cur.fetchall()
    conn.close()

    assert len(rows) >= 1
    assert rows[0][0] == "authoring_shaping"
    assert rows[0][1] == test_run_id


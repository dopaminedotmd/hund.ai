"""End-to-end checks for the conversation-level skill authoring runtime."""
from __future__ import annotations

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
    def complete(self, messages, tools=None):
        return CompletionResult(
            text=(
                '{"subject":"marketing","confidence":0.9,"questions":['
                '{"key":"audience","title":"Target audience",'
                '"help_text":"Choose the audience so channel and review steps fit.",'
                '"options":["Existing customers","New B2B prospects"],'
                '"default_option":"Existing customers"}]}'
            )
        )


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
    assert started.view.title == "Target audience"
    assert started.view.description.startswith("Choose the audience")


def test_typed_free_text_clarification_becomes_authoring_state(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    started = handle_authoring_turn(
        "create a skill for something useful for this project without research",
        session_id="clarification",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
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

    started = handle_authoring_turn(
        "create a skill for marketing without research",
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )

    assert started.view is not None
    assert started.view.phase == AuthoringState.SHAPING
    assert started.view.step_index == 1
    assert started.view.step_total == 2
    assert started.view.question_key == "focus"
    assert started.view.title == "Primary Marketing Outcome"
    assert "controls the procedure" in started.view.description
    assert all("Project" not in option.label for option in started.view.options)

    scope = handle_authoring_action(
        AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="focus",
            value=started.view.options[0].value,
        ),
        session_id="chat-stepper",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )

    assert scope.view is not None
    assert scope.view.phase == AuthoringState.SHAPING
    assert scope.view.step_index == 2
    assert scope.view.question_key == "scope"
    assert scope.view.title == "Skill Scope"
    assert registry.get("chat-stepper").state == AuthoringState.SHAPING

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
    )
    assert editing.view is not None
    assert editing.view.phase == AuthoringState.SHAPING
    assert editing.view.question_key == "scope"


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
        transient=True,
    )

    assert declined.view is None
    assert declined.outputs == ("Skill authoring cancelled.",)
    assert registry.get("chat-decline") is None


def test_typed_back_from_research_returns_to_last_shaping_question(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    started = handle_authoring_turn(
        "create a skill for OpenAI API errors with research",
        session_id="chat-research-back",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    current = started
    while current.view and current.view.phase == AuthoringState.SHAPING:
        current = handle_authoring_action(
            AuthoringAction(
                AuthoringActionKind.ANSWER,
                key=current.view.question_key,
                value=current.view.options[0].value,
            ),
            session_id="chat-research-back",
            workspace=tmp_path,
            registered_tools=_tools(),
            registry=registry,
        )

    assert current.view is not None
    assert current.view.phase == AuthoringState.RESEARCHING
    backed = handle_authoring_action(
        AuthoringAction(AuthoringActionKind.BACK),
        session_id="chat-research-back",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert backed.view is not None
    assert backed.view.phase == AuthoringState.SHAPING
    assert backed.view.question_key == "scope"


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

    started = _run_authoring_runtime(
        "create a skill for marketing without research",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        transient=True,
    )
    assert started.outputs == ()
    assert started.view is not None
    assert started.view.question_key == "focus"

    focus = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="focus",
            value=started.view.options[0].value,
        ),
        transient=True,
    )
    assert focus.outputs == ()
    assert focus.view.question_key == "scope"

    ready = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(
            AuthoringActionKind.ANSWER,
            key="scope",
            value=focus.view.options[0].value,
        ),
        transient=True,
    )
    assert ready.outputs == ()
    assert ready.view.phase == AuthoringState.READY

    published = _run_authoring_runtime(
        "",
        session_id="chat-transient",
        workspace=tmp_path,
        engine=engine,
        console=console,
        authoring_action=AuthoringAction(AuthoringActionKind.PUBLISH_USE),
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
    assert published.receipt.scope == "project"
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
    assert outcome.view.question_key == "audience"


def test_local_authoring_reaches_ready_without_writing(tmp_path: Path):
    registry = AuthoringSessionRegistry()

    shaping = handle_authoring_turn(
        "create a skill for markdown release notes in this project without research",
        session_id="chat-1",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert shaping.handled
    assert "Shaping" in shaping.rendered
    assert not list(tmp_path.rglob("*.json"))

    ready = handle_authoring_turn(
        "Project scope. Generate release notes from the committed changes.",
        session_id="chat-1",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
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
    )
    assert publication.publication_args is not None
    payload = publication.publication_args["skill"]
    assert publication.publication_args["payload_hash"] == compute_payload_hash(payload)
    assert publication.publication_args["authorization_id"]


def test_research_requires_choice_and_uses_supplied_dispatch_results(tmp_path: Path):
    registry = AuthoringSessionRegistry()

    handle_authoring_turn(
        "create a skill for OpenAI SDK error handling globally with research",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    research = handle_authoring_turn(
        "Global scope. Handle current SDK errors and verify retry behavior.",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert "External Research" in research.rendered

    authorized = handle_authoring_turn(
        "yes",
        session_id="chat-2",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert authorized.research_queries

    ready = complete_authoring_research(
        session_id="chat-2",
        summaries=("Official SDK documentation summary.",),
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    session = registry.get("chat-2")
    assert session is not None
    assert session.state == AuthoringState.READY
    assert session.research_sources
    assert "SKILL READY" in ready.rendered


def test_batch_moves_to_next_skill_after_decline(tmp_path: Path):
    registry = AuthoringSessionRegistry()

    first = handle_authoring_turn(
        "create skills for markdown release notes and changelog validation",
        session_id="chat-3",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert "[1 of 2]" in first.rendered

    second = handle_authoring_turn(
        "decline",
        session_id="chat-3",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    assert "[2 of 2]" in second.rendered
    assert "changelog validation" in second.rendered.lower()


def test_request_mode_publishes_directly_from_chat(tmp_path: Path):
    result = make_handler(home=tmp_path, workspace_path=tmp_path)(
        {"request": "create a skill for current OpenAI SDK docs"}
    )

    assert result.status is ToolStatus.SUCCESS
    assert "Saved skill" in result.to_llm_text()
    assert list((tmp_path / "brain" / "skills").rglob("*.json"))


def test_ready_edit_returns_to_visible_shaping(tmp_path: Path):
    registry = AuthoringSessionRegistry()
    handle_authoring_turn(
        "create a skill for markdown summaries without research",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )
    handle_authoring_turn(
        "Project scope with concise summaries.",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )

    editing = handle_authoring_turn(
        "edit",
        session_id="chat-edit",
        workspace=tmp_path,
        registered_tools=_tools(),
        registry=registry,
    )

    assert registry.get("chat-edit").state == AuthoringState.EDITING
    assert "Shaping" in editing.rendered

"""Conversation-level orchestration for explicit skill authoring."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import uuid
from typing import Any, Sequence

from .authoring import (
    AuthoringSession,
    AuthoringSessionRegistry,
    AuthoringState,
    LocalInspectionSnapshot,
    LocalSkillProposal,
    ResearchSkillProposal,
    ResearchSourceRef,
    ShapingQuestion,
    SkillAuthoringIntent,
    apply_shaping_answers,
    authorize_publication,
    create_authoring_session,
    decide_research_need,
    detect_batch_skill_intent,
    extract_shaping_questions,
    get_authoring_registry,
    inspect_local_context,
    run_deterministic_quality_checks,
    transition_session,
)
from .contracts import ResearchChoice, ResearchGrant
from .factory import SkillFactory
from .loader import load_builtins, load_domain_skills
from .scope import compute_workspace_key, resolve_scope_and_overlap


class AuthoringActionKind(str, Enum):
    ANSWER = "answer"
    RESEARCH = "research"
    LOCAL_ONLY = "local_only"
    PUBLISH_USE = "publish_use"
    PUBLISH_VAULT = "publish_vault"
    EDIT = "edit"
    DECLINE = "decline"
    BACK = "back"


@dataclass(frozen=True)
class AuthoringAction:
    kind: AuthoringActionKind
    key: str = ""
    value: str = ""


@dataclass(frozen=True)
class AuthoringOption:
    action: AuthoringActionKind | str
    label: str
    value: str = ""


@dataclass(frozen=True)
class AuthoringView:
    session_id: str
    phase: str
    subject: str
    title: str
    question_key: str = ""
    step_index: int = 0
    step_total: int = 0
    options: tuple[AuthoringOption, ...] = ()
    skill_name: str = ""
    scope: str = ""
    description: str = ""
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthoringTurnResult:
    """One deterministic authoring turn; side effects are delegated to runtime."""

    handled: bool
    rendered: str = ""
    research_queries: tuple[str, ...] = ()
    publication_args: dict[str, Any] | None = None
    view: AuthoringView | None = None


_TERMINAL_STATES = {
    AuthoringState.PUBLISHED,
    AuthoringState.CANCELLED,
    AuthoringState.FAILED,
}


def _session_questions(session: AuthoringSession) -> tuple[ShapingQuestion, ...]:
    if session.shaping_questions:
        return session.shaping_questions
    intent = session.queue_items[session.queue_position - 1]
    return extract_shaping_questions(intent)


def _authoring_view(session: AuthoringSession) -> AuthoringView:
    if session.state in {AuthoringState.SHAPING, AuthoringState.EDITING}:
        questions = _session_questions(session)
        active_index = next(
            (index for index, question in enumerate(questions) if question.key not in session.shaping_answers),
            max(len(questions) - 1, 0),
        )
        question = questions[active_index]
        return AuthoringView(
            session_id=session.session_id,
            phase=AuthoringState.SHAPING,
            subject=session.request_subject,
            title=question.title,
            description=question.help_text,
            question_key=question.key,
            step_index=active_index + 1,
            step_total=len(questions),
            options=tuple(
                AuthoringOption(AuthoringActionKind.ANSWER, option, option)
                for option in question.options
            ),
        )
    if session.state == AuthoringState.RESEARCHING:
        return AuthoringView(
            session.session_id,
            session.state,
            session.request_subject,
            "External Research",
            options=(
                AuthoringOption(AuthoringActionKind.RESEARCH, "Search official documentation"),
                AuthoringOption(AuthoringActionKind.LOCAL_ONLY, "Use existing context only"),
                AuthoringOption(AuthoringActionKind.DECLINE, "Decline"),
            ),
        )
    if session.state == AuthoringState.READY:
        skill = session.draft.skill if session.draft else None
        research = getattr(skill, "research_metadata", None) if skill else None
        return AuthoringView(
            session.session_id,
            session.state,
            session.request_subject,
            "Skill Ready",
            options=(
                AuthoringOption(AuthoringActionKind.PUBLISH_USE, "Publish & use"),
                AuthoringOption(AuthoringActionKind.PUBLISH_VAULT, "Save to vault"),
                AuthoringOption(AuthoringActionKind.EDIT, "Edit"),
                AuthoringOption(AuthoringActionKind.DECLINE, "Decline"),
            ),
            skill_name=skill.name if skill else session.request_subject,
            scope=skill.scope if skill else session.target_scope,
            description=skill.when_to_use if skill else "",
            limitations=tuple(getattr(research, "limitations", ()) or ()),
        )
    return AuthoringView(
        session.session_id,
        session.state,
        session.request_subject,
        session.state.replace("_", " ").title(),
    )


def _render(session: AuthoringSession, width: int, ascii_only: bool) -> str:
    from ..ui.skill_authoring import (
        render_authoring_quality,
        render_authoring_ready,
        render_authoring_research,
        render_authoring_shaping,
        render_batch_banner,
    )

    prefix = ""
    if session.queue_total > 1:
        prefix = render_batch_banner(
            session.queue_position,
            session.queue_total,
            session.request_subject,
            width,
            ascii_only=ascii_only,
        ) + "\n\n"

    if session.state in {AuthoringState.SHAPING, AuthoringState.EDITING}:
        questions = _session_questions(session)
        active = next(
            (question for question in questions if question.key not in session.shaping_answers),
            questions[-1:] and questions[-1],
        )
        return prefix + render_authoring_shaping(
            session, (active,) if active else (), width, ascii_only=ascii_only
        )
    if session.state == AuthoringState.RESEARCHING:
        return prefix + render_authoring_research(session, width, ascii_only=ascii_only)
    if session.state == AuthoringState.QUALITY_CHECKING and session.quality_result:
        return prefix + render_authoring_quality(
            session, session.quality_result, width, ascii_only=ascii_only
        )
    if session.state == AuthoringState.READY:
        return prefix + render_authoring_ready(session, width, ascii_only=ascii_only)
    return prefix


def _start(
    intent: SkillAuthoringIntent,
    *,
    session_id: str,
    intents: tuple[SkillAuthoringIntent, ...],
    position: int,
    workspace: Path,
    registered_tools: set[str],
    registry: AuthoringSessionRegistry,
    width: int,
    ascii_only: bool,
    shaping_client: Any = None,
) -> AuthoringTurnResult:
    session = create_authoring_session(
        intent,
        session_id=session_id,
        queue_position=position,
        queue_total=len(intents),
        queue_items=intents,
        registry=registry,
    )
    existing = load_domain_skills(workspace=workspace)
    snapshot = inspect_local_context(workspace, registered_tools, existing)
    decision = decide_research_need(intent, snapshot)
    from .shaping import build_shaping_plan

    shaping_plan = build_shaping_plan(intent, snapshot, client=shaping_client, workspace=workspace)
    questions = shaping_plan.questions
    session = replace(
        session,
        state=AuthoringState.SHAPING,
        shaping_gaps=tuple(question.key for question in questions),
        shaping_questions=questions,
        research_decision=decision,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    registry.save(session)
    return AuthoringTurnResult(
        True,
        _render(session, width, ascii_only),
        view=_authoring_view(session),
    )


def synthesize_skill_proposal_content(
    subject: str,
    target_name: str,
    shaping_answers: dict[str, str],
    workspace_configs: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Synthesize specific, non-boilerplate when_to_use, steps, triggers, and verification."""
    sub = (subject or target_name).lower()
    tname = target_name or subject

    # 1. Planning, specs, architecture
    if any(k in sub or k in tname for k in ("plan", "spec", "roadmap", "arkitektur", "architecture", "planering")):
        location = shaping_answers.get("location") or "docs/plans/"
        when_to_use = (
            "When structuring, authoring, or validating technical implementation plans, "
            "architecture roadmaps, and project specifications."
        )
        steps = (
            f"Define explicit goals, non-goals, TCB boundaries, and preconditions in {location}.",
            "Structure modular implementation sections with before/after state and ASCII architectural mockups.",
            "Establish step-by-step progress tracking, test verification gates, and rollback criteria.",
        )
        verification = (
            "Verify plan structure against repository standards, ADR compliance, and verification checkpoints.",
        )
        triggers = ("planning", "planering", "planning-files", tname)
        return when_to_use, steps, triggers, verification

    # 2. Git, branch, rebase, squash
    if any(k in sub or k in tname for k in ("git", "rebase", "squash", "commit", "branch", "merge")):
        when_to_use = (
            "When organizing, rebasing, squashing, or structuring git commits and branch history."
        )
        steps = (
            "Inspect git status, commit history, and branch topology before rebasing.",
            "Perform clean interactive rebase, squash fixup commits, and craft atomic commit messages.",
            "Verify working tree cleanliness and run regression test suite before pushing.",
        )
        verification = (
            "Verify git log shows clean linear history and test suite passes 100%.",
        )
        triggers = ("git rebase", "squash", "git workflow", tname)
        return when_to_use, steps, triggers, verification

    # 3. Database, postgres, sql, migrations
    if any(k in sub or k in tname for k in ("data", "database", "postgres", "sql", "migrat", "migrer", "query", "schema")):
        when_to_use = (
            "When designing, optimizing, reviewing, or migrating database schemas, indexes, and SQL queries."
        )
        steps = (
            "Analyze query execution plans (EXPLAIN), table schemas, and indexing strategies.",
            "Write safe, transactional migration scripts with forward and backward compatibility.",
            "Validate query latency, data integrity, and index utilization under realistic workload.",
        )
        verification = (
            "Verify query plan avoids full table scans and database migrations execute cleanly.",
        )
        triggers = ("database", "sql query", "database migration", tname)
        return when_to_use, steps, triggers, verification

    # 4. B2B, outreach, sales, marketing
    if any(k in sub or k in tname for k in ("b2b", "outreach", "sales", "marknad", "marketing", "lead", "kund")):
        when_to_use = (
            "When planning, writing, or reviewing B2B outreach messaging, sales communication, and value propositions."
        )
        steps = (
            "Identify target profile, ICP pain points, and specific value proposition.",
            "Craft personalized, high-clarity communication with direct value delivery and call to action.",
            "Review message brevity, tone, and compliance with outreach standards.",
        )
        verification = (
            "Verify messaging clarity, audience relevance, and call-to-action precision.",
        )
        triggers = ("b2b outreach", "sales outreach", "marketing", tname)
        return when_to_use, steps, triggers, verification

    # 5. Customer support
    if any(k in sub or k in tname for k in ("support", "kundsupport", "helpdesk", "troubleshoot", "service")):
        when_to_use = (
            "When diagnosing customer inquiries, troubleshooting service issues, and drafting resolution guidance."
        )
        steps = (
            "Diagnose customer inquiry, reproduce reported issue, and identify root cause.",
            "Formulate clear, empathetic step-by-step resolution instructions.",
            "Validate user resolution and document knowledge base pattern for future inquiries.",
        )
        verification = (
            "Verify issue resolution, customer clarity, and support documentation accuracy.",
        )
        triggers = ("customer support", "kundsupport", "troubleshooting", tname)
        return when_to_use, steps, triggers, verification

    # 6. Release & checklists
    if any(k in sub or k in tname for k in ("release", "checklist", "deploy", "checklista")):
        when_to_use = (
            "When validating release readiness, running pre-deployment checklists, and executing deployment gates."
        )
        steps = (
            "Audit release diff, dependency versions, and environmental configurations.",
            "Execute complete automated test suite, linting, and security gate checks.",
            "Verify smoke test health endpoints post-release and confirm rollback readiness.",
        )
        verification = (
            "Verify release checklist criteria are met and smoke tests pass 100%.",
        )
        triggers = ("release review", "deployment checklist", "release checklist", tname)
        return when_to_use, steps, triggers, verification

    # 7. Dynamic Synthesis from user inputs & shaping answers
    focus = shaping_answers.get("focus") or f"Execute structured {subject} workflow."
    when_to_use = (
        f"When executing {subject} tasks requiring structured domain validation and workflow consistency."
    )
    steps = (
        f"Analyze project requirements, constraints, and dependencies for {subject}.",
        focus.rstrip(".") + ".",
        f"Verify output quality and adherence to {subject} standards.",
    )
    verification = (
        f"Verify that {subject} deliverables meet all specified functional and quality criteria.",
    )
    triggers = (subject, tname)
    return when_to_use, steps, triggers, verification


def _build_ready(
    session: AuthoringSession,
    *,
    workspace: Path,
    registered_tools: set[str],
    registry: AuthoringSessionRegistry,
    width: int,
    ascii_only: bool,
) -> AuthoringTurnResult:
    existing = load_domain_skills(workspace=workspace)
    builtins = load_builtins()
    intent = session.queue_items[session.queue_position - 1]
    resolution = resolve_scope_and_overlap(
        replace(intent, target_scope=session.target_scope),
        compute_workspace_key(workspace),
        existing,
        builtins,
    )
    if resolution.status != "RESOLVED":
        failed = replace(
            session,
            state=AuthoringState.FAILED,
            failure_reason=resolution.reason,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        registry.save(failed)
        return AuthoringTurnResult(
            True,
            f"Skill authoring stopped: {resolution.reason}",
        )

    snapshot = inspect_local_context(workspace, registered_tools, existing)
    target_name = resolution.target_name or session.request_subject
    when_to_use, steps, triggers, verification = synthesize_skill_proposal_content(
        subject=session.request_subject,
        target_name=target_name,
        shaping_answers=session.shaping_answers,
        workspace_configs=snapshot.config_files_found,
    )

    common = dict(
        name=target_name,
        domain="general",
        intent=session.request_subject,
        scope=resolution.target_scope or session.target_scope,
        steps=steps,
        required_tools=(),
        when_to_use=when_to_use,
        triggers=triggers,
        verification=verification,
    )
    if session.research_sources:
        proposal = ResearchSkillProposal(
            **common,
            source_refs=session.research_sources,
        )
    else:
        proposal = LocalSkillProposal(**common)

    draft = SkillFactory().build_from_proposal(proposal, resolution, existing)
    session = transition_session(
        session,
        AuthoringState.BUILDING,
        registry=registry,
    ) if session.state in (AuthoringState.SHAPING, AuthoringState.RESEARCHING) else session
    session = transition_session(
        session,
        AuthoringState.QUALITY_CHECKING,
        draft=draft,
        registry=registry,
    )
    quality = run_deterministic_quality_checks(
        draft,
        builtins=builtins,
        registered_tools=registered_tools,
    )
    session = replace(
        session,
        quality_result=quality,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    registry.save(session)
    if quality.passed:
        session = transition_session(session, AuthoringState.READY, registry=registry)
    return AuthoringTurnResult(
        True,
        _render(session, width, ascii_only),
        view=_authoring_view(session),
    )


def _next_or_finish(
    session: AuthoringSession,
    *,
    workspace: Path,
    registered_tools: set[str],
    registry: AuthoringSessionRegistry,
    width: int,
    ascii_only: bool,
    shaping_client: Any = None,
) -> AuthoringTurnResult | None:
    if session.queue_position >= session.queue_total:
        registry.remove(session.session_id)
        return None
    return _start(
        session.queue_items[session.queue_position],
        session_id=session.session_id,
        intents=session.queue_items,
        position=session.queue_position + 1,
        workspace=workspace,
        registered_tools=registered_tools,
        registry=registry,
        width=width,
        ascii_only=ascii_only,
        shaping_client=shaping_client,
    )


def handle_authoring_turn(
    user_text: str,
    *,
    session_id: str,
    workspace: Path,
    registered_tools: set[str],
    width: int = 80,
    ascii_only: bool = False,
    registry: AuthoringSessionRegistry | None = None,
    shaping_client: Any = None,
) -> AuthoringTurnResult:
    """Advance explicit authoring without canonical writes before consent."""
    try:
        reg = registry or get_authoring_registry()
        session = reg.get(session_id)

        if session is not None and session.state in _TERMINAL_STATES:
            next_result = _next_or_finish(
                session,
                workspace=workspace,
                registered_tools=registered_tools,
                registry=reg,
                width=width,
                ascii_only=ascii_only,
                shaping_client=shaping_client,
            )
            if next_result is not None:
                return next_result
            session = None

        if session is None:
            intents = tuple(detect_batch_skill_intent(user_text))
            if not intents:
                return AuthoringTurnResult(False)
            return _start(
                intents[0],
                session_id=session_id,
                intents=intents,
                position=1,
                workspace=workspace,
                registered_tools=registered_tools,
                registry=reg,
                width=width,
                ascii_only=ascii_only,
                shaping_client=shaping_client,
            )

        answer = (user_text or "").strip()
        lower = answer.casefold()
        if lower in {"cancel", "decline", "stop", "avbryt", "nej", "d"}:
            cancelled = transition_session(session, AuthoringState.CANCELLED, registry=reg)
            next_result = _next_or_finish(
                cancelled,
                workspace=workspace,
                registered_tools=registered_tools,
                registry=reg,
                width=width,
                ascii_only=ascii_only,
            )
            return next_result or AuthoringTurnResult(True, "Skill authoring cancelled.")

        if session.state in {AuthoringState.SHAPING, AuthoringState.EDITING}:
            answers = {"focus": answer}
            if "global" in lower:
                answers["scope"] = "global"
            elif "project" in lower or "projekt" in lower or session.target_scope == "unresolved":
                answers["scope"] = "project"
            session = apply_shaping_answers(session, answers, registry=reg)
            decision = session.research_decision
            if decision and decision.needs_research:
                session = transition_session(session, AuthoringState.RESEARCHING, registry=reg)
                return AuthoringTurnResult(True, _render(session, width, ascii_only))
            return _build_ready(
                session,
                workspace=workspace,
                registered_tools=registered_tools,
                registry=reg,
                width=width,
                ascii_only=ascii_only,
            )

        if session.state == AuthoringState.RESEARCHING:
            if lower in {"y", "yes", "ja", "research", "sök", "sok"}:
                now = datetime.now(timezone.utc)
                choice = (
                    ResearchChoice.EXPLICITLY_REQUESTED
                    if session.queue_items[session.queue_position - 1].requires_research
                    else ResearchChoice.USER_APPROVED
                )
                grant = ResearchGrant(
                    grant_id=f"grant_{uuid.uuid4().hex[:12]}",
                    session_id=session.session_id,
                    purpose=f"skill_authoring:{session.request_subject}",
                    choice=choice,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(minutes=5)).isoformat(),
                )
                session = replace(session, research_grant=grant, updated_at=now.isoformat())
                reg.save(session)
                queries = session.research_decision.search_queries if session.research_decision else ()
                return AuthoringTurnResult(True, "Research authorized.", tuple(queries))
            if lower in {"n", "no", "nej", "local", "lokalt"}:
                grant = ResearchGrant(
                    grant_id=f"grant_{uuid.uuid4().hex[:12]}",
                    session_id=session.session_id,
                    purpose=f"skill_authoring:{session.request_subject}",
                    choice=ResearchChoice.DECLINED_WITH_LIMITATION,
                )
                session = replace(session, research_grant=grant)
                reg.save(session)
                return _build_ready(
                    session,
                    workspace=workspace,
                    registered_tools=registered_tools,
                    registry=reg,
                    width=width,
                    ascii_only=ascii_only,
                )
            return AuthoringTurnResult(True, _render(session, width, ascii_only))

        if session.state == AuthoringState.QUALITY_CHECKING:
            if lower in {"e", "edit", "ändra", "andra"}:
                edited = transition_session(session, AuthoringState.EDITING, registry=reg)
                return AuthoringTurnResult(True, _render(edited, width, ascii_only))
            return AuthoringTurnResult(True, _render(session, width, ascii_only))

        if session.state == AuthoringState.READY:
            if lower in {"u", "use", "use now", "använd", "anvand", "använd nu"}:
                disposition = "equip"
            elif lower in {"v", "vault", "save", "save to vault", "spara"}:
                disposition = "vault"
            elif lower in {"e", "edit", "ändra", "andra"}:
                edited = transition_session(session, AuthoringState.EDITING, registry=reg)
                return AuthoringTurnResult(True, _render(edited, width, ascii_only))
            else:
                return AuthoringTurnResult(True, _render(session, width, ascii_only))

            session, auth = authorize_publication(
                session,
                disposition=disposition,
                registry=reg,
            )
            args = {
                "session_id": session.session_id,
                "authorization_id": auth.authorization_id,
                "payload_hash": session.draft_hash,
                "desired_disposition": disposition,
                "skill": session.draft.skill.to_dict(),
            }
            return AuthoringTurnResult(True, _render(session, width, ascii_only), publication_args=args)

        return AuthoringTurnResult(True, _render(session, width, ascii_only))
    except Exception as exc:
        return AuthoringTurnResult(
            True,
            f"Skill authoring could not proceed: {exc}. You can try again or describe what you want.",
        )


def handle_authoring_action(
    action: AuthoringAction,
    *,
    session_id: str,
    workspace: Path,
    registered_tools: set[str],
    width: int = 80,
    ascii_only: bool = False,
    registry: AuthoringSessionRegistry | None = None,
) -> AuthoringTurnResult:
    """Advance authoring from a typed fullscreen action, never fabricated chat text."""
    reg = registry or get_authoring_registry()
    session = reg.get(session_id)
    if session is None:
        return AuthoringTurnResult(False)

    if action.kind is AuthoringActionKind.ANSWER:
        if session.state not in {AuthoringState.SHAPING, AuthoringState.EDITING}:
            return AuthoringTurnResult(True, view=_authoring_view(session))
        questions = _session_questions(session)
        active = next(
            (question for question in questions if question.key not in session.shaping_answers),
            None,
        )
        free_text_answer = (
            active is not None
            and active.key == "clarification"
            and not active.options
            and 3 <= len(action.value.strip()) <= 500
        )
        if active is None or action.key != active.key or (
            not free_text_answer and action.value not in active.options
        ):
            return AuthoringTurnResult(True, view=_authoring_view(session))
        session = apply_shaping_answers(
            session,
            {active.key: action.value.strip()},
            registry=reg,
        )
        remaining = [
            question
            for question in questions
            if question.key not in session.shaping_answers
        ]
        if remaining:
            return AuthoringTurnResult(
                True,
                _render(session, width, ascii_only),
                view=_authoring_view(session),
            )
        decision = session.research_decision
        if decision and decision.needs_research:
            session = transition_session(session, AuthoringState.RESEARCHING, registry=reg)
            return AuthoringTurnResult(
                True,
                _render(session, width, ascii_only),
                view=_authoring_view(session),
            )
        return _build_ready(
            session,
            workspace=workspace,
            registered_tools=registered_tools,
            registry=reg,
            width=width,
            ascii_only=ascii_only,
        )

    if action.kind is AuthoringActionKind.EDIT and session.state == AuthoringState.READY:
        questions = _session_questions(session)
        answers = dict(session.shaping_answers)
        answered = [question for question in questions if question.key in answers]
        if answered:
            answers.pop(answered[-1].key, None)
        session = transition_session(session, AuthoringState.EDITING, registry=reg)
        session = replace(
            session,
            shaping_answers=answers,
            publication_authorization=None,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        reg.save(session)
        return AuthoringTurnResult(
            True,
            _render(session, width, ascii_only),
            view=_authoring_view(session),
        )

    text_actions = {
        AuthoringActionKind.RESEARCH: "yes",
        AuthoringActionKind.LOCAL_ONLY: "no",
        AuthoringActionKind.PUBLISH_USE: "use now",
        AuthoringActionKind.PUBLISH_VAULT: "vault",
        AuthoringActionKind.DECLINE: "decline",
    }
    if action.kind in text_actions:
        result = handle_authoring_turn(
            text_actions[action.kind],
            session_id=session_id,
            workspace=workspace,
            registered_tools=registered_tools,
            width=width,
            ascii_only=ascii_only,
            registry=reg,
        )
        current = reg.get(session_id)
        if current is not None and result.view is None:
            return replace(result, view=_authoring_view(current))
        return result

    if action.kind is AuthoringActionKind.BACK:
        questions = _session_questions(session)
        answered = [question for question in questions if question.key in session.shaping_answers]
        if session.state in {AuthoringState.READY, AuthoringState.RESEARCHING}:
            session = transition_session(session, AuthoringState.EDITING, registry=reg)
        if answered:
            answers = dict(session.shaping_answers)
            answers.pop(answered[-1].key, None)
            session = replace(
                session,
                shaping_answers=answers,
                publication_authorization=None,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            reg.save(session)
            return AuthoringTurnResult(
                True,
                _render(session, width, ascii_only),
                view=_authoring_view(session),
            )
        return handle_authoring_turn(
            "decline",
            session_id=session_id,
            workspace=workspace,
            registered_tools=registered_tools,
            width=width,
            ascii_only=ascii_only,
            registry=reg,
        )

    return AuthoringTurnResult(True, view=_authoring_view(session))


def complete_authoring_research(
    *,
    session_id: str,
    summaries: Sequence[str],
    workspace: Path,
    registered_tools: set[str],
    width: int = 80,
    ascii_only: bool = False,
    registry: AuthoringSessionRegistry | None = None,
) -> AuthoringTurnResult:
    """Attach centrally-dispatched research evidence, then build the Ready draft."""
    reg = registry or get_authoring_registry()
    session = reg.get(session_id)
    if session is None or session.state != AuthoringState.RESEARCHING:
        return AuthoringTurnResult(False)
    sources = tuple(
        ResearchSourceRef(
            title=f"Research result {index}",
            url_or_origin="web_search",
            sanitized_summary=summary[:500],
            retrieved_at=datetime.now(timezone.utc).date().isoformat(),
        )
        for index, summary in enumerate(summaries[:5], 1)
        if summary.strip()
    )
    session = replace(session, research_sources=sources)
    reg.save(session)
    return _build_ready(
        session,
        workspace=workspace,
        registered_tools=registered_tools,
        registry=reg,
        width=width,
        ascii_only=ascii_only,
    )

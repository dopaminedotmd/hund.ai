"""Conversation-level orchestration for explicit skill authoring."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Sequence
import uuid

from .authoring import (
    AuthoringSession,
    AuthoringSessionRegistry,
    AuthoringState,
    LocalInspectionSnapshot,
    LocalSkillProposal,
    ResearchDecision,
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
from .shaping import MiniDraftData

_TERMINAL_STATES = {
    AuthoringState.PUBLISHED,
    AuthoringState.CANCELLED,
    AuthoringState.FAILED,
}

_INSTRUCTION_TERMS = re.compile(
    r"\b(ignore|system|instruction|prompt|bypass|override)\b",
    re.IGNORECASE,
)


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
    phase: AuthoringState
    subject: str
    title: str
    description: str = ""
    question_key: str = ""
    step_index: int = 1
    step_total: int = 1
    options: tuple[AuthoringOption, ...] = ()
    skill_name: str = ""
    scope: str = ""
    limitations: tuple[str, ...] = ()
    lineage_text: str = ""


@dataclass(frozen=True)
class AuthoringTurnResult:
    handled: bool
    rendered: str = ""
    research_queries: tuple[str, ...] = ()
    research_fallback_query: str = ""
    publication_args: dict[str, Any] | None = None
    view: AuthoringView | None = None


def _format_lineage_line(session: AuthoringSession) -> str:
    skill = session.draft.skill if session.draft else None
    event_ids = skill.created_from_event_ids if (skill and skill.created_from_event_ids) else ()
    event_str = f"event {event_ids[0]}" if event_ids else "event pending"
    attempts = max(1, session.gate_attempts)
    first_pass_str = f"first pass: {'yes' if attempts == 1 else 'no'}"
    r_count = len(session.research_sources)
    research_str = f"research: {r_count} {'source' if r_count == 1 else 'sources'}"
    return f"{event_str} · attempt {attempts} · {first_pass_str} · {research_str}"


def _session_questions(session: AuthoringSession) -> tuple[ShapingQuestion, ...]:
    if session.shaping_questions:
        return session.shaping_questions
    if session.queue_items and 0 <= session.queue_position - 1 < len(session.queue_items):
        intent = session.queue_items[session.queue_position - 1]
        return extract_shaping_questions(intent)
    return ()


def _authoring_view(session: AuthoringSession) -> AuthoringView:
    if session.state in {AuthoringState.SHAPING, AuthoringState.EDITING}:
        questions = _session_questions(session)
        if session.mini_draft is not None and not session.mini_draft_confirmed:
            if session.shaping_answers.get("mini_draft_action") == "correcting":
                return AuthoringView(
                    session_id=session.session_id,
                    phase=AuthoringState.SHAPING,
                    subject=session.request_subject,
                    title="Correct draft (free text)",
                    description="Type your correction in the input field.",
                    question_key="correct_mini_draft",
                    step_index=1,
                    step_total=1,
                    options=(),
                )
            steps_desc = "\n".join(f"{i}. {s}" for i, s in enumerate(session.mini_draft.steps, 1))
            return AuthoringView(
                session_id=session.session_id,
                phase=AuthoringState.SHAPING,
                subject=session.request_subject,
                title=f'Draft — "{session.request_subject}"',
                description=f"{session.mini_draft.when_to_use}\n\n{steps_desc}",
                question_key="mini_draft",
                step_index=1,
                step_total=1,
                options=(
                    AuthoringOption(AuthoringActionKind.ANSWER, "Continue with this draft", "continue"),
                    AuthoringOption(AuthoringActionKind.ANSWER, "Correct draft (free text)", "correct"),
                ),
            )
        if not questions or all(q.key in session.shaping_answers for q in questions):
            return AuthoringView(
                session_id=session.session_id,
                phase=AuthoringState.SHAPING,
                subject=session.request_subject,
                title="Capability Confirmed",
                description="Deriving procedure and verification checks...",
                question_key="confirmed",
                step_index=1,
                step_total=1,
                options=(),
            )
        active_index = next(
            (index for index, question in enumerate(questions) if question.key not in session.shaping_answers),
            0,
        )
        question = questions[active_index]
        return AuthoringView(
            session_id=session.session_id,
            phase=AuthoringState.SHAPING,
            subject=session.request_subject,
            title=question.title,
            description=f"Help: {question.help_text}" if question.help_text else "",
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
                AuthoringOption(AuthoringActionKind.PUBLISH_USE, "Publish & use now"),
                AuthoringOption(AuthoringActionKind.PUBLISH_VAULT, "Save to vault"),
                AuthoringOption(AuthoringActionKind.EDIT, "Edit draft"),
                AuthoringOption(AuthoringActionKind.DECLINE, "Decline"),
            ),
            skill_name=skill.name if skill else session.request_subject,
            scope=skill.scope if skill else session.target_scope,
            description=skill.when_to_use if skill else "",
            limitations=tuple(getattr(research, "limitations", ()) or ()),
            lineage_text=_format_lineage_line(session),
        )
    if session.state == AuthoringState.FAILED:
        return AuthoringView(
            session_id=session.session_id,
            phase=AuthoringState.FAILED,
            subject=session.request_subject,
            title="Failed",
            description=session.failure_reason or "Skill authoring failed.",
            options=(
                AuthoringOption(AuthoringActionKind.BACK, "Close"),
            ),
            question_key="failed",
        )
    if session.state == AuthoringState.CANCELLED:
        return AuthoringView(
            session_id=session.session_id,
            phase=AuthoringState.CANCELLED,
            subject=session.request_subject,
            title="Cancelled",
            description="Skill authoring cancelled.",
            options=(
                AuthoringOption(AuthoringActionKind.BACK, "Close"),
            ),
            question_key="cancelled",
        )
    if session.state == AuthoringState.PUBLISHED:
        return AuthoringView(
            session_id=session.session_id,
            phase=AuthoringState.PUBLISHED,
            subject=session.request_subject,
            title="Published",
            description="Skill published successfully.",
            options=(
                AuthoringOption(AuthoringActionKind.BACK, "Close"),
            ),
            question_key="published",
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
        view = _authoring_view(session)
        if session.mini_draft is not None and not session.mini_draft_confirmed:
            from ..ui.skill_authoring import render_authoring_stepper

            return prefix + render_authoring_stepper(view, width=width, ascii_only=ascii_only)
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
    width: int = 80,
    ascii_only: bool = False,
    shaping_client: Any = None,
    client: Any = None,
    run_id: str | None = None,
    initial_batch_tokens: int = 0,
) -> AuthoringTurnResult:
    if initial_batch_tokens > 50000:
        failed_session = create_authoring_session(
            intent,
            session_id=session_id,
            queue_position=position,
            queue_total=len(intents),
            queue_items=intents,
            registry=registry,
        )
        failed_session = transition_session(failed_session, AuthoringState.FAILED, registry=registry)
        failed_session = replace(
            failed_session,
            failure_reason="Batch token budget of 50000 input tokens exceeded.",
            batch_input_tokens=initial_batch_tokens,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        registry.save(failed_session)
        return AuthoringTurnResult(
            True,
            "Skill authoring failed: Batch token budget of 50000 input tokens exceeded.",
            view=_authoring_view(failed_session),
        )

    session = create_authoring_session(
        intent,
        session_id=session_id,
        queue_position=position,
        queue_total=len(intents),
        queue_items=intents,
        registry=registry,
    )
    session = replace(session, batch_input_tokens=initial_batch_tokens)
    existing = load_domain_skills(workspace=workspace)
    snapshot = inspect_local_context(workspace, registered_tools, existing)
    from .shaping import build_shaping_plan

    shaping_plan = build_shaping_plan(intent, snapshot, client=shaping_client, workspace=workspace, run_id=run_id)
    if shaping_plan.failed:
        failed_session = transition_session(session, AuthoringState.FAILED, registry=registry)
        failed_session = replace(
            failed_session,
            failure_reason=shaping_plan.failure_reason,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        registry.save(failed_session)
        return AuthoringTurnResult(
            True,
            f"Skill authoring failed: {shaping_plan.failure_reason or 'Shaping plan failed.'}",
            view=_authoring_view(failed_session),
        )

    questions = shaping_plan.questions
    decision = ResearchDecision(
        needs_research=bool(shaping_plan.research_queries),
        reason="Identified knowledge gap requires research" if shaping_plan.research_queries else "No research needed",
        search_queries=shaping_plan.research_queries,
    )
    session = replace(
        session,
        state=AuthoringState.SHAPING,
        mini_draft=shaping_plan.mini_draft,
        mini_draft_confirmed=False if shaping_plan.mini_draft is not None else True,
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
    *,
    client: Any = None,
    knowledge_packet: dict[str, Any] | None = None,
    mini_draft: MiniDraftData | None = None,
    research_sources: Sequence[ResearchSourceRef] | None = None,
    gate_feedback: Sequence[str] | None = None,
    run_id: str | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Synthesize specific, grounded when_to_use, steps, triggers, verification, and examples."""
    if client is None:
        raise ValueError("Provider client required for skill proposal synthesis")

    craft_rules = [
        "1. Define one narrow capability and a when_to_use that distinguishes matching from non-matching tasks.",
        "2. Write 2–8 concrete ordered steps; include only instructions that change an execution decision. Embed conditional decision rules (e.g. 'If condition then action') where versions, tools, or variants diverge.",
        "3. Include anti-pattern warnings directly in steps ('Do not X; instead Y') for common domain pitfalls or deprecated methods.",
        "4. Reference canonical project anchor files (e.g. build scripts, config files) in early steps when relevant to the domain.",
        "5. Use 1–12 precise routing triggers; add Swedish aliases only when useful and never use catchalls.",
        "6. Include 1–2 realistic golden examples with expected outcomes.",
        "7. Include 2–3 binary verification checks; every claimed result must be decidable as pass or fail.",
        "8. Keep canonical content strictly in English. Never echo non-English terms from the user input (e.g. translate 'bättre' to 'improve/better', 'skapa' to 'create'). Never add secrets, permissions, banned actions or speculative edge cases.",
        "9. Ground all version claims strictly in research summaries or user input. Version strings from user (e.g. '26.2') are opaque identifiers: preserve them verbatim, never add or remove prefixes (never rewrite 26.2 to 1.26.2). If research summaries confirm the user's version, use it verbatim. If research summaries do not confirm it, use the latest concrete version confirmed by research and explicitly note the correction in when_to_use (e.g. 'targets Minecraft <version> as declared in user project / latest verified release'). Never write an unverified version without grounding.",
        "10. Anti-slop and concrete design standards: For UI, styling, and design skills, ban generic AI aesthetic platitudes and marketing buzzwords. Require concrete aesthetic choices, deliberate typographic hierarchies, and intentional spacing rules.",
    ]
    system_prompt = (
        "You are Hund's canonical skill synthesis engine.\n"
        "CRITICAL LANGUAGE & TRANSLATION RULE: ALL fields in the output (when_to_use, steps, triggers, verification, examples) "
        "MUST ALWAYS be written strictly in ENGLISH, regardless of the language used in the user's input, shaping answers, or conversation. "
        "If user input contains non-English words (e.g. Swedish 'bättre', 'skapa'), translate all concepts to English. NEVER echo non-English terms into canonical fields.\n"
        "ANTI-SLOP & TECHNICAL NAMING RULES:\n"
        "- Ban marketing buzzwords (e.g. 'extreme', 'high-design', 'best', 'super', 'value') from skill names, steps, and triggers.\n"
        "- Require concrete aesthetic choices, deliberate typography hierarchies, and intentional spacing rather than vague aesthetic claims.\n"
        "WORKSPACE RULE: The knowledge_packet contains facts about the CURRENT workspace (project_type, config_files, declared_dependencies, available_tools). "
        "These describe where Hund runs, NOT what the skill must be about. Synthesize around the confirmed mini-draft and user capability only. "
        "If the skill is about a domain outside the workspace (music, writing, design, ops on other systems, etc.), IGNORE project_type/config/dependencies entirely. "
        "Only use workspace facts when the skill is explicitly about this project's own code, tooling or repository.\n\n"
        "Adhere strictly to these craft rules:\n"
        + "\n".join(craft_rules)
        + "\n\n"
        "Return strictly JSON conforming to this schema with NO extra fields:\n"
        "{\n"
        '  "when_to_use": "20-300 chars in English describing exact capability boundaries",\n'
        '  "steps": ["Plain text step 1 without numbering prefix, max 200 chars", "Plain text step 2", ...] (2-8 items),\n'
        '  "triggers": ["precise trigger phrase 1", "precise trigger phrase 2", ...] (1-12 items),\n'
        '  "verification": ["Binary check 1 without numbering prefix, max 200 chars", "Binary check 2", ...] (2-3 items),\n'
        '  "examples": ["A concrete golden case with expected outcome, max 200 chars", "(optional) a second distinct golden case"]  (1-2 items)\n'
        "}"
    )

    if gate_feedback:
        system_prompt += (
            "\n\nCRITICAL REVISION INSTRUCTION: The previous draft failed quality gate checks with the following issues:\n"
            + "\n".join(f"- {fb}" for fb in gate_feedback)
            + "\nYou MUST address every issue above in this revision. "
            "If any feedback mentions non-English, Swedish, or prohibited characters, translate all such terms into proper English immediately."
        )

    from .scope import derive_technical_skill_name
    tech_target_name = derive_technical_skill_name(subject or target_name, shaping_answers=shaping_answers, base_name=target_name)

    data_payload: dict[str, Any] = {
        "subject": subject,
        "target_name": tech_target_name,
        "shaping_answers": {
            k: v for k, v in shaping_answers.items()
            if not _INSTRUCTION_TERMS.search(v)
        },
    }
    if knowledge_packet:
        data_payload["knowledge_packet"] = knowledge_packet
    if mini_draft:
        data_payload["confirmed_mini_draft"] = {
            "when_to_use": mini_draft.when_to_use,
            "steps": list(mini_draft.steps),
        }
    if research_sources:
        data_payload["research_summaries"] = [
            r.sanitized_summary for r in research_sources
        ]
    if gate_feedback:
        data_payload["gate_feedback"] = list(gate_feedback)

    user_prompt = json.dumps({"untrusted_data": data_payload}, ensure_ascii=False, indent=2)

    from ..providers.base import Message
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    import time
    t0 = time.time()
    result = client.complete(messages, tools=None, max_tokens=8000)
    latency_ms = int((time.time() - t0) * 1000)
    from .authoring import log_authoring_request
    log_authoring_request(client, result, "authoring_synthesis", run_id=run_id, latency_ms=latency_ms)

    raw_text = getattr(result, "text", None) or getattr(result, "content", None) or ""
    from .shaping import _extract_json_block
    from .authoring import SynthesisCallOutput
    json_text = _extract_json_block(raw_text)
    try:
        data = json.loads(json_text)
        if isinstance(data, dict):
            if isinstance(data.get("verification"), list) and len(data["verification"]) > 3:
                data["verification"] = data["verification"][:3]
            if isinstance(data.get("steps"), list) and len(data["steps"]) > 8:
                data["steps"] = data["steps"][:8]
            if isinstance(data.get("triggers"), list) and len(data["triggers"]) > 12:
                data["triggers"] = data["triggers"][:12]
            if isinstance(data.get("examples"), list) and len(data["examples"]) > 2:
                data["examples"] = data["examples"][:2]
        parsed = SynthesisCallOutput.model_validate(data)
    except Exception:
        parsed = SynthesisCallOutput.model_validate_json(json_text)

    return (
        parsed.when_to_use,
        tuple(parsed.steps),
        tuple(parsed.triggers),
        tuple(parsed.verification),
        tuple(parsed.examples),
    )


def _build_ready(
    session: AuthoringSession,
    *,
    workspace: Path,
    registered_tools: set[str],
    registry: AuthoringSessionRegistry,
    width: int = 80,
    ascii_only: bool = False,
    client: Any = None,
    run_id: str | None = None,
) -> AuthoringTurnResult:
    existing = load_domain_skills(workspace=workspace)
    builtins = load_builtins()
    if session.queue_items and 0 <= session.queue_position - 1 < len(session.queue_items):
        intent = session.queue_items[session.queue_position - 1]
    else:
        intent = SkillAuthoringIntent(
            operation="create",
            capability=session.request_subject,
            target_scope=session.target_scope,
            referenced_name=None,
            local_only=True,
            requires_research=False,
            confidence=1.0,
            raw_prompt=session.request_subject,
        )
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
            view=_authoring_view(failed),
        )

    snapshot = inspect_local_context(workspace, registered_tools, existing)
    from .scope import derive_technical_skill_name
    target_name = derive_technical_skill_name(
        session.request_subject,
        shaping_answers=session.shaping_answers,
        base_name=resolution.target_name,
    )

    # Quality loop: synthesis and gate check (up to 3 attempts if client is provided)
    max_gate_attempts = 3 if client is not None else 1
    gate_attempts = 0
    gate_feedback: list[str] = []
    draft = None
    quality = None

    while gate_attempts < max_gate_attempts:
        gate_attempts += 1
        try:
            when_to_use, steps, triggers, verification, examples = synthesize_skill_proposal_content(
                subject=session.request_subject,
                target_name=target_name,
                shaping_answers=session.shaping_answers,
                workspace_configs=snapshot.config_files_found,
                client=client,
                knowledge_packet=snapshot.to_dict() if hasattr(snapshot, "to_dict") else None,
                mini_draft=session.mini_draft,
                research_sources=session.research_sources,
                gate_feedback=gate_feedback if gate_feedback else None,
                run_id=run_id,
            )
        except Exception as exc:
            failed = replace(
                session,
                state=AuthoringState.FAILED,
                failure_reason=f"Synthesis failed: {exc}",
                gate_attempts=gate_attempts,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            registry.save(failed)
            return AuthoringTurnResult(
                True,
                f"Skill authoring failed: Synthesis error: {exc}",
                view=_authoring_view(failed),
            )

        req_tools = set()
        steps_text = " ".join(tuple(steps) + (when_to_use,)).casefold()
        file_edit_markers = (
            "write_file", "edit_file", "write file", "edit file", "modify file",
            "create file", "save file", "update file", "overwrite file",
            "skriv fil", "skapa fil", "ändra fil", "uppdatera fil",
        )
        if any(marker in steps_text for marker in file_edit_markers):
            req_tools.update({"write_file", "edit_file"})

        common = dict(
            name=target_name,
            domain="general",
            intent=session.request_subject,
            scope=resolution.target_scope or session.target_scope,
            steps=steps,
            required_tools=tuple(sorted(req_tools)),
            when_to_use=when_to_use,
            triggers=triggers,
            verification=verification,
            examples=examples,
        )
        if session.research_sources:
            proposal = ResearchSkillProposal(
                **common,
                source_refs=session.research_sources,
            )
        else:
            proposal = LocalSkillProposal(**common)

        active_resolution = replace(
            resolution,
            target_name=target_name,
            capability_id=f"{proposal.domain}/{target_name}",
        )
        draft = SkillFactory().build_from_proposal(proposal, active_resolution, existing)
        # Extract version context & research summaries
        raw_prompt = session.raw_prompt or ""
        _VERSION_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)+\b")
        user_stated_versions = set(_VERSION_TOKEN_RE.findall(f"{raw_prompt} {' '.join(session.shaping_answers.values())}"))
        research_summaries = [r.sanitized_summary for r in session.research_sources] if session.research_sources else []

        quality = run_deterministic_quality_checks(
            draft,
            builtins=builtins,
            registered_tools=registered_tools,
            raw_prompt=raw_prompt,
            shaping_answers=session.shaping_answers,
            research_summaries=research_summaries,
            declared_dependencies=snapshot.declared_dependencies,
            user_stated_versions=user_stated_versions,
        )
        if not quality.passed:
            gate_feedback = list(quality.failures) or ["Deterministic quality check failed."]
            continue

        if client is not None:
            from .authoring import run_llm_review_gate
            review = run_llm_review_gate(
                draft,
                client=client,
                run_id=run_id,
                research_summaries=research_summaries,
                user_stated_versions=user_stated_versions,
            )
            if not review.approved or review.score < 0.7:
                gate_feedback = list(review.issues) or ["Review gate score below threshold."]
                continue

        # Passed all gates!
        gate_feedback = []
        break

    if draft is None or quality is None or not quality.passed or gate_feedback:
        failure_msg = f"Quality gate failed after {gate_attempts} attempts: {'; '.join(gate_feedback)}" if gate_feedback else f"Quality gate failed after {gate_attempts} attempts."
        failed = replace(
            session,
            state=AuthoringState.FAILED,
            failure_reason=failure_msg,
            gate_attempts=gate_attempts,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        registry.save(failed)
        return AuthoringTurnResult(
            True,
            f"Skill authoring failed: {failure_msg}",
            view=_authoring_view(failed),
        )

    # Lineage fail-closed check
    if not run_id:
        failed = replace(
            session,
            state=AuthoringState.FAILED,
            failure_reason="Lineage error: missing run_id for proposal approval trace event",
            gate_attempts=gate_attempts,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        registry.save(failed)
        return AuthoringTurnResult(
            True,
            "Skill authoring failed: missing run_id for proposal approval trace event",
            view=_authoring_view(failed),
        )

    event_ids: tuple[str, ...] = ()
    try:
        from ..trace.events import record_event

        first_pass = (gate_attempts == 1)
        ev = record_event(
            workspace_id=str(workspace),
            session_id=session.session_id,
            run_id=run_id,
            actor="hund",
            event_type="proposal_approved",
            policy_version="1.0.0",
            payload_unredacted={
                "skill_name": draft.skill.name,
                "target_scope": draft.skill.scope,
                "gate_attempts": gate_attempts,
                "first_pass": first_pass,
                "gap_keys": list(session.shaping_answers.keys()),
                "research_source_count": len(session.research_sources),
            },
        )
        event_ids = (ev.event_id,)
    except Exception as exc:
        failed = replace(
            session,
            state=AuthoringState.FAILED,
            failure_reason=f"Lineage error: failed to record proposal_approved trace event: {exc}",
            gate_attempts=gate_attempts,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        registry.save(failed)
        return AuthoringTurnResult(
            True,
            f"Skill authoring failed: Lineage error: {exc}",
            view=_authoring_view(failed),
        )

    # Set created_from_event_ids on draft skill
    draft_skill_with_lineage = replace(draft.skill, created_from_event_ids=event_ids)
    draft = replace(draft, skill=draft_skill_with_lineage)

    session = replace(
        session,
        draft=draft,
        quality_result=quality,
        gate_attempts=gate_attempts,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    if session.state in (AuthoringState.RECOGNIZED, AuthoringState.SHAPING, AuthoringState.RESEARCHING, AuthoringState.EDITING):
        session = transition_session(session, AuthoringState.BUILDING, registry=registry)
    if session.state != AuthoringState.QUALITY_CHECKING:
        session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=registry)
    session = transition_session(session, AuthoringState.READY, draft=draft, registry=registry)
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
    client: Any = None,
    run_id: str | None = None,
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
        client=client,
        run_id=run_id,
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
    client: Any = None,
    run_id: str | None = None,
) -> AuthoringTurnResult:
    """Advance explicit authoring without canonical writes before consent."""
    try:
        reg = registry or get_authoring_registry()
        session = reg.get(session_id)
        active_client = client or shaping_client
        active_run_id = run_id or f"run_{session_id}"

        if session is not None and session.state in _TERMINAL_STATES:
            reg.remove(session.session_id)
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
                client=active_client,
                run_id=active_run_id,
            )

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
                client=active_client,
                run_id=active_run_id,
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
                shaping_client=active_client,
                client=active_client,
                run_id=active_run_id,
            )
            return next_result or AuthoringTurnResult(True, "Skill authoring cancelled.")

        if session.state in {AuthoringState.SHAPING, AuthoringState.EDITING}:
            if session.mini_draft is not None and not session.mini_draft_confirmed:
                if lower in {"continue", "continue with this draft", "continue with this definition", "1", "c"}:
                    session = replace(session, mini_draft_confirmed=True)
                    reg.save(session)
                    questions = _session_questions(session)
                    remaining = [
                        q for q in questions if q.key not in session.shaping_answers
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
                        client=active_client,
                        run_id=active_run_id,
                    )
                elif lower in {"correct", "correct draft", "correct draft (free text)", "correct definition", "2"}:
                    session = replace(
                        session,
                        shaping_answers={**session.shaping_answers, "mini_draft_action": "correcting"},
                    )
                    reg.save(session)
                    return AuthoringTurnResult(
                        True,
                        _render(session, width, ascii_only),
                        view=_authoring_view(session),
                    )
                elif session.shaping_answers.get("mini_draft_action") == "correcting" or "correct" in lower or len(answer) > 5:
                    answers = dict(session.shaping_answers)
                    answers.pop("mini_draft_action", None)
                    answers["correction"] = answer
                    session = replace(
                        session,
                        mini_draft_confirmed=True,
                        shaping_answers=answers,
                    )
                    reg.save(session)
                    questions = _session_questions(session)
                    remaining = [
                        q for q in questions if q.key not in session.shaping_answers
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
                        client=active_client,
                        run_id=active_run_id,
                    )

            questions = _session_questions(session)
            active = next(
                (question for question in questions if question.key not in session.shaping_answers),
                None,
            )
            key = active.key if active else "focus"
            answers = {key: answer}
            if "global" in lower:
                answers["scope"] = "global"
            elif "project" in lower or "projekt" in lower or session.target_scope == "unresolved":
                answers["scope"] = "project"
            session = apply_shaping_answers(session, answers, registry=reg)
            remaining = [
                q for q in questions if q.key not in session.shaping_answers
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
                return AuthoringTurnResult(True, _render(session, width, ascii_only), view=_authoring_view(session))
            return _build_ready(
                session,
                workspace=workspace,
                registered_tools=registered_tools,
                registry=reg,
                width=width,
                ascii_only=ascii_only,
                client=active_client,
                run_id=active_run_id,
            )

        if session.state == AuthoringState.RESEARCHING:
            if lower in {"y", "yes", "ja", "research", "sök", "sok"}:
                now = datetime.now(timezone.utc)
                choice = (
                    ResearchChoice.EXPLICITLY_REQUESTED
                    if (session.queue_items and session.queue_items[session.queue_position - 1].requires_research)
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
                from .shaping import refine_research_queries
                refined_queries, fallback_query = refine_research_queries(
                    subject=session.request_subject,
                    shaping_answers=session.shaping_answers,
                    mini_draft=session.mini_draft,
                    existing_queries=session.research_decision.search_queries if session.research_decision else (),
                    client=active_client,
                    run_id=active_run_id,
                )
                if session.research_decision:
                    session = replace(
                        session,
                        research_decision=replace(session.research_decision, search_queries=tuple(refined_queries)),
                    )
                    reg.save(session)
                return AuthoringTurnResult(
                    True,
                    "Research authorized.",
                    tuple(refined_queries),
                    research_fallback_query=fallback_query,
                )
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
                    client=active_client,
                    run_id=active_run_id,
                )
            return AuthoringTurnResult(True, _render(session, width, ascii_only))

        if session.state == AuthoringState.QUALITY_CHECKING:
            if lower in {"e", "edit", "ändra", "andra"}:
                edited = transition_session(session, AuthoringState.EDITING, registry=reg)
                return AuthoringTurnResult(True, _render(edited, width, ascii_only))
            return AuthoringTurnResult(True, _render(session, width, ascii_only))

        if session.state == AuthoringState.READY:
            if lower in {"u", "use", "use now", "publish & use now", "publish and use now", "publish & use", "publish and use", "använd", "anvand", "använd nu"}:
                disposition = "equip"
            elif lower in {"v", "vault", "save", "save to vault", "publish to vault", "spara"}:
                disposition = "vault"
            elif lower in {"e", "edit", "edit draft", "ändra", "andra", "redigera"}:
                questions = _session_questions(session)
                answers = dict(session.shaping_answers)
                answered = [question for question in questions if question.key in answers]
                if answered:
                    answers.pop(answered[-1].key, None)
                edited = transition_session(session, AuthoringState.EDITING, registry=reg)
                edited = replace(
                    edited,
                    shaping_answers=answers,
                    publication_authorization=None,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                reg.save(edited)
                return AuthoringTurnResult(True, _render(edited, width, ascii_only), view=_authoring_view(edited))
            elif lower in {"d", "decline", "cancel", "avböj", "avbryt"}:
                declined = transition_session(session, AuthoringState.CANCELLED, registry=reg)
                next_result = _next_or_finish(
                    declined,
                    workspace=workspace,
                    registered_tools=registered_tools,
                    registry=reg,
                    width=width,
                    ascii_only=ascii_only,
                    shaping_client=active_client,
                    client=active_client,
                    run_id=active_run_id,
                )
                if next_result is not None:
                    return next_result
                return AuthoringTurnResult(
                    True,
                    "Skill authoring cancelled.",
                    view=_authoring_view(declined),
                )
            else:
                return AuthoringTurnResult(True, _render(session, width, ascii_only), view=_authoring_view(session))

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
        if session is not None:
            failed = transition_session(session, AuthoringState.FAILED, registry=reg)
            failed = replace(
                failed,
                failure_reason=f"Skill authoring error: {exc}",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            reg.save(failed)
            return AuthoringTurnResult(
                True,
                f"Skill authoring failed: {exc}",
                view=_authoring_view(failed),
            )
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
    client: Any = None,
    run_id: str | None = None,
) -> AuthoringTurnResult:
    """Advance authoring from a typed fullscreen action, never fabricated chat text."""
    reg = registry or get_authoring_registry()
    session = reg.get(session_id)
    if session is None:
        return AuthoringTurnResult(False)

    active_run_id = run_id or f"run_{session_id}"

    if action.kind is AuthoringActionKind.ANSWER:
        if session.state not in {AuthoringState.SHAPING, AuthoringState.EDITING}:
            return AuthoringTurnResult(True, view=_authoring_view(session))

        if session.mini_draft is not None and not session.mini_draft_confirmed:
            val_lower = action.value.strip().lower()
            if action.key == "mini_draft" and val_lower in {"continue", "continue with this draft", "continue with this definition"}:
                session = replace(session, mini_draft_confirmed=True)
                reg.save(session)
                questions = _session_questions(session)
                remaining = [
                    q for q in questions if q.key not in session.shaping_answers
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
                    client=client,
                    run_id=active_run_id,
                )
            elif action.key == "mini_draft" and val_lower in {"correct", "correct draft", "correct draft (free text)", "correct definition"}:
                session = replace(
                    session,
                    shaping_answers={**session.shaping_answers, "mini_draft_action": "correcting"},
                )
                reg.save(session)
                return AuthoringTurnResult(
                    True,
                    _render(session, width, ascii_only),
                    view=_authoring_view(session),
                )
            elif action.key in {"correct_mini_draft", "mini_draft"}:
                answers = dict(session.shaping_answers)
                answers.pop("mini_draft_action", None)
                corr = action.value.strip()
                if corr:
                    answers["correction"] = corr
                session = replace(
                    session,
                    mini_draft_confirmed=True,
                    shaping_answers=answers,
                )
                reg.save(session)
                questions = _session_questions(session)
                remaining = [
                    q for q in questions if q.key not in session.shaping_answers
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
                    client=client,
                    run_id=active_run_id,
                )

        questions = _session_questions(session)
        active = next(
            (question for question in questions if question.key not in session.shaping_answers),
            None,
        )
        free_text_answer = (
            active is not None
            and active.key in {"clarification", "correct_mini_draft"}
            and not active.options
            and 1 <= len(action.value.strip()) <= 500
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
            client=client,
            run_id=active_run_id,
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
            client=client,
            run_id=run_id,
        )
        current = reg.get(session_id)
        if current is not None and result.view is None:
            return replace(result, view=_authoring_view(current))
        return result

    if action.kind is AuthoringActionKind.BACK:
        if session.state in _TERMINAL_STATES:
            reg.remove(session.session_id)
            return AuthoringTurnResult(True, f"Skill authoring {session.state}.", view=None)

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
            client=client,
            run_id=run_id,
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
    client: Any = None,
    run_id: str | None = None,
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
    active_run_id = run_id or f"run_{session_id}"
    return _build_ready(
        session,
        workspace=workspace,
        registered_tools=registered_tools,
        registry=reg,
        width=width,
        ascii_only=ascii_only,
        client=client,
        run_id=active_run_id,
    )

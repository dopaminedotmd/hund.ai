"""On-demand skill authoring — typed intents, proposals, receipts, state machine, and intent detection."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import textwrap
import threading
import tomllib
from typing import Any, Iterable, Optional, Sequence
import uuid

from pydantic import BaseModel, Field, field_validator

from ..learning.redactor import redact_text
from .contracts import (
    PublicationAuthorization,
    PublicationReceipt,
    QualityGateCheck,
    QualityGateResult,
    ResearchChoice,
    ResearchGrant,
    compute_payload_hash,
    normalize_publication_payload,
)
from .loader import load_builtins
from .model import BANNED_ACTIONS, Skill


class AuthoringState:
    RECOGNIZED = "recognized"
    SHAPING = "shaping"
    RESEARCHING = "researching"
    BUILDING = "building"
    QUALITY_CHECKING = "quality_checking"
    READY = "ready"
    EDITING = "editing"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    FAILED = "failed"


class IllegalStateTransitionError(ValueError):
    """Raised when an illegal transition is attempted on an authoring session."""


@dataclass(frozen=True)
class ShapingQuestion:
    key: str
    title: str
    help_text: str = ""
    options: tuple[str, ...] = ()
    default: str = ""
    user_input: str = ""


@dataclass(frozen=True)
class SkillAuthoringIntent:
    operation: str  # "create" | "update"
    capability: str
    target_scope: str  # "global" | "project" | "unresolved"
    referenced_name: str | None
    local_only: bool
    requires_research: bool
    confidence: float
    raw_prompt: str
    desired_disposition: str = "auto"  # "auto" | "equip" | "vault"


@dataclass(frozen=True)
class LocalInspectionSnapshot:
    workspace_name: str
    workspace_root: str
    config_files_found: tuple[str, ...]
    relevant_files: tuple[str, ...]
    registered_tools: tuple[str, ...]
    scoped_skills: tuple[str, ...]
    declared_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchDecision:
    needs_research: bool
    reason: str
    search_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalSkillProposal:
    name: str
    domain: str
    intent: str
    scope: str
    steps: tuple[str, ...]
    required_tools: tuple[str, ...]
    when_to_use: str
    triggers: tuple[str, ...]
    verification: tuple[str, ...]
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchSourceRef:
    title: str
    url_or_origin: str
    sanitized_summary: str
    retrieved_at: str


@dataclass(frozen=True)
class ResearchSkillProposal:
    name: str
    domain: str
    intent: str
    scope: str
    steps: tuple[str, ...]
    required_tools: tuple[str, ...]
    when_to_use: str
    triggers: tuple[str, ...]
    verification: tuple[str, ...]
    source_refs: tuple[ResearchSourceRef, ...]  # 1 to 5 references
    examples: tuple[str, ...] = ()


def _clean_list_item(item: Any) -> str:
    if item is None:
        return ""
    text = str(item).strip()
    return " ".join(text.split())


_INSTRUCTION_TERMS = re.compile(
    r"\b(ignore|system\s+prompt|disregard|override|jailbreak|eval|exec|import\s+os)\b",
    re.IGNORECASE,
)


class SynthesisCallOutput(BaseModel, extra="forbid"):
    when_to_use: str = Field(min_length=20, max_length=300)
    steps: list[str] = Field(min_length=2, max_length=8)
    triggers: list[str] = Field(min_length=1, max_length=12)
    verification: list[str] = Field(min_length=2, max_length=3)
    examples: list[str] = Field(default_factory=list, min_length=1, max_length=2)

    @field_validator("when_to_use")
    @classmethod
    def validate_when_to_use(cls, val: str) -> str:
        clean = " ".join(val.split())
        if not (20 <= len(clean) <= 300):
            raise ValueError("when_to_use must be between 20 and 300 characters")
        if _INSTRUCTION_TERMS.search(clean):
            raise ValueError("when_to_use contains instruction terms")
        return clean

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[str]) -> list[str]:
        cleaned = []
        for s in steps:
            c = " ".join(s.split())
            if not c or len(c) > 300:
                raise ValueError("each step must be between 1 and 300 characters")
            if _INSTRUCTION_TERMS.search(c):
                raise ValueError("step contains instruction terms")
            cleaned.append(c)
        if not (2 <= len(cleaned) <= 8):
            raise ValueError("steps must contain between 2 and 8 concrete steps")
        return cleaned

    @field_validator("triggers")
    @classmethod
    def validate_triggers(cls, triggers: list[str]) -> list[str]:
        cleaned = []
        seen_lower = set()
        for t in triggers:
            c = " ".join(t.split())
            if not c or len(c) > 120:
                raise ValueError("each trigger must be between 1 and 120 characters")
            if any(ord(ch) < 32 for ch in c):
                raise ValueError("trigger must not contain control characters")
            if not re.search(r"[\w\u00C0-\u017F]", c):
                raise ValueError("trigger must contain at least one alphanumeric character")
            if _INSTRUCTION_TERMS.search(c):
                raise ValueError("trigger contains instruction terms")
            if c.casefold() not in seen_lower:
                seen_lower.add(c.casefold())
                cleaned.append(c)
        if not (1 <= len(cleaned) <= 12):
            raise ValueError("triggers must contain between 1 and 12 unique triggers")
        return cleaned

    @field_validator("verification")
    @classmethod
    def validate_verification(cls, verification: list[str]) -> list[str]:
        cleaned = []
        for v in verification:
            c = " ".join(v.split())
            if not c or len(c) > 300:
                raise ValueError("each verification check must be between 1 and 300 characters")
            if _INSTRUCTION_TERMS.search(c):
                raise ValueError("verification contains instruction terms")
            cleaned.append(c)
        if not (2 <= len(cleaned) <= 3):
            raise ValueError("verification must contain between 2 and 3 items")
        return cleaned

    @field_validator("examples")
    @classmethod
    def validate_examples(cls, examples: list[str]) -> list[str]:
        cleaned = []
        for e in examples:
            c = " ".join(e.split())
            if c and len(c) <= 300 and not _INSTRUCTION_TERMS.search(c):
                cleaned.append(c)
        if not (1 <= len(cleaned) <= 2):
            raise ValueError("examples must contain between 1 and 2 golden cases")
        return cleaned


@dataclass(frozen=True)
class MiniDraftData:
    when_to_use: str
    steps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "when_to_use": self.when_to_use,
            "steps": list(self.steps),
        }


@dataclass(frozen=True)
class SkillDraft:
    action: str  # "CREATE" | "UPDATE"
    skill: Skill
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthoringSession:
    session_id: str
    user_id: str
    state: str
    request_subject: str
    raw_prompt: str
    target_scope: str = "unresolved"
    desired_disposition: str = "auto"
    draft: SkillDraft | None = None
    draft_hash: str | None = None
    mini_draft: MiniDraftData | None = None
    mini_draft_confirmed: bool = False
    gate_attempts: int = 0
    batch_input_tokens: int = 0
    shaping_gaps: tuple[str, ...] = ()
    shaping_questions: tuple[ShapingQuestion, ...] = ()
    shaping_answers: dict[str, str] = field(default_factory=dict)
    research_decision: ResearchDecision | None = None
    research_grant: ResearchGrant | None = None
    research_sources: tuple[ResearchSourceRef, ...] = ()
    quality_result: QualityGateResult | None = None
    publication_authorization: PublicationAuthorization | None = None
    publication_receipt: PublicationReceipt | None = None
    queue_position: int = 1
    queue_total: int = 1
    queue_items: tuple[SkillAuthoringIntent, ...] = ()
    failure_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    AuthoringState.RECOGNIZED: {
        AuthoringState.SHAPING,
        AuthoringState.RESEARCHING,
        AuthoringState.BUILDING,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.SHAPING: {
        AuthoringState.RESEARCHING,
        AuthoringState.BUILDING,
        AuthoringState.QUALITY_CHECKING,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.RESEARCHING: {
        AuthoringState.EDITING,
        AuthoringState.BUILDING,
        AuthoringState.QUALITY_CHECKING,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.BUILDING: {
        AuthoringState.QUALITY_CHECKING,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.QUALITY_CHECKING: {
        AuthoringState.READY,
        AuthoringState.EDITING,
        AuthoringState.BUILDING,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.READY: {
        AuthoringState.EDITING,
        AuthoringState.PUBLISHING,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.EDITING: {
        AuthoringState.QUALITY_CHECKING,
        AuthoringState.BUILDING,
        AuthoringState.READY,
        AuthoringState.CANCELLED,
        AuthoringState.FAILED,
    },
    AuthoringState.PUBLISHING: {
        AuthoringState.PUBLISHED,
        AuthoringState.READY,
        AuthoringState.FAILED,
    },
    AuthoringState.PUBLISHED: set(),
    AuthoringState.CANCELLED: set(),
    AuthoringState.FAILED: {
        AuthoringState.SHAPING,
        AuthoringState.BUILDING,
        AuthoringState.READY,
        AuthoringState.CANCELLED,
    },
}


class AuthoringSessionRegistry:
    """Thread-safe in-memory registry for active authoring sessions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, AuthoringSession] = {}

    def save(self, session: AuthoringSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> AuthoringSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def all_sessions(self) -> dict[str, AuthoringSession]:
        with self._lock:
            return dict(self._sessions)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def consume_publication_authorization(
        self,
        session_id: str,
        authorization_id: str,
        payload_hash: str,
    ) -> bool:
        """Atomically consume one exact-draft publication authorization."""
        with self._lock:
            session = self._sessions.get(session_id)
            auth = session.publication_authorization if session else None
            if (
                session is None
                or auth is None
                or auth.authorization_id != authorization_id
                or not auth.is_valid(payload_hash)
            ):
                return False
            self._sessions[session_id] = replace(
                session,
                publication_authorization=replace(auth, is_used=True),
                state=AuthoringState.PUBLISHING,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            return True


_GLOBAL_AUTHORING_REGISTRY = AuthoringSessionRegistry()


def get_authoring_registry() -> AuthoringSessionRegistry:
    return _GLOBAL_AUTHORING_REGISTRY


def create_authoring_session(
    intent: SkillAuthoringIntent,
    user_id: str = "default",
    session_id: str | None = None,
    registry: AuthoringSessionRegistry | None = None,
    queue_position: int = 1,
    queue_total: int = 1,
    queue_items: tuple[SkillAuthoringIntent, ...] = (),
) -> AuthoringSession:
    sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    session = AuthoringSession(
        session_id=sid,
        user_id=user_id,
        state=AuthoringState.RECOGNIZED,
        request_subject=intent.capability,
        raw_prompt=intent.raw_prompt,
        target_scope=intent.target_scope,
        desired_disposition=intent.desired_disposition,
        queue_position=queue_position,
        queue_total=queue_total,
        queue_items=queue_items,
        created_at=now,
        updated_at=now,
    )
    reg = registry or get_authoring_registry()
    reg.save(session)
    return session


def transition_session(
    session: AuthoringSession,
    next_state: str,
    draft: SkillDraft | None = None,
    receipt: PublicationReceipt | None = None,
    failure_reason: str | None = None,
    registry: AuthoringSessionRegistry | None = None,
) -> AuthoringSession:
    allowed = _ALLOWED_TRANSITIONS.get(session.state, set())
    if next_state not in allowed:
        raise IllegalStateTransitionError(
            f"Illegal state transition: cannot transition from '{session.state}' to '{next_state}'. Allowed: {sorted(allowed)}"
        )

    now = datetime.now(timezone.utc).isoformat()
    updates: dict[str, Any] = {
        "state": next_state,
        "updated_at": now,
    }

    if draft is not None:
        updates["draft"] = draft
        updates["draft_hash"] = compute_payload_hash(draft.skill.to_dict())
    elif session.draft is not None and session.draft_hash is None:
        updates["draft_hash"] = compute_payload_hash(session.draft.skill.to_dict())

    if receipt is not None:
        updates["publication_receipt"] = receipt

    if failure_reason is not None:
        updates["failure_reason"] = failure_reason

    updated_session = replace(session, **updates)
    reg = registry or get_authoring_registry()
    reg.save(updated_session)
    return updated_session


def modify_draft(
    session: AuthoringSession,
    new_draft: SkillDraft,
    registry: AuthoringSessionRegistry | None = None,
) -> AuthoringSession:
    """Modify the current draft, invalidating any previous publication authorization token."""
    new_hash = compute_payload_hash(new_draft.skill.to_dict())
    now = datetime.now(timezone.utc).isoformat()
    updated = replace(
        session,
        state=AuthoringState.QUALITY_CHECKING,
        draft=new_draft,
        draft_hash=new_hash,
        publication_authorization=None,  # Invalidate previous token!
        updated_at=now,
    )
    reg = registry or get_authoring_registry()
    reg.save(updated)
    return updated


def authorize_publication(
    session: AuthoringSession,
    user_id: str = "default",
    disposition: str = "equip",
    expiry_seconds: int = 300,
    registry: AuthoringSessionRegistry | None = None,
) -> tuple[AuthoringSession, PublicationAuthorization]:
    """Create a typed, single-use publication authorization bound to the exact draft hash."""
    if not session.draft or not session.draft_hash:
        raise ValueError("Cannot authorize publication without a verified draft and draft_hash.")

    now_dt = datetime.now(timezone.utc)
    exp_dt = now_dt + timedelta(seconds=expiry_seconds)
    auth = PublicationAuthorization(
        authorization_id=f"auth_{uuid.uuid4().hex[:12]}",
        session_id=session.session_id,
        user_id=user_id,
        payload_hash=session.draft_hash,
        scope=session.target_scope if session.target_scope != "unresolved" else "global",
        disposition=disposition,
        created_at=now_dt.isoformat(),
        expires_at=exp_dt.isoformat(),
        is_used=False,
    )
    updated = replace(
        session,
        publication_authorization=auth,
        updated_at=now_dt.isoformat(),
    )
    reg = registry or get_authoring_registry()
    reg.save(updated)
    return updated, auth


_CONSTITUTIONAL_BUILTIN_NAMES = frozenset({
    "persona-preservation",
    "environment-profiling",
    "shell-command-safety",
    "file-operations",
    "git-safety",
    "external-safety",
    "knowledge-gap-detection",
    "context-condenser",
    "systematic-debugging",
    "python-project-workflow",
    "skill-authoring",
})


def check_reserved_name_collision(name: str, builtins: list[Skill] | None = None) -> tuple[bool, list[str]]:
    """Check if name collides with constitutional motor skills, returning safe alternatives."""
    clean_name = re.sub(r"[^a-z0-9_-]+", "-", (name or "").casefold()).strip("-")
    builtin_names = set(_CONSTITUTIONAL_BUILTIN_NAMES)
    if builtins is not None:
        builtin_names.update(b.name.lower() for b in builtins)

    if clean_name in builtin_names:
        suggestions = [
            f"custom-{clean_name}",
            f"repo-{clean_name}",
            f"{clean_name}-workflow",
        ]
        return True, suggestions
    return False, []


def extract_shaping_questions(
    intent: SkillAuthoringIntent,
    local_snapshot: LocalInspectionSnapshot | None = None,
) -> tuple[ShapingQuestion, ...]:
    """Derive at most 3 contextual shaping questions to resolve material gaps."""
    if not intent.capability or not intent.capability.strip():
        return (
            ShapingQuestion(
                key="clarification",
                title="What skill or task would you like hund to learn?",
                help_text="Describe the workflow, checklist, or task to automate.",
                options=(),
                default="",
            ),
        )

    questions: list[ShapingQuestion] = []
    cap = intent.capability.lower()

    if any(k in cap for k in ("plan", "planering", "planeringsfil", "spec", "roadmap")):
        questions.append(
            ShapingQuestion(
                key="focus",
                title="Planning Workflow Focus",
                options=(
                    "Template and structure planning files with clear goals and tasks",
                    "Validate plan requirements, TCB boundaries, and verification gates",
                    "Track step-by-step progress, checklists, and acceptance criteria",
                    "Custom (type your own focus)",
                ),
                default="Template and structure planning files with clear goals and tasks",
            )
        )
        questions.append(
            ShapingQuestion(
                key="location",
                title="Plan Location & Standards",
                options=(
                    "Standard docs/plans/ with YYYY-MM-DD timestamping",
                    "Active handoff files in docs/handoffs/",
                    "Workspace root markdown documents",
                    "Custom (type your own location)",
                ),
                default="Standard docs/plans/ with YYYY-MM-DD timestamping",
            )
        )
        questions.append(
            ShapingQuestion(
                key="safety_gate",
                title="Execution & Gatekeeping Gate",
                options=(
                    "Require explicit approval before executing any plan steps",
                    "Auto-verify against repository ADRs and project guidelines",
                    "Pure drafting and structuring without execution gates",
                ),
                default="Require explicit approval before executing any plan steps",
            )
        )
    elif any(k in cap for k in ("deploy", "deployment", "infra", "server", "host", "docker")):
        questions.append(
            ShapingQuestion(
                key="target",
                title="Deployment Target",
                options=(
                    "Docker container to production VPS",
                    "Cloud Run / Serverless container",
                    "Fly.io / PaaS deployment",
                    "Custom script / Other",
                ),
                default="Docker container to production VPS",
            )
        )
        questions.append(
            ShapingQuestion(
                key="safety_gate",
                title="Safety & Verification Gate",
                options=(
                    "Run pytest & lint suite before triggering deploy",
                    "Smoke test health endpoint post-deploy only",
                    "Manual confirmation before container push",
                ),
                default="Run pytest & lint suite before triggering deploy",
            )
        )
    elif any(k in cap for k in ("api", "endpoint", "route", "service", "rest", "graphql")):
        questions.append(
            ShapingQuestion(
                key="protocol",
                title="API Structure & Protocol",
                options=(
                    "Standard REST JSON endpoints",
                    "GraphQL schema & mutations",
                    "gRPC / Protobuf services",
                    "Custom (type your own protocol)",
                ),
                default="Standard REST JSON endpoints",
            )
        )
    elif any(k in cap for k in ("test", "pytest", "testing", "tdd", "unit")):
        questions.append(
            ShapingQuestion(
                key="test_type",
                title="Testing Strategy",
                options=(
                    "Unit and regression testing with pytest",
                    "Integration and end-to-end testing",
                    "Test-driven development (TDD failing test first)",
                    "Custom (type your own strategy)",
                ),
                default="Unit and regression testing with pytest",
            )
        )
    else:
        questions.append(
            ShapingQuestion(
                key="focus",
                title="Primary Workflow Focus",
                options=(
                    f"Automate {intent.capability} end-to-end",
                    f"Validate and verify {intent.capability}",
                    f"Template and structure {intent.capability}",
                    "Custom (type your own focus)",
                ),
                default=f"Automate {intent.capability} end-to-end",
            )
        )

    if intent.target_scope == "unresolved" and len(questions) < 4:
        questions.append(
            ShapingQuestion(
                key="scope",
                title="Skill Scope",
                options=(
                    "Project (this repository only)",
                    "Global (available across all projects)",
                ),
                default="Project (this repository only)",
            )
        )

    return tuple(questions[:4])


def apply_shaping_answers(
    session: AuthoringSession,
    answers: dict[str, str],
    registry: AuthoringSessionRegistry | None = None,
) -> AuthoringSession:
    """Apply user answers to shaping questions and update session scope/metadata."""
    updated_answers = dict(session.shaping_answers)
    updated_answers.update(answers)

    target_scope = session.target_scope
    if "scope" in answers:
        s_val = answers["scope"].lower()
        if "project" in s_val:
            target_scope = "project"
        elif "global" in s_val:
            target_scope = "global"

    now = datetime.now(timezone.utc).isoformat()
    updated = replace(
        session,
        shaping_answers=updated_answers,
        target_scope=target_scope,
        updated_at=now,
    )
    reg = registry or get_authoring_registry()
    reg.save(updated)
    return updated


_PLACEHOLDER_PATTERNS = (
    re.compile(r"(?i)\bTODO\b"),
    re.compile(r"(?i)\bTBD\b"),
    re.compile(r"(?i)\badd\s+(?:your\s+)?(?:secret|key|token|password|here)\b"),
    re.compile(r"(?i)\bYOUR_[A-Z0-9_]+\b"),
    re.compile(r"(?i)\bxxx+\b"),
)

_BOILERPLATE_PATTERNS = (
    re.compile(r"(?i)\bapply\s+the\s+.*\s+workflow\s+without\s+overriding\b"),
    re.compile(r"(?i)\binspect\s+.*\s+for\s+requirements\s+relevant\s+to\b"),
    re.compile(r"(?i)\bexecute\s+.*\s+using\s+the\s+current\s+project's\s+conventions\b"),
    re.compile(r"(?i)\bwhen\s+the\s+task\s+requires\s+[a-z0-9_-]+\.?$"),
    re.compile(r"(?i)\binspect\s+(?:the\s+)?(?:files|workspace|project|codebase)\s*(?:to\s+understand|\.|$)", re.IGNORECASE),
    re.compile(r"(?i)\bcheck\s+(?:the\s+)?(?:files|workspace|project|codebase)\s*(?:structure|\.|$)", re.IGNORECASE),
)

_SWEDISH_WORDS_PATTERN = re.compile(
    r"\b(och|eller|att|för|med|inte|läs|skapa|ändra|kontrollera|verifiera|kör|av|på|om|vid|som|när|detta|denna|dessa|ska|måste|använd|använda|etablera|utför|utföra|befintlig|befintliga|säkerställ|säkerställa|åtgärda|inställningar|arbetsyta|katalog|fil|filer|rapportera|resultat|användare|steg|behörigheter)\b|[åäöÅÄÖ]",
    re.IGNORECASE,
)


def log_authoring_request(
    client: Any,
    result: Any,
    task_class: str,
    *,
    run_id: str | None = None,
    latency_ms: int = 0,
) -> None:
    """Log an authoring LLM call to logs/requests.db without crashing."""
    try:
        from ..store.sqlite import connect_requests
        conn = connect_requests()
        cfg = getattr(client, "cfg", None)
        model = (
            getattr(client, "model", None)
            or (getattr(cfg, "provider", None) and getattr(cfg.provider, "model", None))
            or getattr(client, "model_name", "unknown")
            or "unknown"
        )
        provider = (
            (getattr(cfg, "provider", None) and getattr(cfg.provider, "base_url", None))
            or getattr(client, "base_url", None)
            or "authoring_provider"
        )
        finish_reason = getattr(result, "finish_reason", "stop") or "stop"
        prompt_tokens = getattr(result, "prompt_tokens", 0) or 0
        completion_tokens = getattr(result, "completion_tokens", 0) or 0
        lat = getattr(result, "latency_ms", None) or latency_ms or 0

        conn.execute(
            """INSERT INTO requests
               (id, created_at, task_class, model_requested, model_actual, provider,
                finish_reason, prompt_tokens, completion_tokens, latency_ms, run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                task_class,
                str(model),
                str(model),
                str(provider),
                str(finish_reason),
                int(prompt_tokens),
                int(completion_tokens),
                int(lat),
                run_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


class ReviewCallOutput(BaseModel, extra="forbid"):
    approved: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)


def run_llm_review_gate(
    draft: SkillDraft,
    *,
    client: Any = None,
    run_id: str | None = None,
    research_summaries: list[str] | tuple[str, ...] | None = None,
    user_stated_versions: set[str] | None = None,
) -> ReviewCallOutput:
    """Execute LLM review gate (Call 3) evaluating draft along 5 strict axes."""
    if client is None:
        raise ValueError("Provider client required for LLM review gate")

    system_prompt = (
        "You are Hund's canonical skill quality review gate. "
        "Evaluate the declarative skill draft along 5 strict axes:\n"
        "1. Scope specificity (narrow, distinct boundaries, distinguishes matching from non-matching tasks; reject conflation of incompatible variants/loaders)\n"
        "2. Operational clarity (concrete ordered steps that change execution decisions, with conditional rules where choices diverge, and anti-pattern warnings 'Do not X; instead Y' for common pitfalls; reject vague 'inspect files' without a concrete target file or action)\n"
        "3. Trigger appropriateness (1-12 precise triggers, Swedish aliases when useful, NO catchalls)\n"
        "4. Verification decisiveness (2-3 binary checks decidable as pass or fail)\n"
        "5. Anti-slop / No secrets (English canonical instructions, no secrets, no banned actions, no placeholders)\n\n"
        "VERSION GROUNDING RULE: User-stated versions (in 'user_stated_versions') and research versions are 100% FACTUAL AND AUTHORITATIVE. "
        "You MUST NOT reject, lower score, or question a version because it seems unfamiliar, high, futuristic, or because your training weights lack it. "
        "NEVER claim a version is 'unrealistic', 'fabricated', 'simulated', or 'does not exist'. "
        "Reject a version ONLY if it was completely invented out of thin air — neither user-stated nor present in research summaries.\n\n"
        "CALIBRATION & ACCEPTANCE RULE:\n"
        "- Your goal is quality gatekeeping, not perfectionism or pedantic nitpicking.\n"
        "- APPROVE (approved=true, score >= 0.8) if the draft provides actionable, concrete guidance that enables Hund to reliably perform the task.\n"
        "- Standard build commands (e.g. gradlew build/dependencies), common troubleshooting practices (e.g. inspecting build logs or cache reports), locating entry points, and reasonable trigger phrases are fully acceptable and desirable.\n"
        "- Reject (approved=false, score < 0.7) ONLY for fatal quality defects: completely vague/empty steps, harmful or banned actions, non-English canonical text, hallucinatory ungrounded claims, or severe scope conflation.\n"
        "- Do NOT reject for minor stylistic differences, pedantic definitions of standard developer terminology, or reasonable troubleshooting steps.\n\n"
        "Return strictly JSON conforming to this schema with NO extra fields:\n"
        "{\n"
        '  "approved": boolean,\n'
        '  "score": float between 0.0 and 1.0,\n'
        '  "issues": ["Issue 1", ... (empty if approved)]\n'
        "}"
    )

    skill_dict = {
        "name": draft.skill.name,
        "when_to_use": draft.skill.when_to_use,
        "steps": list(draft.skill.steps),
        "triggers": list(draft.skill.triggers),
        "verification": list(draft.skill.verification),
        "examples": list(draft.skill.examples),
    }
    prompt_payload: dict[str, Any] = {"skill_draft": skill_dict}
    if research_summaries:
        prompt_payload["research_summaries"] = list(research_summaries)
    if user_stated_versions:
        prompt_payload["user_stated_versions"] = sorted(user_stated_versions)
    user_prompt = json.dumps(prompt_payload, ensure_ascii=False, indent=2)

    from ..providers.base import Message
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    import time
    t0 = time.time()
    result = client.complete(messages, tools=None, max_tokens=2500)
    latency_ms = int((time.time() - t0) * 1000)
    log_authoring_request(client, result, "authoring_review", run_id=run_id, latency_ms=latency_ms)

    raw_text = (getattr(result, "text", "") or getattr(result, "content", "") or "").strip()
    if not raw_text:
        t0 = time.time()
        result = client.complete(messages, tools=None, max_tokens=8000)
        latency_ms = int((time.time() - t0) * 1000)
        log_authoring_request(client, result, "authoring_review", run_id=run_id, latency_ms=latency_ms)
        raw_text = (getattr(result, "text", "") or getattr(result, "content", "") or "").strip()

    if not raw_text:
        finish = getattr(result, "finish_reason", "unknown")
        raise ValueError(f"Provider review returned no JSON after retry (finish_reason={finish}).")

    from .shaping import _extract_json_block
    json_text = _extract_json_block(raw_text)
    review = ReviewCallOutput.model_validate_json(json_text)

    if user_stated_versions and review.issues:
        clean_issues = []
        for issue in review.issues:
            issue_lower = issue.casefold()
            is_version_complaint = any(
                term in issue_lower
                for term in (
                    "unrealistic version",
                    "not recognized in research",
                    "not recognized",
                    "not exist",
                    "does not exist",
                    "fabricated internally",
                    "simulated",
                    "dated in future",
                    "duplicate knowledge",
                    "no such official",
                )
            )
            has_user_version = any(v.casefold() in issue_lower for v in user_stated_versions)
            if is_version_complaint or (has_user_version and "version" in issue_lower):
                # Spurious rejection of user-stated version
                continue
            clean_issues.append(issue)

        if not clean_issues and not review.approved:
            review = ReviewCallOutput(
                approved=True,
                score=max(review.score, 0.85),
                issues=[],
            )
        elif len(clean_issues) != len(review.issues):
            review = ReviewCallOutput(
                approved=review.approved if clean_issues else True,
                score=review.score if clean_issues else max(review.score, 0.85),
                issues=clean_issues,
            )

    return review



def run_deterministic_quality_checks(
    draft: SkillDraft,
    builtins: list[Skill] | None = None,
    registered_tools: set[str] | None = None,
    existing_skills: list[Skill] | None = None,
    *,
    raw_prompt: str | None = None,
    shaping_answers: dict[str, str] | None = None,
    research_summaries: list[str] | tuple[str, ...] | None = None,
    declared_dependencies: tuple[str, ...] | list[str] | None = None,
    user_stated_versions: set[str] | None = None,
) -> QualityGateResult:
    """Execute all deterministic pre-publication quality checks on a skill draft."""
    skill = draft.skill
    checks: list[QualityGateCheck] = []
    failures: list[str] = []

    # 0. Existing skill trigger or name collision
    if existing_skills:
        for existing in existing_skills:
            if existing.name == skill.name:
                msg = f"Skill name '{skill.name}' collides with existing skill."
                checks.append(QualityGateCheck("existing_skill_collision", False, msg))
                failures.append(msg)
                break
            overlap = set(skill.triggers).intersection(set(existing.triggers or ()))
            if overlap:
                msg = f"Trigger collision with existing skill '{existing.name}': {overlap}"
                checks.append(QualityGateCheck("existing_skill_collision", False, msg))
                failures.append(msg)
                break

    # 1. Non-reserved identity check
    collided, suggestions = check_reserved_name_collision(skill.name, builtins=builtins)
    if collided:
        msg = f"Skill name '{skill.name}' collides with reserved constitutional motor skill."
        checks.append(QualityGateCheck("non_reserved_identity", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("non_reserved_identity", True))

    # 2. Specific triggers & bounded outcome
    if not skill.triggers or not any(str(t).strip() for t in skill.triggers):
        msg = "Skill triggers are empty; at least one specific routing trigger is required."
        checks.append(QualityGateCheck("specific_triggers", False, msg))
        failures.append(msg)
    elif not skill.when_to_use or len(skill.when_to_use.strip()) < 10:
        msg = "when_to_use description is too short or missing."
        checks.append(QualityGateCheck("specific_triggers", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("specific_triggers", True))

    # 3. Mandatory banned actions check
    from .model import BANNED_ACTIONS
    missing_banned = set(BANNED_ACTIONS) - set(skill.forbidden_actions or ())
    if missing_banned:
        msg = f"Skill is missing required constitutional banned actions: {missing_banned}"
        checks.append(QualityGateCheck("banned_actions_included", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("banned_actions_included", True))

    # 3. Actionable procedure
    if not skill.steps or not any(str(s).strip() for s in skill.steps):
        msg = "Procedure steps are empty; actionable steps are required."
        checks.append(QualityGateCheck("actionable_procedure", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("actionable_procedure", True))

    # 4. Constraints & verification
    if not skill.verification or not any(str(v).strip() for v in skill.verification):
        msg = "Verification steps are required to confirm successful outcome."
        checks.append(QualityGateCheck("constraints_and_verification", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("constraints_and_verification", True))

    # 5. Placeholders (TODO, TBD, your_key)
    full_text = " ".join([
        skill.name,
        skill.when_to_use,
        " ".join(skill.triggers),
        " ".join(skill.steps),
        " ".join(skill.verification),
    ])
    placeholder_found = False
    for pat in _PLACEHOLDER_PATTERNS:
        m = pat.search(full_text)
        if m:
            msg = f"Unresolved placeholder '{m.group(0)}' detected in skill content."
            checks.append(QualityGateCheck("no_placeholders", False, msg))
            failures.append(msg)
            placeholder_found = True
            break
    if not placeholder_found:
        checks.append(QualityGateCheck("no_placeholders", True))

    # 6. Boilerplate and hollow template detection
    boilerplate_found = False
    for pat in _BOILERPLATE_PATTERNS:
        m = pat.search(full_text)
        if m:
            msg = f"Hollow boilerplate phrase '{m.group(0)}' detected in skill content."
            checks.append(QualityGateCheck("no_boilerplate", False, msg))
            failures.append(msg)
            boilerplate_found = True
            break
    if not boilerplate_found:
        checks.append(QualityGateCheck("no_boilerplate", True))

    # 6. Scope & disposition consistency
    if skill.scope not in ("global", "project"):
        msg = f"Invalid skill scope '{skill.scope}'. Must be 'global' or 'project'."
        checks.append(QualityGateCheck("scope_consistency", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("scope_consistency", True))

    # 7. Secret & private paths
    red = redact_text(full_text)
    if "secret" in red.blocked_fields:
        msg = "Secret credential pattern detected in skill content."
        checks.append(QualityGateCheck("secret_redaction", False, msg))
        failures.append(msg)
    else:
        checks.append(QualityGateCheck("secret_redaction", True))

    # 8. Canonical content in English
    canonical_text = " ".join([
        skill.when_to_use or "",
        " ".join(skill.steps or ()),
        " ".join(skill.verification or ()),
        " ".join(getattr(skill, "examples", ()) or ()),
    ])
    swedish_match = _SWEDISH_WORDS_PATTERN.search(canonical_text)
    if swedish_match:
        msg = f"Canonical skill content must be in English. Detected non-English term '{swedish_match.group(0)}'."
        checks.append(QualityGateCheck("english_canonical_content", False, msg))
        failures.append(msg)
    # 9. Grounded versions check
    _VERSION_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)+\b")
    draft_scope_text = f"{skill.when_to_use or ''} {' '.join(skill.steps or ())}"
    draft_versions = set(_VERSION_TOKEN_RE.findall(draft_scope_text))

    if draft_versions:
        grounded_sources: list[str] = []
        if raw_prompt:
            grounded_sources.append(raw_prompt)
        if shaping_answers:
            grounded_sources.extend(shaping_answers.values())
        if research_summaries:
            grounded_sources.extend(research_summaries)
        if declared_dependencies:
            grounded_sources.extend(declared_dependencies)

        grounded_text = " ".join(str(s) for s in grounded_sources)
        grounded_tokens = set(_VERSION_TOKEN_RE.findall(grounded_text))
        if user_stated_versions:
            grounded_tokens.update(user_stated_versions)

        ungrounded = [v for v in sorted(draft_versions) if v not in grounded_tokens]
        if ungrounded:
            for bad_ver in ungrounded:
                msg = f"version not grounded: '{bad_ver}'"
                checks.append(QualityGateCheck("grounded_versions", False, msg))
                failures.append(msg)
        else:
            checks.append(QualityGateCheck("grounded_versions", True))

    return QualityGateResult(
        passed=(len(failures) == 0),
        checks=tuple(checks),
        failures=tuple(failures),
    )


def detect_batch_skill_intent(user_text: str) -> list[SkillAuthoringIntent]:
    """Detect single or multiple skill authoring requests (e.g. 'Create skills for X and Y')."""
    text = (user_text or "").strip()
    if not text:
        return []

    m_batch = re.search(
        r"\b(?:create|make|build|skapa|bygg)\s+skills?\s+(?:for|om|för|kring)\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if m_batch:
        raw_items = m_batch.group(1)
        parts = re.split(r"\s+(?:and|och)\s+|,\s*", raw_items, flags=re.IGNORECASE)
        intents = []
        for p in parts:
            p_clean = _clean_capability(p)
            if p_clean and p_clean.lower() not in _CONNECTOR_WORDS:
                intents.append(
                    SkillAuthoringIntent(
                        operation="create",
                        capability=p_clean,
                        target_scope="project" if any(k in text.lower() for k in ("project", "projekt", "repo")) else "global",
                        referenced_name=None,
                        local_only="without research" in text.lower() or "offline" in text.lower(),
                        requires_research="research" in text.lower() or "docs" in text.lower(),
                        confidence=0.95,
                        raw_prompt=f"Create skill for {p_clean}",
                    )
                )
        if len(intents) >= 2:
            return intents

    single = detect_explicit_skill_intent(text)
    if single:
        return [single]

    return []


@dataclass(frozen=True)
class CreateSkillToolArgs:
    request: str | None
    target_scope: str  # "global" | "project" | "unresolved"
    desired_disposition: str  # "equip" | "vault" | "auto"
    legacy_skill: dict[str, Any] | None = None
    session_id: str | None = None
    payload_hash: str | None = None
    authorization_id: str | None = None


@dataclass(frozen=True)
class AuthoringAdvisory:
    status: str  # "NONE" | "CLARIFICATION_REQUIRED" | "REJECTED" | "CALL_CREATE_SKILL"
    message: str = ""
    tool_args: CreateSkillToolArgs | None = None


def render_publication_receipt(receipt: PublicationReceipt, width: int = 80, ascii_only: bool = False) -> str:
    """Render a width- and ASCII-aware publication receipt string."""
    bullet = "*" if ascii_only else "·"
    sep = "|" if ascii_only else "·"
    raw_lines = [
        f"{receipt.action.capitalize()} {receipt.skill_name} ({receipt.scope}).",
        f"Version {receipt.artifact_version if hasattr(receipt, 'artifact_version') else getattr(receipt, 'version', '1')} {sep} {receipt.lifecycle_state.capitalize()} {sep} Vault: {receipt.vault_state} {sep} {receipt.personal_skill_xp} XP",
    ]
    if receipt.source_count > 0:
        raw_lines.append(f"Sources: {receipt.source_count} authoritative reference(s)")
    if receipt.diff_summary:
        raw_lines.append(f"Changes: {receipt.diff_summary}")
    if receipt.limitations:
        raw_lines.append(f"Note: {'; '.join(receipt.limitations)}")

    wrapped_lines = []
    for line in raw_lines:
        wrapped = textwrap.fill(line, width=max(width, 20), break_long_words=True, break_on_hyphens=False)
        wrapped_lines.append(wrapped)
    return "\n".join(wrapped_lines)


# Regex matchers for explicit authoring intent
_NON_INTENT_PATTERNS = [
    r"^(?:vad\s+är|hur\s+fungerar|berätta\s+om|förklara|visa)\s+.*skills?",
    r"^(?:what\s+is|what\s+are|how\s+do|how\s+does|tell\s+me\s+about|explain)\s+.*skills?",
    r"\b(?:do\s+you\s+have|har\s+du)\s+.*skills?",
    r"\b(?:jag\s+såg|i\s+saw)\s+.*skill",
    # Negations
    r"\b(?:inte|aldrig|skall\s+inte|ska\s+inte|vill\s+inte|bör\s+inte|får\s+inte)\b",
    r"\b(?:don't|do\s+not|never|should\s+not|must\s+not|cannot|can't|won't)\b",
    # Question openers / interrogatives
    r"^(?:ska\s+vi|ska\s+jag|skall\s+vi|skall\s+jag|borde\s+vi|borde\s+jag|kan\s+vi|kan\s+jag|vill\s+du|måste\s+vi|måste\s+jag)\b",
    r"^(?:should\s+(?:i|we|you)|can\s+(?:i|we|you)|could\s+(?:i|we|you)|would\s+(?:i|we|you)|shall\s+(?:i|we)|why\s+(?:not\s+|should\s+|would\s+)?(?:create|make|build|add))\b",
    r"^(?:varför|hur|när|vem|vilka|vilken|vilket)\b",
    r"^(?:why|how|when|who|which|where)\b",
]

_CREATE_PATTERNS_EN = [
    r"\b(?:create|make|build|write|author|generate|compose|add)\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?skill(?:-?file)?\s+(?:for|to|that|about|regarding|around|on|so\s+that|so|in\s+order\s+to)\s+(.+)",
    r"\b(?:create|make|build|write|author|generate|compose|add)\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?skill(?:-?file)?[:\s]+(.+)",
]

_CREATE_PATTERNS_SV = [
    r"\b(?:skapa|bygg|bygga|skriv|skriva|författa|generera|lägg\s+till|gör|göra)\s+(?:mig\s+)?(?:en\s+)?(?:ny\s+)?skill(?:-?fil(?:er)?)?\s+(?:för|som|till|om|kring|gällande|angående|avseende|rörande|så\s+att|så|att|för\s+att)\s+(.+)",
    r"\b(?:skapa|bygg|bygga|skriv|skriva|författa|generera|lägg\s+till|gör|göra)\s+(?:mig\s+)?(?:en\s+)?(?:ny\s+)?skill(?:-?fil(?:er)?)?[:\s]+(.+)",
]

_UPDATE_PATTERNS_EN = [
    r"\b(?:update|edit|modify|improve|refine|patch)\s+skill\s+([a-z0-9_-]+)(?:\s+(?:to|with|for)\s+(.+))?",
    r"\b(?:update|edit|modify|improve|refine|patch)\s+(?:the\s+)?([a-z0-9_-]+)\s+skill(?:\s+(?:to|with|for)\s+(.+))?",
]

_UPDATE_PATTERNS_SV = [
    r"\b(?:uppdatera|ändra|modifiera|förbättra)\s+skill(?:en)?\s+([a-z0-9_-]+)(?:\s+(?:med|för|till)\s+(.+))?",
    r"\b(?:uppdatera|ändra|modifiera|förbättra)\s+([a-z0-9_-]+)-skill(?:en)?(?:\s+(?:med|för|till)\s+(.+))?",
]

_CONNECTOR_WORDS = {
    "om", "kring", "gällande", "angående", "avseende", "rörande",
    "för", "som", "till", "for", "about", "regarding", "to", "that", "around", "on", "så", "så att",
}


def _clean_capability(raw_cap: str) -> str:
    cleaned = raw_cap.strip().strip("\"'`:;,!?.")
    leading_connectors = (
        r"^(?:om|kring|gällande|angående|avseende|rörande|för|som|till|for|about|regarding|to|that|around|on|att|så\s+att|så|in\s+order\s+to|so\s+that)\s+"
    )
    leading_scope_possessives = (
        r"^(?:det\s+här\s+projektets|detta\s+projekts|det\s+här\s+repot?s|detta\s+repos?|this\s+project'?s|this\s+repo'?s)\s+"
    )
    leading_verbs_pronouns = (
        r"^(?:du\s+|jag\s+|hund\s+|vi\s+|man\s+|han\s+|hon\s+|you\s+|we\s+|i\s+)?(?:gör\s+(?:att\s+)?(?:mig\s+|oss\s+|dig\s+|du\s+|jag\s+)?|göra\s+(?:att\s+)?|gör\s+|skriver\s+|skriva\s+|skriv\s+|writes?\s+|authoring\s+|author\s+|make\s+(?:me\s+|us\s+|you\s+)?|makes\s+|blir\s+|är\s+|ska\s+bli\s+|ska\s+vara\s+|become\s+|be\s+|are\s+|is\s+)\s*"
    )
    leading_helper_phrases = (
        r"^(?:bättre\s+(?:och\s+mer\s+)?(?:på\s+att\s+|med\s+|i\s+)?|better\s+(?:and\s+more\s+)?(?:at\s+|with\s+|in\s+)?|mer\s+strukturerad\s+(?:när\s+vi\s+|när\s+jag\s+|på\s+att\s+)?|more\s+structured\s+(?:when\s+|at\s+)?)\s*"
    )
    leading_time_clauses = (
        r"^(?:när\s+vi\s+|när\s+jag\s+|när\s+man\s+|när\s+du\s+|when\s+we\s+|when\s+i\s+|when\s+you\s+)\s*"
    )
    trailing_patterns = [
        r"\s+(?:for\s+this\s+project|in\s+this\s+repo|för\s+detta\s+projekt|i\s+detta\s+repo|lokalt\s+för\s+projektet)[.!?]*$",
        r"\s+(?:globally|globalt|för\s+alla\s+projekt|for\s+all\s+projects)[.!?]*$",
        r"\s+(?:and\s+equip\s+now|och\s+aktivera|och\s+spara\s+till\s+valvet|and\s+vault|spara\s+till\s+valvet)[.!?]*$",
        r"\s+(?:offline|utan\s+webbsökning|no\s+web\s+search|without\s+research|utan\s+sökning)[.!?]*$",
        r"\s+(?:åt\s+mig|för\s+mig|till\s+mig|for\s+me|please|tack)[.!?]*$",
    ]
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = cleaned.strip(" \t\r\n\"'`:;,!?.").strip()
        cleaned = re.sub(leading_connectors, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(leading_scope_possessives, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(leading_verbs_pronouns, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(leading_helper_phrases, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(leading_time_clauses, "", cleaned, flags=re.IGNORECASE).strip()
        for tp in trailing_patterns:
            cleaned = re.sub(tp, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = cleaned.strip(" \t\r\n\"'`:;,!?.").strip()
    return cleaned


_BARE_CREATE_PATTERNS = (
    r"^\s*(?:kan\s+du\s+|skulle\s+du\s+kunna\s+)?(?:skapa|bygg|bygga|skriv|skriva|författa|generera|lägg\s+till|gör|göra)\s+(?:mig\s+)?(?:en\s+)?(?:ny\s+)?skill(?:-?fil(?:er)?)?[.\s]*$",
    r"^\s*(?:could\s+you\s+|can\s+you\s+|would\s+you\s+)?(?:please\s+)?(?:create|make|build|write|author|generate|compose|add)\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?skill(?:-?file)?[.\s]*$",
)


def detect_explicit_skill_intent(user_text: str) -> SkillAuthoringIntent | None:
    """Detect explicit English or Swedish skill authoring intent with conservative filtering."""
    raw_text = (user_text or "").strip()
    if not raw_text:
        return None

    text = raw_text
    polite_patterns = (
        r"^(?:kan\s+du|skulle\s+du\s+kunna|vill\s+du)\s+((?:skapa|bygg|bygga|gör|göra|skriv|skriva|lägg\s+till|författa|generera)\b.+)\??$",
        r"^(?:could|can|would)\s+you\s+(?:please\s+)?((?:create|make|build|add|author|generate|write|compose)\b.+)\??$",
    )
    polite_command = next(
        (
            match.group(1).strip()
            for pattern in polite_patterns
            if (match := re.match(pattern, text, re.IGNORECASE))
        ),
        None,
    )
    if polite_command is not None:
        text = polite_command
    elif text.endswith("?"):
        return None

    for pattern in _NON_INTENT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return None

    lower = text.lower()

    if any(k in lower for k in ("global", "globally", "globalt", "för alla projekt", "for all projects")):
        target_scope = "global"
    elif any(k in lower for k in (
        "project", "projekt", "för detta projekt", "for this project",
        "lokalt för projektet", "i detta repo", "in this repo",
        "det här projektets", "detta projekts", "this project's",
        "det här repots", "detta repos", "this repo's",
    )):
        target_scope = "project"
    else:
        target_scope = "unresolved"

    if any(k in lower for k in ("equip", "use now", "aktivera", "använd direkt", "aktivera direkt", "ta i bruk")):
        desired_disposition = "equip"
    elif any(k in lower for k in ("vault", "parkera", "spara till valvet", "save to vault", "i valvet", "valva")):
        desired_disposition = "vault"
    else:
        desired_disposition = "auto"

    local_only = any(k in lower for k in (
        "utan webbsökning", "utan sökning", "offline", "lokalt", "no web search",
        "without research", "without web search", "lokal skill", "pure instruction",
    ))
    requires_research = any(k in lower for k in (
        "research", "webbsök", "web search", "senaste api", "latest api",
        "external docs", "extern dokumentation", "search documentation", "search online",
    )) and not local_only

    # Check bare authoring requests first
    for pattern in _BARE_CREATE_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return SkillAuthoringIntent(
                operation="create",
                capability="",
                target_scope=target_scope,
                referenced_name=None,
                local_only=local_only,
                requires_research=requires_research,
                confidence=0.95,
                raw_prompt=raw_text,
                desired_disposition=desired_disposition,
            )

    for pattern in _UPDATE_PATTERNS_EN + _UPDATE_PATTERNS_SV:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            extra = m.group(2).strip() if len(m.groups()) > 1 and m.group(2) else ""
            capability = _clean_capability(f"{name} {extra}".strip())
            if not capability or capability.lower() in _CONNECTOR_WORDS:
                continue
            return SkillAuthoringIntent(
                operation="update",
                capability=capability,
                target_scope=target_scope,
                referenced_name=name,
                local_only=local_only,
                requires_research=requires_research,
                confidence=0.95,
                raw_prompt=raw_text,
                desired_disposition=desired_disposition,
            )

    for pattern in _CREATE_PATTERNS_EN + _CREATE_PATTERNS_SV:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw_cap = m.group(1).strip()
            capability = _clean_capability(raw_cap)
            if not capability or capability.lower() in _CONNECTOR_WORDS:
                continue
            return SkillAuthoringIntent(
                operation="create",
                capability=capability,
                target_scope=target_scope,
                referenced_name=None,
                local_only=local_only,
                requires_research=requires_research,
                confidence=0.95,
                raw_prompt=raw_text,
                desired_disposition=desired_disposition,
            )

    return None

    return None


def inspect_local_context(
    workspace_root: Path,
    registered_tools: set[str],
    existing_skills: list[Skill],
) -> LocalInspectionSnapshot:
    """Inspect local workspace context without network or mutating I/O."""
    ws_root = workspace_root.resolve()
    ws_name = ws_root.name
    configs = []
    relevant = []
    dependencies: set[str] = set()

    try:
        for p in ws_root.glob("*"):
            if p.is_file():
                if p.name in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile", "requirements.txt"):
                    configs.append(p.name)
                elif len(relevant) < 10:
                    relevant.append(p.name)
    except Exception:
        pass

    def add_dependency(raw: object) -> None:
        if not isinstance(raw, str):
            return
        name = re.split(r"[<>=!~;\s\[]", raw.strip(), maxsplit=1)[0]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,79}", name):
            dependencies.add(name)

    try:
        pyproject = ws_root / "pyproject.toml"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            for dependency in data.get("project", {}).get("dependencies", []):
                add_dependency(dependency)
            for group in data.get("project", {}).get("optional-dependencies", {}).values():
                for dependency in group if isinstance(group, list) else ():
                    add_dependency(dependency)
        package_json = ws_root / "package.json"
        if package_json.is_file():
            data = json.loads(package_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                values = data.get(section, {})
                if isinstance(values, dict):
                    for dependency in values:
                        add_dependency(dependency)
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        dependencies.clear()

    return LocalInspectionSnapshot(
        workspace_name=ws_name,
        workspace_root=str(ws_root),
        config_files_found=tuple(sorted(configs)),
        relevant_files=tuple(sorted(relevant)),
        registered_tools=tuple(sorted(registered_tools)),
        scoped_skills=tuple(sorted(s.name for s in existing_skills)),
        declared_dependencies=tuple(sorted(dependencies))[:50],
    )


def _sanitize_for_query(text: str) -> str:
    sanitized = re.sub(r"[A-Za-z]:[/\\][^\s]+", "", text)
    sanitized = re.sub(r"/(?:Users|home|root|var|tmp|etc|usr|bin)/[^\s]+", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"[^a-zA-Z0-9\s_-]", " ", sanitized)
    words = [w for w in sanitized.split() if len(w) > 1 and w.lower() not in ("skill", "create", "make", "for", "the", "and", "in", "to", "of", "with")]
    return " ".join(words[:5])


def decide_research_need(
    intent: SkillAuthoringIntent,
    local_context: LocalInspectionSnapshot,
) -> ResearchDecision:
    """Decide if web research is required for authoring proposal."""
    if intent.local_only:
        return ResearchDecision(
            needs_research=False,
            reason="Local-only explicitly requested.",
            search_queries=(),
        )

    if intent.requires_research:
        query_kw = _sanitize_for_query(intent.capability)
        query = (query_kw + " documentation").strip()
        return ResearchDecision(
            needs_research=True,
            reason="External research explicitly requested.",
            search_queries=(query,) if query else ("documentation",),
        )

    lower_cap = intent.capability.lower()
    volatile_keywords = ("api", "v2", "v3", "sdk", "cloud", "aws", "gcp", "azure", "openai", "deepseek", "library", "framework", "version")
    if any(k in lower_cap for k in volatile_keywords) and not any(k in lower_cap for k in ("local", "git", "markdown", "file", "text")):
        query_kw = _sanitize_for_query(intent.capability)
        query = (query_kw + " best practices").strip()
        return ResearchDecision(
            needs_research=True,
            reason="Volatile API/framework keyword detected in skill capability.",
            search_queries=(query,) if query else ("best practices",),
        )

    return ResearchDecision(
        needs_research=False,
        reason="Local context and instructions sufficient for skill authoring.",
        search_queries=(),
    )

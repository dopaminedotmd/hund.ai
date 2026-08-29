"""Safe, typed, context-aware shaping for Skill Authoring."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from ..providers.base import Message
from .authoring import LocalInspectionSnapshot, ShapingQuestion, SkillAuthoringIntent


@dataclass(frozen=True)
class ShapingPlan:
    subject: str
    confidence: float
    questions: tuple[ShapingQuestion, ...]
    clarification: str | None = None
    source: str = "fallback"


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+@/-]{0,79}$")
_INSTRUCTION_TERMS = re.compile(
    r"\b(?:create_skill|publish\s+now|skip\s+consent|execute\s+tool|"
    r"authorize\s+publication|ignore\s+(?:previous|safety))\b",
    re.IGNORECASE,
)


def _safe_names(values: tuple[str, ...], *, limit: int = 30) -> list[str]:
    return sorted(
        {
            value
            for value in values
            if _SAFE_NAME.fullmatch(value)
            and not _INSTRUCTION_TERMS.search(value.replace("_", " ").replace("-", " "))
        }
    )[:limit]


def _project_type(snapshot: LocalInspectionSnapshot) -> str:
    configs = set(snapshot.config_files_found)
    if "pyproject.toml" in configs or "requirements.txt" in configs:
        return "python"
    if "package.json" in configs:
        return "javascript_or_typescript"
    if "Cargo.toml" in configs:
        return "rust"
    if "go.mod" in configs:
        return "go"
    return "unknown"


def sanitized_shaping_context(
    intent: SkillAuthoringIntent,
    snapshot: LocalInspectionSnapshot,
    prior_answers: dict[str, str] | None = None,
    user_memories: list[str] | None = None,
    project_memories: list[str] | None = None,
) -> dict[str, Any]:
    """Return the complete allowlisted provider context; never include paths or source."""
    safe_answers = {
        key[:40]: value[:160]
        for key, value in (prior_answers or {}).items()
        if _SAFE_NAME.fullmatch(key) and not _INSTRUCTION_TERMS.search(value)
    }
    ctx: dict[str, Any] = {
        "requested_capability": intent.capability[:160],
        "operation": intent.operation,
        "target_scope": intent.target_scope,
        "project_type": _project_type(snapshot),
        "config_files": _safe_names(snapshot.config_files_found),
        "declared_dependencies": _safe_names(snapshot.declared_dependencies),
        "available_tools": _safe_names(snapshot.registered_tools),
        "existing_skills": _safe_names(snapshot.scoped_skills),
        "prior_answers": safe_answers,
    }
    if user_memories:
        ctx["user_profile"] = [m[:160] for m in user_memories[:10]]
    if project_memories:
        ctx["project_profile"] = [m[:160] for m in project_memories[:10]]
    return ctx


def _question(
    key: str, title: str, help_text: str, options: tuple[str, ...]
) -> ShapingQuestion:
    return ShapingQuestion(
        key=key,
        title=title,
        help_text=help_text,
        options=options,
        default=options[0],
    )


def _scope_question() -> ShapingQuestion:
    return _question(
        "scope",
        "Skill Scope",
        "Choose where this skill should be available; project scope keeps it isolated to this workspace.",
        (
            "Project (this repository only)",
            "Global (available across all projects)",
        ),
    )


def _fallback_questions(intent: SkillAuthoringIntent) -> tuple[ShapingQuestion, ...]:
    from .scope import _slug

    slug_name = _slug(intent.capability).replace("-", " ")
    subject = slug_name.title() if slug_name else "Domain Workflow"
    cap = intent.capability.casefold()
    if any(k in cap for k in ("plan", "spec", "roadmap", "planering")):
        primary = _question(
            "planning_focus",
            "Planning & Specification Focus",
            "Select the primary structure for this planning workflow to establish the right template and verification gates.",
            (
                "Technical architecture and implementation roadmaps",
                "Task breakdowns and milestone tracking",
                "Pre-implementation design and boundary verification",
            ),
        )
    elif "marketing" in cap:
        primary = _question(
            "focus",
            "Primary Marketing Outcome",
            "Choose the result this skill should optimize; it controls the procedure and verification checks.",
            (
                "Plan marketing positioning and channel mix",
                "Draft and review marketing campaign content",
                "Measure marketing performance and recommend iterations",
            ),
        )
    elif any(term in cap for term in ("b2b", "outreach", "prospecting")):
        primary = _question(
            "outreach_stage",
            "B2B Outreach Stage",
            "Choose where the workflow should add the most value; Hund will tailor steps and quality checks to that stage.",
            (
                "Research and qualify target accounts",
                "Draft personalized outreach sequences",
                "Review replies and recommend follow-up actions",
            ),
        )
    elif any(term in cap for term in ("kundsupport", "customer support", "support")):
        primary = _question(
            "support_outcome",
            "Customer Support Outcome",
            "Choose the main support result so escalation rules and verification match the intended workflow.",
            (
                "Triage and categorize incoming requests",
                "Draft accurate customer responses",
                "Summarize cases and prepare escalations",
            ),
        )
    elif any(term in cap for term in ("release", "changelog")):
        primary = _question(
            "release_focus",
            "Release Notes Focus",
            "Select the primary audience so tone, detail level, and verification match expectations.",
            (
                "Technical changelog for contributors and maintainers",
                "User-facing product update highlights",
                "Release checklist and deployment verification",
            ),
        )
    elif any(term in cap for term in ("git-rebase", "rebase", "squash", "git")):
        primary = _question(
            "history_goal",
            "Git History Goal",
            "Choose the intended history outcome so the skill can emphasize safe commands, conflict handling, and verification.",
            (
                "Prepare a clean interactive rebase plan",
                "Squash and reorder commits safely",
                "Resolve rebase conflicts and verify history",
            ),
        )
    elif any(term in cap for term in ("postgresql", "postgres", "sql", "query review", "database")):
        primary = _question(
            "query_goal",
            "Database Review Goal",
            "Choose the primary review lens; it controls which evidence and safety checks the skill requires.",
            (
                "Find correctness and transaction risks",
                "Identify performance and indexing issues",
                "Review maintainability and explain the query plan",
            ),
        )
    else:
        primary = _question(
            "outcome",
            f"{subject} Workflow Outcome",
            f"Choose the primary goal for this {subject.lower()} capability.",
            (
                f"Automate and structure {subject.lower()} end-to-end",
                f"Review and verify {subject.lower()} results",
                f"Guide {subject.lower()} decisions with domain best practices",
            ),
        )

    questions = [primary]
    if intent.target_scope == "unresolved":
        questions.append(_scope_question())
    return tuple(questions)


def _clarification_plan(intent: SkillAuthoringIntent) -> ShapingPlan | None:
    normalized = re.sub(r"[^a-z0-9åäö]+", " ", intent.capability.casefold()).strip()
    vague = {
        "something",
        "something useful",
        "anything",
        "workflow",
        "a workflow",
        "något",
        "något användbart",
        "ett arbetsflöde",
    }
    if normalized not in vague:
        return None
    prompt = (
        "What concrete result should this skill produce, and for which recurring task?"
    )
    return ShapingPlan(
        intent.capability,
        0.0,
        (
            ShapingQuestion(
                key="clarification",
                title="Clarify the Intended Outcome",
                help_text=(
                    "Describe one recurring task and its desired result so Hund can create relevant steps and checks."
                ),
            ),
        ),
        clarification=prompt,
        source="fallback",
    )


def _clean_text(value: Any, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or len(text) > maximum or _INSTRUCTION_TERMS.search(text):
        return None
    return text


def _parse_model_plan(text: str, subject: str) -> ShapingPlan | None:
    cleaned_text = (text or "").strip()
    if "```" in cleaned_text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_text)
        if match:
            cleaned_text = match.group(1).strip()
    try:
        payload = json.loads(cleaned_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        return None
    raw_questions = payload["questions"]
    if not 1 <= len(raw_questions) <= 3:
        return None
    questions: list[ShapingQuestion] = []
    keys: set[str] = set()
    for item in raw_questions:
        if not isinstance(item, dict):
            return None
        key = _clean_text(item.get("key"), maximum=40)
        title = _clean_text(item.get("title"), maximum=80)
        help_text = _clean_text(item.get("help_text"), maximum=220)
        raw_options = item.get("options")
        default = _clean_text(item.get("default_option"), maximum=160)
        if (
            key is None
            or not _SAFE_NAME.fullmatch(key)
            or key in keys
            or title is None
            or help_text is None
            or not isinstance(raw_options, list)
            or not 2 <= len(raw_options) <= 4
        ):
            return None
        options = tuple(_clean_text(option, maximum=160) for option in raw_options)
        if any(option is None for option in options) or len(set(options)) != len(options):
            return None
        typed_options = tuple(option for option in options if option is not None)
        if default not in typed_options:
            default = typed_options[0]
        keys.add(key)
        questions.append(
            ShapingQuestion(key, title, help_text, typed_options, default)
        )
    confidence = payload.get("confidence", 0.9)
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        confidence = 0.9
    return ShapingPlan(subject, float(confidence), tuple(questions), source="model")


def build_shaping_plan(
    intent: SkillAuthoringIntent,
    snapshot: LocalInspectionSnapshot,
    *,
    client: Any = None,
    prior_answers: dict[str, str] | None = None,
    workspace: Path | None = None,
) -> ShapingPlan:
    """Generate a validated plan, falling back safely on every provider failure."""
    clarification = _clarification_plan(intent)
    if clarification is not None:
        return clarification
    fallback = ShapingPlan(
        intent.capability,
        0.7,
        _fallback_questions(intent),
        source="fallback",
    )
    if client is None:
        return fallback

    user_mems: list[str] = []
    proj_mems: list[str] = []
    try:
        from ..memory import list_active_memories
        from ..memory.models import SCOPE_USER_GLOBAL, SCOPE_PROJECT_PREFIX
        from ..paths import workspace_id as get_workspace_id

        user_mems = [m.content for m in list_active_memories(scope=SCOPE_USER_GLOBAL)]
        if workspace:
            ws_id = get_workspace_id(workspace)
            proj_mems = [m.content for m in list_active_memories(scope=f"{SCOPE_PROJECT_PREFIX}{ws_id}")]
    except Exception:
        pass

    context = sanitized_shaping_context(
        intent,
        snapshot,
        prior_answers,
        user_memories=user_mems,
        project_memories=proj_mems,
    )
    messages = [
        Message(
            role="system",
            content=(
                "Generate 1 to 3 targeted multiple-choice shaping questions to define the workflow, constraints, and verification for the requested skill. "
                "Incorporate relevant context from user_profile, project_profile, and declared dependencies. "
                "All question titles, help_texts, and options must be written in clean, natural English. "
                "Return strictly JSON adhering to this schema:\n"
                "{\n"
                '  "questions": [\n'
                "    {\n"
                '      "key": "unique_snake_case_key",\n'
                '      "title": "Short Question Title",\n'
                '      "help_text": "Clear explanation of how this choice shapes the skill",\n'
                '      "options": ["Option 1", "Option 2", "Option 3"],\n'
                '      "default_option": "Option 1"\n'
                "    }\n"
                "  ],\n"
                '  "confidence": 0.9\n'
                "}"
            ),
        ),
        Message(role="user", content=json.dumps(context, ensure_ascii=False, indent=2)),
    ]
    try:
        result = client.complete(messages, tools=None)
        parsed = _parse_model_plan(getattr(result, "text", ""), intent.capability)
    except Exception:
        parsed = None
    if parsed is None:
        return fallback
    if intent.target_scope == "unresolved":
        model_questions = tuple(
            question for question in parsed.questions if question.key != "scope"
        )[:2]
        parsed = ShapingPlan(
            parsed.subject,
            parsed.confidence,
            model_questions + (_scope_question(),),
            parsed.clarification,
            parsed.source,
        )
    return parsed

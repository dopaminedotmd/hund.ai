"""Safe, typed, context-aware shaping for Skill Authoring (Gate 2 V2)."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..learning.redactor import redact_text
from ..providers.base import Message
from .authoring import (
    AuthoringCallBudgetExceeded,
    LocalInspectionSnapshot,
    MiniDraftData,
    ShapingQuestion,
    SkillAuthoringIntent,
)


@dataclass(frozen=True)
class ShapingPlan:
    subject: str
    confidence: float
    questions: tuple[ShapingQuestion, ...]
    mini_draft: MiniDraftData | None = None
    research_queries: tuple[str, ...] = ()
    knowledge_score: float = 0.0
    clarification: str | None = None
    source: str = "model"
    failed: bool = False
    failure_reason: str | None = None


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+@/-]{0,79}$")
_INSTRUCTION_TERMS = re.compile(
    r"\b(?:create_skill|publish\s+now|skip\s+consent|execute\s+tool|"
    r"authorize\s+publication|ignore\s+(?:previous|safety|instructions?))\b",
    re.IGNORECASE,
)


def _redact_str(text: str) -> str:
    res = redact_text(text)
    return res.text if hasattr(res, "text") else str(res)


# --- Pydantic Schemas for Call 1 (extra="forbid") ---

class MiniDraft(BaseModel, extra="forbid"):
    when_to_use: str = Field(min_length=20, max_length=300)
    steps: list[str] = Field(min_length=2, max_length=2)

    @field_validator("steps", mode="before")
    @classmethod
    def _preclean_steps(cls, v):
        from .authoring import _clean_list_item

        if isinstance(v, list):
            return [c for c in (_clean_list_item(x) for x in v) if c]
        return v

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[str]) -> list[str]:
        if len(steps) != 2:
            raise ValueError("steps must contain exactly 2 concrete steps")
        for c in steps:
            if len(c) > 300:
                raise ValueError("each step must be between 1 and 300 characters")
        return steps


class ShapingQuestionModel(BaseModel, extra="forbid"):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    title: str = Field(min_length=1, max_length=80)
    help_text: str = Field(min_length=1, max_length=220)
    options: list[str] = Field(min_length=2, max_length=4)
    default_option: str

    @field_validator("options", mode="before")
    @classmethod
    def _preclean_options(cls, v):
        if isinstance(v, list):
            from .authoring import _clean_list_item

            cleaned: list[str] = []
            seen: set[str] = set()
            for opt in v:
                c = _clean_list_item(opt)
                if c and c.casefold() not in seen:
                    seen.add(c.casefold())
                    cleaned.append(c)
            return cleaned[:4]  # bounded options; host trims model over-supply
        return v

    @field_validator("options")
    @classmethod
    def validate_options(cls, options: list[str]) -> list[str]:
        if any(len(opt) > 160 for opt in options):
            raise ValueError("each option must be 1-160 characters")
        if not (2 <= len(options) <= 4):
            raise ValueError("options must contain between 2 and 4 unique items")
        return options

    @field_validator("default_option")
    @classmethod
    def validate_default(cls, default: str, info) -> str:
        options = info.data.get("options", [])
        cleaned_default = default.strip()
        if cleaned_default in options:
            return cleaned_default
        # Model pointed default at a trimmed/duplicate option; fall back to first.
        if options:
            return options[0]
        raise ValueError(f"default_option '{default}' must be one of options: {options}")


class ShapingCallOutput(BaseModel, extra="forbid"):
    mini_draft: MiniDraft
    questions: list[ShapingQuestionModel] = Field(default_factory=list, max_length=3)
    research_queries: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("research_queries")
    @classmethod
    def validate_queries(cls, queries: list[str]) -> list[str]:
        cleaned: list[str] = []
        for q in queries:
            c = q.strip()
            if len(c) > 160:
                raise ValueError("each research query must be <= 160 characters")
            if c:
                cleaned.append(c)
        return cleaned


# --- Helper Functions ---

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


def build_knowledge_packet(
    intent: SkillAuthoringIntent,
    snapshot: LocalInspectionSnapshot,
    prior_answers: dict[str, str] | None = None,
    user_memories: list[str] | None = None,
    project_memories: list[str] | None = None,
    session_history: list[str] | None = None,
    research_summaries: list[str] | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Build a bounded, redacted knowledge packet (<= 4000 chars) for shaping and synthesis."""
    # 1. Capability: redact, check instruction terms, truncate to 160
    redacted_cap = _redact_str(intent.capability)
    if _INSTRUCTION_TERMS.search(redacted_cap):
        raise ValueError(f"Instruction term detected in capability: {intent.capability}")
    safe_capability = redacted_cap[:160]

    # 2. Shaping answers: safe keys, redact values, filter instruction terms, truncate to 160
    safe_answers: dict[str, str] = {}
    for k, v in (prior_answers or {}).items():
        if not _SAFE_NAME.fullmatch(k[:40]):
            continue
        redacted_v = _redact_str(v)
        if _INSTRUCTION_TERMS.search(redacted_v):
            continue
        safe_answers[k[:40]] = redacted_v[:160]

    # 3. Verified memories
    user_mems: list[str] = []
    proj_mems: list[str] = []
    if user_memories is not None:
        user_mems = user_memories
    else:
        try:
            from ..memory import list_active_memories
            from ..memory.models import SCOPE_USER_GLOBAL
            user_mems = [m.statement for m in list_active_memories(scope=SCOPE_USER_GLOBAL, include_drafts=False)]
        except (sqlite3.Error, OSError):
            user_mems = []

    if project_memories is not None:
        proj_mems = project_memories
    elif workspace:
        try:
            from ..memory import list_active_memories
            from ..memory.models import SCOPE_PROJECT_PREFIX
            from ..paths import workspace_id as get_workspace_id
            ws_id = get_workspace_id(workspace)
            proj_mems = [m.statement for m in list_active_memories(scope=f"{SCOPE_PROJECT_PREFIX}{ws_id}", include_drafts=False)]
        except (sqlite3.Error, OSError):
            proj_mems = []

    safe_user_mems = [
        _redact_str(m)[:160]
        for m in user_mems
        if not _INSTRUCTION_TERMS.search(_redact_str(m))
    ][:10]

    safe_proj_mems = [
        _redact_str(m)[:160]
        for m in proj_mems
        if not _INSTRUCTION_TERMS.search(_redact_str(m))
    ][:10]

    # 4. Session history & research summaries
    safe_history = [
        _redact_str(h)[:800]
        for h in (session_history or [])
        if not _INSTRUCTION_TERMS.search(_redact_str(h))
    ][:5]

    safe_research = [
        _redact_str(r)[:800]
        for r in (research_summaries or [])
        if not _INSTRUCTION_TERMS.search(_redact_str(r))
    ][:5]

    packet: dict[str, Any] = {
        "requested_capability": safe_capability,
        "operation": intent.operation,
        "target_scope": intent.target_scope,
        "project_type": _project_type(snapshot),
        "config_files": _safe_names(snapshot.config_files_found),
        "declared_dependencies": _safe_names(snapshot.declared_dependencies),
        "available_tools": _safe_names(snapshot.registered_tools),
        "existing_skills": _safe_names(snapshot.scoped_skills),
        "prior_answers": safe_answers,
        "user_profile": safe_user_mems,
        "project_profile": safe_proj_mems,
    }
    if safe_history:
        packet["session_history"] = safe_history
    if safe_research:
        packet["research_summaries"] = safe_research

    # 5. Deterministic truncation to ensure <= 4 000 chars serialized
    serialized = json.dumps(packet, ensure_ascii=False)
    if len(serialized) > 4000:
        # Deterministically prune optional heavy fields
        for prune_key in ("session_history", "research_summaries", "project_profile", "user_profile"):
            if prune_key in packet:
                while packet[prune_key] and len(json.dumps(packet, ensure_ascii=False)) > 4000:
                    packet[prune_key].pop()
                if not packet[prune_key]:
                    del packet[prune_key]
                if len(json.dumps(packet, ensure_ascii=False)) <= 4000:
                    break

    return packet


def sanitized_shaping_context(
    intent: SkillAuthoringIntent,
    snapshot: LocalInspectionSnapshot,
    prior_answers: dict[str, str] | None = None,
    user_memories: list[str] | None = None,
    project_memories: list[str] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper around build_knowledge_packet."""
    return build_knowledge_packet(
        intent,
        snapshot,
        prior_answers=prior_answers,
        user_memories=user_memories,
        project_memories=project_memories,
    )


def compute_knowledge_score(
    capability: str,
    verified_memories: list[str],
    config_and_deps: list[str],
    tools: list[str],
    existing_skills: list[str],
    research_queries: tuple[str, ...] | list[str],
) -> float:
    """Calculate deterministic knowledge score from 5 boolean signals."""
    tokens = {t.lower() for t in re.findall(r"[a-z0-9_]{3,}", capability.lower())}
    if not tokens:
        tokens = {capability.lower()}

    def has_match(pool: list[str]) -> bool:
        return any(
            any(tok in item.lower() for tok in tokens)
            for item in pool
        )

    s1 = bool(verified_memories and has_match(verified_memories))
    s2 = bool(config_and_deps and has_match(config_and_deps))
    s3 = bool(tools and has_match(tools))
    s4 = bool(existing_skills and has_match(existing_skills))
    s5 = bool(len(research_queries) == 0)

    return (int(s1) + int(s2) + int(s3) + int(s4) + int(s5)) / 5.0


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
        subject=intent.capability,
        confidence=0.0,
        questions=(
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


def _extract_json_block(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>", "", cleaned).strip()
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            return match.group(1).strip()
    return cleaned


def build_shaping_plan(
    intent: SkillAuthoringIntent,
    snapshot: LocalInspectionSnapshot,
    *,
    client: Any = None,
    prior_answers: dict[str, str] | None = None,
    workspace: Path | None = None,
    run_id: str | None = None,
) -> ShapingPlan:
    """Execute Call 1 (shaping) to generate mini-draft, gap questions, and research queries."""
    clarification = _clarification_plan(intent)
    if clarification is not None:
        return clarification

    if client is None:
        return ShapingPlan(
            subject=intent.capability,
            confidence=0.0,
            questions=(),
            failed=True,
            failure_reason="No provider client available for shaping call",
            source="failed",
        )

    try:
        packet = build_knowledge_packet(
            intent,
            snapshot,
            prior_answers=prior_answers,
            workspace=workspace,
        )
    except Exception as exc:
        return ShapingPlan(
            subject=intent.capability,
            confidence=0.0,
            questions=(),
            failed=True,
            failure_reason=f"Knowledge packet construction failed: {exc}",
            source="failed",
        )

    system_prompt = (
        "You are an expert AI skill shaping specialist. "
        "CRITICAL LANGUAGE RULE: Write the mini-draft (when_to_use and steps) strictly in ENGLISH regardless of the user's input language. "
        "VERSION INTEGRITY RULE: Version strings provided in the user request or capability (e.g. '26.2', '1.21.1') are opaque identifiers. You MUST copy and preserve them verbatim. NEVER add, remove, or alter prefixes or digits (never rewrite 26.2 to 1.26.2). NEVER invent a version that is neither stated by the user nor found in research. "
        "WORKSPACE RULE: The untrusted_data contains facts about the CURRENT workspace (project_type, config_files, declared_dependencies, available_tools). "
        "These describe where Hund runs, NOT what the skill must be about. Shape the skill around the user's REQUESTED CAPABILITY only. "
        "If the request is about a domain outside the workspace (music, writing, design, ops on other systems, etc.), IGNORE project_type/config/dependencies entirely. "
        "Only use workspace facts when the requested capability is explicitly about this project's own code, tooling or repository. "
        "Define a concrete mini-draft (when_to_use and exactly 2 steps in English), identify 0 to 3 genuine knowledge gap questions, "
        "and suggest 0 to 3 targeted external research queries if external documentation is needed. "
        "When the subject involves software development, frameworks, libraries, or tooling, prioritize queries targeting official example repositories, GitHub templates, MDKs, and build configuration files (e.g. build.gradle, package.json) over generic tutorial guides.\n"
        "Return strictly JSON adhering to this schema with NO extra fields:\n"
        "{\n"
        '  "mini_draft": {\n'
        '    "when_to_use": "Specific description of when to invoke this skill in English (20-300 chars)",\n'
        '    "steps": [\n'
        '      "Concrete actionable instruction as plain text, no numbering prefix, max 200 chars",\n'
        '      "Second concrete actionable instruction as plain text, no numbering prefix"\n'
        "    ]  (exactly 2 items, each its own array element, never more, never empty)\n"
        "  },\n"
        '  "questions": [\n'
        "    {\n"
        '      "key": "snake_case_key",\n'
        '      "title": "Question Title",\n'
        '      "help_text": "Why this choice matters for shaping",\n'
        '      "options": ["Option 1", "Option 2"],\n'
        '      "default_option": "Option 1"\n'
        "    }\n"
        "  ],\n"
        '  "research_queries": ["optional query 1", "optional query 2"]\n'
        "}"
    )

    user_prompt = json.dumps(
        {"untrusted_data": packet},
        ensure_ascii=False,
        indent=2,
    )

    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    try:
        import time
        t0 = time.time()
        result = client.complete(messages, tools=None, max_tokens=2500)
        latency_ms = int((time.time() - t0) * 1000)
        from .authoring import log_authoring_request
        log_authoring_request(client, result, "authoring_shaping", run_id=run_id, latency_ms=latency_ms)

        raw_text = getattr(result, "text", None) or getattr(result, "content", None) or ""
        json_text = _extract_json_block(raw_text)
        parsed = ShapingCallOutput.model_validate_json(json_text)
    except Exception as exc:
        return ShapingPlan(
            subject=intent.capability,
            confidence=0.0,
            questions=(),
            failed=True,
            failure_reason=f"Shaping provider completion or validation failed: {exc}",
            source="failed",
        )

    # 1. Mini-draft
    mini_draft = MiniDraftData(
        when_to_use=parsed.mini_draft.when_to_use,
        steps=tuple(parsed.mini_draft.steps),
    )

    # 2. Research queries
    if intent.local_only:
        research_queries: tuple[str, ...] = ()
    elif intent.requires_research and not parsed.research_queries:
        research_queries = (intent.capability[:160],)
    else:
        research_queries = tuple(parsed.research_queries)

    # 3. Knowledge score
    user_mems = packet.get("user_profile", []) + packet.get("project_profile", [])
    config_deps = packet.get("config_files", []) + packet.get("declared_dependencies", [])
    tools = packet.get("available_tools", [])
    existing_skills = packet.get("existing_skills", [])

    k_score = compute_knowledge_score(
        capability=intent.capability,
        verified_memories=user_mems,
        config_and_deps=config_deps,
        tools=tools,
        existing_skills=existing_skills,
        research_queries=research_queries,
    )

    # 4. Questions & scope reservation
    model_questions = [
        ShapingQuestion(
            key=q.key,
            title=q.title,
            help_text=q.help_text,
            options=tuple(q.options),
            default=q.default_option,
        )
        for q in parsed.questions
        if q.key != "scope"
    ]

    # If knowledge score is high (> 0.8), model gap questions are skipped!
    if k_score > 0.8:
        model_questions = []

    if intent.target_scope == "unresolved":
        # Reserve 1 of 3 slots for scope question; keep at most 2 model questions
        final_questions = tuple(model_questions[:2]) + (_scope_question(),)
    else:
        final_questions = tuple(model_questions[:3])

    return ShapingPlan(
        subject=intent.capability,
        confidence=1.0,
        questions=final_questions,
        mini_draft=mini_draft,
        research_queries=research_queries,
        knowledge_score=k_score,
        source="model",
    )


class RefinedQueriesOutput(BaseModel, extra="ignore"):
    queries: list[str] = Field(default_factory=list)
    fallback_query: str = Field(default="")


def refine_research_queries(
    subject: str,
    shaping_answers: dict[str, str],
    mini_draft: MiniDraftData | None = None,
    existing_queries: tuple[str, ...] = (),
    *,
    client: Any = None,
    run_id: str | None = None,
) -> tuple[tuple[str, ...], str]:
    """Refine research queries using user shaping answers (Call 1b).

    Ensures that when a user selects a specific variant (e.g. Fabric), queries focus solely
    on that variant and never conflate competing alternatives (e.g. Forge/NeoForge).
    Returns (refined_queries, fallback_query).
    """
    _VERSION_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)+\b")
    combined_context = f"{subject} {' '.join(shaping_answers.values())}"
    version_matches = _VERSION_TOKEN_RE.findall(combined_context)

    if version_matches:
        domain_candidate = _VERSION_TOKEN_RE.sub("", subject).strip()
        domain_clean = re.sub(r"\s+", " ", domain_candidate).strip() or "project"
        default_fallback = f"latest {domain_clean} version"[:160]
    else:
        default_fallback = f"{subject} setup getting started"[:160]

    # Quick deterministic check for conflicting loader / variant answers
    cleaned_existing: list[str] = []
    variant_hints = [v.lower() for v in shaping_answers.values() if v]

    for q in existing_queries:
        q_lower = q.lower()
        if "fabric" in variant_hints and ("forge" in q_lower or "neoforge" in q_lower):
            cleaned_q = re.sub(r"(?i)\b(?:neo)?forge\b", "", q).strip()
            if cleaned_q:
                cleaned_existing.append(cleaned_q)
        elif ("forge" in variant_hints or "neoforge" in variant_hints) and "fabric" in q_lower:
            cleaned_q = re.sub(r"(?i)\bfabric\b", "", q).strip()
            if cleaned_q:
                cleaned_existing.append(cleaned_q)
        else:
            cleaned_existing.append(q)

    if version_matches and not any(any(vm in q for vm in version_matches) for q in cleaned_existing):
        cleaned_existing.insert(0, f"{subject} fabric yarn mappings"[:160])

    fallback_queries = tuple(cleaned_existing) if cleaned_existing else existing_queries

    if client is None:
        return (fallback_queries[:3], default_fallback)

    system_prompt = (
        "You are Hund's research query refinement engine (Call 1b).\n"
        "Given the capability subject, confirmed mini-draft, and user shaping answers, "
        "generate 1-3 targeted, non-conflicting web search queries to find official documentation, MDKs, and GitHub templates.\n"
        "CRITICAL RULES:\n"
        "1. VERSION INTEGRITY: Version strings from user or answers (e.g. '26.2') are opaque identifiers. Preserve them verbatim (never alter or prefix them, e.g. never rewrite 26.2 to 1.26.2). Do not invent versions. If a version token is present, at least one query MUST be an exact verification search targeting that version token (e.g. 'Minecraft 26.2 fabric yarn mappings').\n"
        "2. CONCURRENCY & EXCLUSIVITY: If the user selected a specific framework, variant, or loader (e.g. 'Fabric'), you MUST ONLY search for that specific choice. NEVER include conflicting alternatives (e.g. Forge, NeoForge).\n"
        "3. CODE & SDK FOCUS: For programming/code skills, prioritize official example repos, templates, MDKs, and build files (e.g. 'FabricMC fabric-example-mod build.gradle').\n"
        "4. CONCISE: Each query must be <= 160 characters. Maximum 3 queries.\n"
        "5. FALLBACK QUERY: Provide exactly one broad fallback query to use if specific queries return no results. If a version token is present in the subject or answers, the fallback query MUST be 'latest <domain> version' (e.g. 'latest minecraft version').\n"
        "6. ENGLISH ONLY: All queries must be strictly in English.\n"
        "Return strictly JSON adhering to this schema with NO extra fields:\n"
        "{\n"
        '  "queries": ["query 1", "query 2"],\n'
        '  "fallback_query": "broad fallback query"\n'
        "}"
    )

    user_payload = {
        "subject": subject,
        "shaping_answers": shaping_answers,
        "mini_draft": {
            "when_to_use": mini_draft.when_to_use,
            "steps": list(mini_draft.steps),
        } if mini_draft else None,
        "draft_queries": list(existing_queries),
    }

    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=json.dumps(user_payload, ensure_ascii=False, indent=2)),
    ]

    try:
        import time
        t0 = time.time()
        result = client.complete(messages, tools=None, max_tokens=1000)
        latency_ms = int((time.time() - t0) * 1000)
        from .authoring import log_authoring_request
        log_authoring_request(client, result, "authoring_query_refine", run_id=run_id, latency_ms=latency_ms)

        raw_text = getattr(result, "text", None) or getattr(result, "content", None) or ""
        json_text = _extract_json_block(raw_text)
        parsed = RefinedQueriesOutput.model_validate_json(json_text)
        raw_queries = [q.strip()[:160] for q in parsed.queries if q.strip()]
        if version_matches and not any(any(vm in q for vm in version_matches) for q in raw_queries):
            raw_queries.insert(0, f"{subject} fabric yarn mappings"[:160])
        queries = tuple(raw_queries[:3])
        fallback = (parsed.fallback_query or default_fallback).strip()[:160]
        if queries:
            return (queries, fallback)
    except AuthoringCallBudgetExceeded:
        # Track 19: budget violations must stop the attempt, not fall back.
        raise
    except Exception:
        pass

    return (fallback_queries, default_fallback)


"""Deterministic task policy classifier and brief derivation."""
from __future__ import annotations

import re
from pathlib import Path
from .task_brief import ResponseFormat, TaskBrief, TaskType


# Regular expression pattern matchers for deterministic classification
_SYSTEM_PATTERNS = [
    r"\b(?:what|show|check|tell\s+me\s+about)\s+(?:me\s+)?(?:my\s+)?.*(?:system|hardware|specs|pc|computer|machine|cpu|gpu|ram|vram|disk|storage|os)\b",
    r"\b(?:what|show|check)\b.*\b(?:cpu|gpu|ram|vram|hardware|specs)\b",
    r"\b(?:vad\s+har\s+jag\s+för|visa|berätta\s+om\s+min)\s+.*(?:hårdvara|dator|maskin|processor|cpu|gpu|grafikkort|ram|minne|disk|lagring|os|system)\b",
    r"\bhur\s+mycket\s+(?:ram|minne|disk|lagringsutrymme|vram)\b",
    r"\b(?:system\s+specs|hardware\s+info|specs\s+för\s+datorn)\b",
]

_RECOMMENDATION_PATTERNS = [
    r"\b(?:which|recommend|what)\s+(?:a\s+)?(?:local\s+)?(?:model|llm)\b",
    r"\bcan\s+i\s+run\s+(?:llama|deepseek|qwen|mistral|gemma|phi|local\s+model)\b",
    r"\b(?:vilken|rekommendera)\s+(?:en\s+)?(?:lokal\s+)?modell\b",
    r"\bpassar\s+(?:llama|deepseek|qwen|mistral|modellen)\s+på\s+(?:min|denna)\s+dator\b",
    r"\bkan\s+jag\s+köra\s+(?:deepseek|llama|qwen|mistral|lokalt|lokala\s+modeller)\b",
]

_DIAGNOSIS_PATTERNS = [
    r"\b(?:run|check)\s+doctor\b",
    r"\b(?:kör|kolla)\s+doctor\b",
    r"\b(?:diagnos|health\s+check|system\s+health)\b",
    r"\bvarför\s+syns\s+.*inte\b",
    r"\bvarför\s+fungerar\s+.*inte\b",
    r"\bwhy\s+does\s+.*not\s+(?:work|show|appear)\b",
    r"\bkontrollera\s+installerad\s+version\b",
    r"\bcheck\s+installed\s+version\b",
]

_WEB_RESEARCH_PATTERNS = [
    r"\b(?:latest|newest|current)\s+(?:version|release|news|docs|pricing)\s+of\b",
    r"\b(?:senaste|nyaste|aktuella)\s+(?:versionen|releasen|nyheter|dokumentation)\s+(?:av|om|för)\b",
    r"\bwhen\s+(?:did|was)\s+.*\s+released\b",
    r"\bnär\s+släpptes\b",
]

_CODE_MODIFICATION_PATTERNS = [
    r"\b(?:create|write|implement|refactor|fix|update|edit|add\s+test)\s+(?:a\s+)?(?:file|function|class|code|feature|test|bug)\b",
    r"\b(?:skapa|skriv|implementera|refaktorera|fixa|uppdatera|ändra|lägg\s+till\s+test)\s+(?:en\s+)?(?:fil|funktion|klass|kod|test|bugg)\b",
]

_CODE_INSPECTION_PATTERNS = [
    r"\b(?:search|find|where\s+is|read|inspect|show\s+code)\b",
    r"\b(?:sök|hitta|var\s+ligger|läs\s+fil|inspektera|visa\s+kod)\b",
    r"\bvilken\s+kod\s+renderar\b",
    r"\bwhich\s+code\s+renders\b",
    r"@file:",
]

_CURRENT_STATE_PATTERNS = [
    r"\b(?:vilka|vad\s+för)\s+(?:skills?|förmågor|modeller)\s+(?:är\s+aktiva|har\s+hund|körs?|används?)\b",
    r"\b(?:what|which)\s+(?:skills?|models?)\s+(?:are\s+active|is\s+active|are\s+loaded|is\s+loaded|running)\b",
    r"\b(?:aktiv\s+modell|aktiva\s+skills|aktiva\s+förmågor|nuvarande\s+status|current\s+model|active\s+skills)\b",
]

_SELF_KNOWLEDGE_PATTERNS = [
    r"\b(?:hur\s+fungerar|vad\s+är|berätta\s+om|förklara)\s+(?:en\s+)?(?:skills?|färdighet(?:er|erna)?)\b",
    r"\b(?:what\s+is|what\s+are|how\s+do|how\s+does)\s+(?:a\s+)?skills?\s*(?:work)?\b",
    r"\b(?:hur\s+ser\s+jag|var\s+ser\s+jag|var\s+hittar\s+jag|var\s+hanterar\s+jag|hur\s+använder\s+jag)\s+.*(?:skills?(?:en)?|färdighet(?:er|erna)?)\b",
    r"\b(?:how\s+do\s+i\s+see|where\s+do\s+i\s+see|where\s+do\s+i\s+find|where\s+do\s+i\s+manage|how\s+do\s+i\s+use)\s+.*skills?\b",
    r"\b(?:vad\s+kan\s+jag\s+göra\s+i|vad\s+gör|hur\s+fungerar|vad\s+innebär|hur\s+används)\s+/(?:[a-z0-9_-]+)\b",
    r"\b(?:what\s+does|how\s+does|what\s+can\s+i\s+do\s+in)\s+/(?:[a-z0-9_-]+)\b",
    r"\bwhat\s+does\s+/(?:[a-z0-9_-]+)\s+(?:do|mean)\b",
    r"\b(?:vilka\s+kommandon\s+finns|vad\s+finns\s+det\s+för\s+kommandon|visa\s+alla\s+kommandon|vilka\s+slash-kommandon\s+finns)\b",
    r"\b(?:what\s+commands\s+are\s+available|list\s+commands|available\s+commands|show\s+commands)\b",
    r"\b(?:hur\s+rensar\s+jag\s+skärmen|how\s+do\s+i\s+clear\s+the\s+screen)\b",
]


def classify_task(user_text: str, workspace: Path | None = None) -> TaskBrief:
    """Classify user query and derive an immutable TaskBrief with conservative fallback."""
    text = (user_text or "").strip()
    if not text:
        return TaskBrief(
            task_type=TaskType.DIRECT_ANSWER,
            requested_outcome="Empty input fallback",
            confidence=1.0,
            scope="general",
        )

    # 0. On-Demand Skill Authoring Intent
    from ..skills.authoring import detect_explicit_skill_intent
    skill_intent = detect_explicit_skill_intent(text)
    if skill_intent is not None:
        return TaskBrief(
            task_type=TaskType.SKILL_AUTHORING,
            requested_outcome="Author and publish declarative skill via registered create_skill tool",
            confidence=skill_intent.confidence,
            scope="workspace" if workspace else "general",
            needs_workspace_context=True,
            preferred_format=ResponseFormat.PROSE,
        )

    # 1. Current Runtime State (from typed providers, zero tools)
    for pattern in _CURRENT_STATE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            from .capability_self_model import find_matching_capabilities
            caps = find_matching_capabilities(text)
            cmd_name = caps[0].id if caps else "skills"
            return TaskBrief(
                task_type=TaskType.CURRENT_STATE,
                requested_outcome=f"Report active state from typed provider for {cmd_name}",
                confidence=0.95,
                scope="general",
                needs_environment_facts=False,
                needs_workspace_context=False,
                needs_web_research=False,
                preferred_format=ResponseFormat.PROSE,
                relevant_command=cmd_name,
            )

    # 2. Health Diagnosis / Troubleshooting
    for pattern in _DIAGNOSIS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return TaskBrief(
                task_type=TaskType.DIAGNOSIS,
                requested_outcome="Diagnose system health, issues, and configuration",
                confidence=0.90,
                scope="system",
                needs_environment_facts=True,
                environment_freshness="dynamic_refresh",
            )

    # 3. Local Code Modification
    for pattern in _CODE_MODIFICATION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return TaskBrief(
                task_type=TaskType.LOCAL_CODE_MODIFICATION,
                requested_outcome="Create or modify workspace files and code",
                confidence=0.85,
                scope="workspace",
                needs_workspace_context=True,
                show_code=False,
            )

    # 4. Local Code Inspection
    for pattern in _CODE_INSPECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return TaskBrief(
                task_type=TaskType.LOCAL_CODE_INSPECTION,
                requested_outcome="Inspect and analyze workspace code or files",
                confidence=0.80,
                scope="workspace",
                needs_workspace_context=True,
                preferred_format=ResponseFormat.PROSE,
            )

    # 5. Self-Knowledge / Slash Commands / UI Capabilities (Direct Answers)
    for pattern in _SELF_KNOWLEDGE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            from .capability_self_model import find_matching_capabilities
            caps = find_matching_capabilities(text)
            cmd_name = caps[0].id if caps else "help"
            return TaskBrief(
                task_type=TaskType.SELF_KNOWLEDGE,
                requested_outcome=f"Explain slash command or UI capability metadata: /{cmd_name}",
                confidence=0.95,
                scope="general",
                needs_environment_facts=False,
                needs_workspace_context=False,
                needs_web_research=False,
                preferred_format=ResponseFormat.PROSE,
                relevant_command=cmd_name,
            )

    # 5. System & Hardware Inspection
    for pattern in _SYSTEM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return TaskBrief(
                task_type=TaskType.SYSTEM_INSPECTION,
                requested_outcome="Inspect and report host system hardware and environment facts",
                confidence=0.95,
                scope="system",
                needs_environment_facts=True,
                environment_freshness="session_static",
                preferred_format=ResponseFormat.PROSE,
            )

    # 6. Local Model / Resource Recommendations
    for pattern in _RECOMMENDATION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return TaskBrief(
                task_type=TaskType.RECOMMENDATION,
                requested_outcome="Evaluate and recommend compatible local models or hardware fit",
                confidence=0.90,
                scope="system",
                needs_environment_facts=True,
                environment_freshness="dynamic_refresh",
                requires_disk_vram_separation=True,
                preferred_format=ResponseFormat.LIST,
                requires_uncertainty_disclosure=True,
            )

    # 7. Web Research
    for pattern in _WEB_RESEARCH_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return TaskBrief(
                task_type=TaskType.WEB_RESEARCH,
                requested_outcome="Research time-sensitive, external, or latest factual information",
                confidence=0.85,
                scope="external",
                needs_web_research=True,
                preferred_format=ResponseFormat.PROSE,
            )

    # 8. Conservative Fallback (General Q&A)
    return TaskBrief(
        task_type=TaskType.DIRECT_ANSWER,
        requested_outcome="Direct response to general query",
        confidence=0.50,
        scope="general",
        preferred_format=ResponseFormat.PROSE,
    )

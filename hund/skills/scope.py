"""Scoped identity, workspace key hashing, and scope resolution for skills."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable

from .model import Skill


@dataclass(frozen=True)
class ScopedSkillId:
    scope_key: str  # "global" or 16-char sha256 hex digest of normalized workspace root path
    capability_id: str
    name: str


@dataclass(frozen=True)
class ScopeResolution:
    status: str  # "RESOLVED" | "CLARIFICATION_REQUIRED" | "REJECTED"
    action: str | None = None  # "CREATE" | "UPDATE"
    target_scope: str | None = None  # "global" | "project"
    workspace_key: str | None = None
    capability_id: str | None = None
    target_name: str | None = None
    existing_skill: Any | None = None  # Skill | None
    is_shadowing: bool = False
    reason: str = ""


def compute_workspace_key(workspace_path: Path | str | None) -> str:
    """Compute deterministic 16-char hex key from workspace path.

    Returns "global" if workspace_path is None or already "global".
    """
    if workspace_path is None:
        return "global"
    if isinstance(workspace_path, str) and workspace_path == "global":
        return "global"

    path = Path(workspace_path).resolve()
    normalized = str(path).casefold().replace("\\", "/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


_SWEDISH_TO_ENGLISH_TERMS = {
    "planeringsfiler": "planning-files",
    "planeringsfil": "planning-files",
    "planering": "planning",
    "planera": "planning",
    "strukturerad": "structured",
    "strukturerat": "structured",
    "skriva": "authoring",
    "skriver": "authoring",
    "skriv": "authoring",
    "skapa": "creation",
    "bygga": "build",
    "bygg": "build",
    "testa": "testing",
    "testning": "testing",
    "tester": "tests",
    "felsöka": "debugging",
    "felsökning": "debugging",
    "refaktorera": "refactoring",
    "refaktorisering": "refactoring",
    "granska": "review",
    "granskning": "review",
    "kodgranskning": "code-review",
    "kod": "code",
    "databas": "database",
    "databaser": "databases",
    "databasmigrering": "database-migration",
    "migrering": "migration",
    "migrera": "migrate",
    "driftsätta": "deployment",
    "driftsättning": "deployment",
    "distribuera": "deployment",
    "distribution": "deployment",
    "dokumentera": "documentation",
    "dokumentation": "documentation",
    "översätta": "translation",
    "översättning": "translation",
    "säkerhet": "security",
    "prestanda": "performance",
    "optimering": "optimization",
    "optimera": "optimize",
    "filer": "files",
    "fil": "file",
    "hantera": "manage",
    "hantering": "management",
    "arkitektur": "architecture",
    "analysera": "analysis",
    "analys": "analysis",
    "funktioner": "functions",
    "funktion": "function",
    "komponenter": "components",
    "komponent": "component",
    "gränssnitt": "interface",
    "ändringar": "changes",
    "ändra": "modify",
    "ändrar": "modify",
    "uppdatera": "update",
    "uppdaterar": "update",
    "uppdatering": "update",
    "sida": "page",
    "sidor": "pages",
    "sidan": "page",
    "sidorna": "pages",
    "designa": "design",
    "designar": "design",
    "utforma": "design",
    "utformar": "design",
    "generera": "generate",
    "genererar": "generate",
    "planerar": "planning",
    "bygger": "build",
    "testar": "testing",
    "felsöker": "debugging",
    "refaktorerar": "refactoring",
    "granskar": "review",
    "skapar": "creation",
    "filen": "file",
    "filerna": "files",
    "optimerar": "optimize",
    "hanterar": "manage",
    "analyserar": "analysis",
    "översätter": "translation",
    "migrerar": "migration",
    "driftsätter": "deployment",
    "språk": "language",
    "prompt": "prompt",
    "prompter": "prompts",
    "modell": "model",
    "modeller": "models",
    "kundsupport": "customer-support",
    "support": "support",
    "kundservice": "customer-service",
    "kundtjänst": "customer-service",
    "kundtjanst": "customer-service",
    "marknadsföring": "marketing",
    "marknadsforing": "marketing",
    "marknad": "marketing",
    "försäljning": "sales",
    "forsaljning": "sales",
    "uppsökande": "outreach",
    "checklista": "checklist",
    "checklistor": "checklists",
    "granskningslista": "review-checklist",
    "projekt": "project",
    "projektet": "project",
    "projektplanering": "project-planning",
    "projektplan": "project-plan",
}

_STOP_WORDS = {
    # Conjunctions / Prepositions
    "and", "och", "för", "for", "med", "with", "att", "to", "in", "i", "av", "of", "en", "ett", "a", "an",
    "the", "den", "det", "de", "dem", "så", "sa", "som", "på", "pa", "om", "till", "från", "fran", "from",
    # Pronouns
    "jag", "mig", "du", "dig", "vi", "oss", "man", "han", "honom", "hon", "henne", "sin", "sitt", "sina",
    "i", "me", "my", "you", "your", "we", "us", "our", "he", "him", "she", "her", "they", "them", "their", "it", "its",
    # Auxiliaries / Common verbs
    "gör", "gor", "göra", "gjorde", "gjort", "blir", "bli", "blivit", "är", "ar", "var", "vara", "varit",
    "ska", "skall", "skulle", "kan", "kunde", "kunna", "vill", "ville", "ha", "har", "hade", "haft",
    "få", "far", "får", "fick", "fått",
    "do", "does", "doing", "did", "done", "make", "makes", "making", "made", "become", "becomes", "be", "is", "are",
    "was", "were", "been", "being", "shall", "should", "will", "would", "can", "could", "have", "has", "had", "having",
    "get", "gets", "getting", "got", "gotten",
    # Modifiers / Fillers / Speech disfluencies
    "när", "nar", "when", "hur", "how", "bättre", "battre", "better", "mer", "mera", "mest", "more", "most",
    "mycket", "much", "bra", "good", "såhär", "sahar", "lite", "här", "har", "där", "dar",
    "eh", "öhm", "ohm", "ehm", "um", "uh", "liksom", "typ", "upp", "ner", "nerå", "sådär", "sån", "sånt",
    "hjälp", "hjalp", "hjälpa", "hjalpa", "hjälper", "hjalper", "help", "helps", "helping", "helped",
    # Swedish & English marketing buzzwords / hype to filter from technical slugs
    "extremt", "extrem", "extreme", "hög", "hog", "high", "bästa", "basta", "best",
    "grym", "grymt", "awesome", "fantastisk", "otrolig", "super", "mega", "ultra", "value",
    # Generic action verbs when preceding a domain noun
    "skriver", "skriva", "skriv", "write", "writes", "writing", "author", "authoring",
    "skapa", "skapar", "create", "creates", "creating", "bygga", "bygger", "build", "builds", "building",
    "designa", "designar", "designs", "designing", "utforma", "utformar", "generera", "genererar",
}

_MARKETING_BUZZWORDS = frozenset({
    "extremt", "extrem", "extreme",
    "hög", "hog", "high",
    "bästa", "basta", "best",
    "grym", "grymt", "awesome",
    "fantastisk", "otrolig",
    "super", "mega", "ultra",
    "value",
    "världsklass", "varldsklass", "world-class", "worldclass",
    "världsledande", "varldsledande", "top-tier", "best-in-class", "world",
})


def _slug(value: str) -> str:
    """Generate clean English canonical slug from user input."""
    raw = (value or "").strip().casefold()
    if not raw:
        return "learned-skill"

    # Normalize multi-word buzzword phrases before splitting
    raw = re.sub(r"\bworld\s+class\b", "worldclass", raw)
    raw = re.sub(r"\bi\s+v[äa]rldsklass\b", "varldsklass", raw)
    raw = re.sub(r"\btop\s+tier\b", "top-tier", raw)
    raw = re.sub(r"\bbest\s+in\s+class\b", "best-in-class", raw)
    raw = re.sub(r"\bv[äa]rldsledande\b", "varldsledande", raw)
    raw = re.sub(r"\bworld\s+leading\b", "world-leading", raw)
    if not raw:
        return "learned-skill"

    # Split into words
    words = re.findall(r"[a-z0-9åäöéèü_-]+", raw)
    english_parts: list[str] = []
    for w in words:
        if w in _STOP_WORDS or w in _MARKETING_BUZZWORDS:
            continue
        if w in _SWEDISH_TO_ENGLISH_TERMS:
            english_parts.append(_SWEDISH_TO_ENGLISH_TERMS[w])
        else:
            # Normalize Swedish vowels if unmapped
            cleaned_word = w.replace("å", "a").replace("ä", "a").replace("ö", "o").replace("é", "e").replace("ü", "u")
            cleaned_word = re.sub(r"[^a-z0-9_-]+", "", cleaned_word)
            if cleaned_word and cleaned_word not in _STOP_WORDS and cleaned_word not in _MARKETING_BUZZWORDS:
                english_parts.append(cleaned_word)

    # De-duplicate consecutive identical parts and limit to 4 key terms
    filtered: list[str] = []
    for p in english_parts:
        # Split terms like planning-files
        for sub in p.split("-"):
            if sub and sub not in _STOP_WORDS and sub not in _MARKETING_BUZZWORDS and (not filtered or filtered[-1] != sub):
                filtered.append(sub)

    combined = "-".join(filtered[:4])
    combined = re.sub(r"-+", "-", combined).strip("-")
    return (combined or "learned-skill")[:40]


def derive_technical_skill_name(
    topic: str,
    shaping_answers: dict[str, Any] | None = None,
    base_name: str | None = None,
) -> str:
    """Derive clean technical skill name from topic and shaping answers, filtering marketing buzzwords."""
    shaping_parts: list[str] = []
    if shaping_answers:
        for key in ("style", "content", "format", "framework", "target", "focus", "domain", "type"):
            val = str(shaping_answers.get(key, "")).strip().casefold()
            if val:
                for word in re.findall(r"[a-z0-9åäöéèü_-]+", val):
                    slug_w = _slug(word)
                    for part in slug_w.split("-"):
                        if (
                            part
                            and part != "learned-skill"
                            and part not in _MARKETING_BUZZWORDS
                            and part not in _STOP_WORDS
                            and part not in shaping_parts
                        ):
                            shaping_parts.append(part)

    raw_topic = base_name or topic or ""
    slug_topic = _slug(raw_topic)
    topic_parts = [
        p for p in slug_topic.split("-")
        if p and p != "learned-skill" and p not in _MARKETING_BUZZWORDS and p not in _STOP_WORDS
    ]

    combined_parts: list[str] = []
    for p in shaping_parts:
        if p not in combined_parts and p not in _MARKETING_BUZZWORDS and p not in _STOP_WORDS:
            combined_parts.append(p)
    for p in topic_parts:
        if p not in combined_parts and p not in _MARKETING_BUZZWORDS and p not in _STOP_WORDS:
            combined_parts.append(p)

    if combined_parts:
        name = "-".join(combined_parts[:4])
        return re.sub(r"-+", "-", name).strip("-")[:40]

    return "learned-skill"


def resolve_scope_and_overlap(
    intent: Any,  # SkillAuthoringIntent
    workspace_key: str,
    existing_skills: list[Skill],
    builtins: list[Skill],
    shaping_answers: dict[str, Any] | None = None,
) -> ScopeResolution:
    """Resolve target scope, lineage update, overlap, and collision against existing skills."""
    raw_name = getattr(intent, "referenced_name", None) or getattr(intent, "capability", "")
    target_name = derive_technical_skill_name(raw_name, shaping_answers=shaping_answers)
    capability_id = f"general/{target_name}"

    # 1. Builtin collision check — fail closed to REJECTED
    builtin_names = {b.name for b in builtins}
    if target_name in builtin_names:
        return ScopeResolution(
            status="REJECTED",
            workspace_key=workspace_key,
            target_name=target_name,
            capability_id=capability_id,
            reason=f"Cannot overwrite or shadow constitutional builtin skill '{target_name}'.",
        )

    # 2. Determine target scope
    intent_scope = getattr(intent, "target_scope", "unresolved")
    if intent_scope == "global":
        resolved_scope = "global"
        eff_ws_key = "global"
    elif intent_scope == "project":
        resolved_scope = "project"
        eff_ws_key = workspace_key
    elif workspace_key != "global":
        resolved_scope = "project"
        eff_ws_key = workspace_key
    else:
        resolved_scope = "global"
        eff_ws_key = "global"

    # If ambiguous and no workspace available
    if intent_scope == "unresolved" and workspace_key == "global" and getattr(intent, "operation", "create") == "create" and "project" in getattr(intent, "raw_prompt", "").lower():
        return ScopeResolution(
            status="CLARIFICATION_REQUIRED",
            workspace_key="global",
            target_name=target_name,
            capability_id=capability_id,
            reason="Unclear target scope: project scope requested but no workspace root active. Specify global or project scope.",
        )

    # 3. Match against existing skills in scope
    existing_in_scope = [
        s for s in existing_skills
        if (s.scope == resolved_scope) or (resolved_scope == "global" and s.scope == "global")
    ]
    matched_existing = next(
        (s for s in existing_in_scope if s.name == target_name or s.capability_id == capability_id),
        None,
    )

    # 4. Check for shadowing
    is_shadowing = False
    if resolved_scope == "project":
        global_match = next((s for s in existing_skills if s.scope == "global" and s.name == target_name), None)
        if global_match is not None:
            is_shadowing = True

    # 5. Handle operation: UPDATE vs CREATE
    op = getattr(intent, "operation", "create")
    if op == "update":
        if matched_existing is not None:
            return ScopeResolution(
                status="RESOLVED",
                action="UPDATE",
                target_scope=resolved_scope,
                workspace_key=eff_ws_key,
                capability_id=matched_existing.capability_id or capability_id,
                target_name=matched_existing.name,
                existing_skill=matched_existing,
                is_shadowing=is_shadowing,
                reason=f"Updating existing {resolved_scope} skill '{matched_existing.name}'.",
            )
        else:
            return ScopeResolution(
                status="RESOLVED",
                action="CREATE",
                target_scope=resolved_scope,
                workspace_key=eff_ws_key,
                capability_id=capability_id,
                target_name=target_name,
                is_shadowing=is_shadowing,
                reason=f"Skill '{target_name}' not found for update; resolving as new creation.",
            )

    # op == "create"
    if matched_existing is not None:
        return ScopeResolution(
            status="RESOLVED",
            action="UPDATE",
            target_scope=resolved_scope,
            workspace_key=eff_ws_key,
            capability_id=matched_existing.capability_id or capability_id,
            target_name=matched_existing.name,
            existing_skill=matched_existing,
            is_shadowing=is_shadowing,
            reason=f"Existing skill '{matched_existing.name}' already exists in {resolved_scope} scope; resolving as update.",
        )

    return ScopeResolution(
        status="RESOLVED",
        action="CREATE",
        target_scope=resolved_scope,
        workspace_key=eff_ws_key,
        capability_id=capability_id,
        target_name=target_name,
        existing_skill=None,
        is_shadowing=is_shadowing,
        reason=f"Creating new {resolved_scope} skill '{target_name}'.",
    )

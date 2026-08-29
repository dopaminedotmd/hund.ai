"""Typed capability self-model adapter over CommandSpec registry.

Provides single-source truth for Hund capability self-knowledge, intent matching,
and direct/state/inspection boundary definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
from typing import Any, Optional, Sequence

from ..ui.command_spec import COMMAND_REGISTRY, CommandSpec, get_command_spec


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Typed capability descriptor for Hund product self-knowledge."""

    id: str  # e.g. "skills", "history", "doctor", "system", "auth"
    display_name: str
    user_meaning: str
    user_actions: tuple[str, ...]
    relevant_commands: tuple[str, ...]
    synonyms_and_intents: tuple[str, ...]
    related_capabilities: tuple[str, ...]
    visibility_surfaces: tuple[str, ...]
    permissions_summary: str
    state_provider_reference: Optional[str] = None
    inspection_boundary: str = "direct"  # "direct" | "typed_state" | "inspection"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "user_meaning": self.user_meaning,
            "user_actions": list(self.user_actions),
            "relevant_commands": list(self.relevant_commands),
            "synonyms_and_intents": list(self.synonyms_and_intents),
            "related_capabilities": list(self.related_capabilities),
            "visibility_surfaces": list(self.visibility_surfaces),
            "permissions_summary": self.permissions_summary,
            "state_provider_reference": self.state_provider_reference,
            "inspection_boundary": self.inspection_boundary,
            "version": self.version,
        }


# Mapping of command names to semantic capability enrichments
_CAPABILITY_ENRICHMENTS: dict[str, dict[str, Any]] = {
    "skills": {
        "user_meaning": "Manage procedural skills, specialized domain behaviors, and runtime motor abilities.",
        "user_actions": ("list active skills", "inspect skill detail", "vault or equip skills", "create custom skills"),
        "synonyms_and_intents": ("skill", "skills", "färdighet", "förmåga", "mastery", "skapa skill", "author skill", "vault", "equip"),
        "related_capabilities": ("learning", "progress", "system"),
        "visibility_surfaces": ("/skills panel", "inline cards", "turn activity feed"),
        "permissions_summary": "Read-only inspection; CONFIRM required to publish or equip custom skills.",
        "state_provider_reference": "hund.skills.vault.SkillVault.get_active_skills",
        "inspection_boundary": "typed_state",
    },
    "history": {
        "user_meaning": "Search and inspect conversation turns from current and past sessions.",
        "user_actions": ("search past turns", "view turn detail", "recall context"),
        "synonyms_and_intents": ("history", "historik", "tidigare prompt", "tidigare svar", "sök historik"),
        "related_capabilities": ("session", "restore", "compress"),
        "visibility_surfaces": ("/history view", "session feed"),
        "permissions_summary": "Read-only access to local transcript records.",
        "state_provider_reference": "hund.agent.sessions.SessionManager",
        "inspection_boundary": "typed_state",
    },
    "session": {
        "user_meaning": "View active session metrics, duration, token usage, and turn counts.",
        "user_actions": ("view token usage", "check session cost", "view turn statistics"),
        "synonyms_and_intents": ("session", "sessionen", "token", "tokens", "kostnad", "cost", "turns"),
        "related_capabilities": ("history", "compress", "model"),
        "visibility_surfaces": ("/session view", "status bar"),
        "permissions_summary": "Read-only access to runtime memory metrics.",
        "state_provider_reference": "hund.agent.sessions.SessionMetrics",
        "inspection_boundary": "typed_state",
    },
    "doctor": {
        "user_meaning": "Diagnose Hund health, provider connectivity, database integrity, and local tools.",
        "user_actions": ("run health checks", "diagnose providers", "verify keyring"),
        "synonyms_and_intents": ("doctor", "hälsa", "health", "diagnose", "diagnostik", "diagnosticera", "hälsokontroll", "hälsokontroller", "felsökning", "keyring check"),
        "related_capabilities": ("system", "auth", "model"),
        "visibility_surfaces": ("/doctor panel", "terminal report"),
        "permissions_summary": "Read-only diagnostics; optional repair mode with user consent.",
        "state_provider_reference": "hund.doctor.run_doctor",
        "inspection_boundary": "inspection",
    },
    "system": {
        "user_meaning": "View host hardware specs, CPU cores, GPU VRAM, RAM, OS, and tool availability.",
        "user_actions": ("inspect CPU/GPU", "view memory stats", "refresh environment snapshot"),
        "synonyms_and_intents": ("system", "hårdvara", "specifikationer", "hardware", "cpu", "gpu", "vram", "ram", "maskin"),
        "related_capabilities": ("doctor", "stats"),
        "visibility_surfaces": ("/system view", "terminal header"),
        "permissions_summary": "Read-only environment probing.",
        "state_provider_reference": "hund.doctor.get_environment_profile",
        "inspection_boundary": "typed_state",
    },
    "model": {
        "user_meaning": "View or switch active LLM provider and reasoning model.",
        "user_actions": ("list available models", "switch model", "view model capabilities"),
        "synonyms_and_intents": ("model", "modell", "byt modell", "switch model", "välj modell", "llm"),
        "related_capabilities": ("auth", "doctor", "session"),
        "visibility_surfaces": ("/model dropdown", "status bar"),
        "permissions_summary": "Read/write session model configuration.",
        "state_provider_reference": "hund.providers.catalog.get_model_catalog",
        "inspection_boundary": "typed_state",
    },
    "auth": {
        "user_meaning": "Manage API keys and provider authentication in encrypted OS keyring.",
        "user_actions": ("set api key", "verify provider auth", "clear credentials"),
        "synonyms_and_intents": ("auth", "api key", "nyckel", "credentials", "api-nyckel", "lösenord", "keyring"),
        "related_capabilities": ("model", "doctor"),
        "visibility_surfaces": ("/auth prompt", "keyring"),
        "permissions_summary": "Secure OS Keyring access; requires interactive user input for key writes.",
        "state_provider_reference": "hund.secrets.get_keyring_status",
        "inspection_boundary": "typed_state",
    },
    "stats": {
        "user_meaning": "View base stats, character sheet, level, and XP progression.",
        "user_actions": ("view character sheet", "inspect base attributes", "view stats guide"),
        "synonyms_and_intents": ("stats", "base stats", "karaktärsblad", "character sheet", "level", "xp guide"),
        "related_capabilities": ("progress", "learning"),
        "visibility_surfaces": ("/stats view", "help summary"),
        "permissions_summary": "Read-only stats display.",
        "state_provider_reference": "hund.stats.base_stats.get_base_stats",
        "inspection_boundary": "typed_state",
    },
    "help": {
        "user_meaning": "Display commands guide, slash commands listing, and keyboard shortcuts.",
        "user_actions": ("view commands", "search help topics", "view shortcuts"),
        "synonyms_and_intents": ("help", "hjälp", "kommando", "kommandon", "commands", "kortkommandon", "shortcuts"),
        "related_capabilities": ("system", "stats"),
        "visibility_surfaces": ("/help panel", "interactive guide"),
        "permissions_summary": "Read-only.",
        "state_provider_reference": None,
        "inspection_boundary": "direct",
    },
}


def _build_descriptor_from_spec(spec: CommandSpec) -> CapabilityDescriptor:
    enrich = _CAPABILITY_ENRICHMENTS.get(spec.name, {})
    user_meaning = enrich.get("user_meaning", spec.detail_description or spec.short_description)
    user_actions = enrich.get("user_actions", (spec.short_description,))
    synonyms = list(enrich.get("synonyms_and_intents", ()))
    synonyms.extend(spec.aliases)
    synonyms.append(spec.name)
    synonyms.append(f"/{spec.name}")

    rel_cmds = [f"/{spec.name}"] + [f"/{a}" for a in spec.aliases]
    related = enrich.get("related_capabilities", ())
    vis = enrich.get("visibility_surfaces", (f"/{spec.name} command",))
    perms = enrich.get("permissions_summary", "Standard user execution.")
    provider_ref = enrich.get("state_provider_reference", None)
    boundary = enrich.get("inspection_boundary", "direct" if not provider_ref else "typed_state")

    return CapabilityDescriptor(
        id=spec.name,
        display_name=spec.name.title(),
        user_meaning=user_meaning,
        user_actions=tuple(user_actions),
        relevant_commands=tuple(rel_cmds),
        synonyms_and_intents=tuple(sorted(set(synonyms))),
        related_capabilities=tuple(related),
        visibility_surfaces=tuple(vis),
        permissions_summary=perms,
        state_provider_reference=provider_ref,
        inspection_boundary=boundary,
        version=1,
    )


def get_capability_descriptor(name_or_alias: str) -> CapabilityDescriptor | None:
    """Retrieve capability descriptor by command name, alias, or capability ID."""
    clean = name_or_alias.lstrip("/").lower().strip()
    spec = get_command_spec(clean)
    if spec:
        return _build_descriptor_from_spec(spec)
    return None


def get_all_capabilities() -> tuple[CapabilityDescriptor, ...]:
    """Return all non-hidden capability descriptors adapted from canonical CommandSpec registry."""
    return tuple(_build_descriptor_from_spec(spec) for spec in COMMAND_REGISTRY if not spec.is_hidden)


def find_matching_capabilities(query_text: str, max_results: int = 3) -> tuple[CapabilityDescriptor, ...]:
    """Find matching capability descriptors based on query intent and synonyms."""
    import re
    clean = query_text.lower().strip()
    if not clean:
        return ()

    all_caps = get_all_capabilities()
    matches: list[tuple[float, CapabilityDescriptor]] = []

    for cap in all_caps:
        score = 0.0
        # Direct slash command match
        for cmd in cap.relevant_commands:
            escaped = re.escape(cmd)
            if re.search(rf"(?:^|\s){escaped}(?:\s|$)", clean):
                score += 10.0
            elif cmd in clean:
                score += 5.0

        # Exact synonym match with word boundaries
        for syn in cap.synonyms_and_intents:
            if not syn:
                continue
            escaped_syn = re.escape(syn.lower())
            if re.search(rf"\b{escaped_syn}\b", clean):
                score += 4.0
            elif len(syn) >= 4 and syn.lower() in clean:
                score += 1.5

        if score > 0:
            matches.append((score, cap))

    matches.sort(key=lambda x: x[0], reverse=True)
    return tuple(cap for _, cap in matches[:max_results])


def render_capability_context(descriptors: Sequence[CapabilityDescriptor]) -> str:
    """Format selected capability descriptors into a compact context snippet for turn prompt."""
    if not descriptors:
        return ""
    lines: list[str] = ["## Hund Capabilities (Direct Self-Knowledge)"]
    for d in descriptors:
        lines.append(f"- **{d.display_name}** (`/{d.id}`): {d.user_meaning}")
        lines.append(f"  Actions: {', '.join(d.user_actions)}")
        lines.append(f"  Commands: {', '.join(d.relevant_commands)}")
        lines.append(f"  Boundary: {d.inspection_boundary} (Permissions: {d.permissions_summary})")
    return "\n".join(lines)

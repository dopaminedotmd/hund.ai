"""Canonical declarative CommandSpec registry for Hund commands, autocomplete, and help."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class CommandSpec:
    """Declarative specification for a Hund slash command."""

    name: str  # without leading slash, e.g. "auth"
    category: str  # e.g. "MODELS & ACCESS"
    short_description: str  # for help list and dropdown autocomplete
    detail_description: str = ""  # extended description
    usage: str = ""  # e.g. "/auth [subcommand]"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    is_planned: bool = False
    is_hidden: bool = False


# Canonical command registry — single source of truth for all slash commands
COMMAND_REGISTRY: tuple[CommandSpec, ...] = (
    # SESSION & CONTEXT
    CommandSpec(
        name="history",
        category="SESSION & CONTEXT",
        short_description="browse or search previous turns",
        detail_description="Browse session turn history and inspect past prompts and responses.",
        usage="/history [search <q> | <id>]",
    ),
    CommandSpec(
        name="session",
        category="SESSION & CONTEXT",
        short_description="view current session details",
        detail_description="Display active session duration, tokens, cost, and turn counts.",
        usage="/session",
    ),
    CommandSpec(
        name="compress",
        category="SESSION & CONTEXT",
        short_description="condense active context safely",
        detail_description="Summarize previous conversation history to free context window headroom.",
        usage="/compress",
        aliases=("compact",),
    ),
    CommandSpec(
        name="clear",
        category="SESSION & CONTEXT",
        short_description="clear output screen",
        detail_description="Clear output terminal feed while keeping active session state in memory.",
        usage="/clear",
        aliases=("cls",),
    ),
    CommandSpec(
        name="exit",
        category="SESSION & CONTEXT",
        short_description="exit session cleanly",
        detail_description="Gracefully shut down active session, save learning jobs, and restore terminal.",
        usage="/exit",
        aliases=("quit", "q"),
    ),
    CommandSpec(
        name="export",
        category="SESSION & CONTEXT",
        short_description="export session transcript to markdown",
        detail_description="Export active session transcript to markdown file.",
        usage="/export [file]",
    ),
    CommandSpec(
        name="restore",
        category="SESSION & CONTEXT",
        short_description="restore previous or specified session",
        detail_description="Restore messages from previous session into active context.",
        usage="/restore [id]",
    ),
    CommandSpec(
        name="retry",
        category="SESSION & CONTEXT",
        short_description="regenerate last assistant response",
        detail_description="Regenerate last assistant response.",
        usage="/retry",
    ),
    # SYSTEM & HEALTH
    CommandSpec(
        name="system",
        category="SYSTEM & HEALTH",
        short_description="view the known machine and environment",
        detail_description="Inspect host CPU, GPU, RAM, VRAM, disk storage, and available runtimes.",
        usage="/system [refresh|changes]",
        aliases=("sys", "env"),
    ),
    CommandSpec(
        name="doctor",
        category="SYSTEM & HEALTH",
        short_description="diagnose Hund, providers and local services",
        detail_description="Run read-only health checks on config, keyring, models, learning database, and terminal font.",
        usage="/doctor [--fix|providers|learning|ui]",
        aliases=("diag", "health"),
    ),
    CommandSpec(
        name="profile",
        category="SYSTEM & HEALTH",
        short_description="system info (migrated to /system)",
        detail_description="View migration notice for /system. (Named context profiles are planned).",
        usage="/profile",
    ),
    CommandSpec(
        name="usage",
        category="SYSTEM & HEALTH",
        short_description="view token and resource use",
        detail_description="Display token usage breakdown, model latency, and cost telemetry.",
        usage="/usage",
        aliases=("cost",),
    ),
    CommandSpec(
        name="stats",
        category="SYSTEM & HEALTH",
        short_description="RPG character sheet, base stats & trend",
        detail_description="Display Hund base stats (Clarity, Precision, Efficiency, Endurance, Mastery) and domain XP.",
        usage="/stats [velocity|compact]",
        aliases=("sheet", "character"),
    ),
    CommandSpec(
        name="config",
        category="SYSTEM & HEALTH",
        short_description="view/update settings",
        detail_description="View or update active configuration settings.",
        usage="/config [set <k> <v>]",
    ),
    # MODELS & ACCESS
    CommandSpec(
        name="model",
        category="MODELS & ACCESS",
        short_description="select the active model",
        detail_description="Open the model selection modal to switch between configured provider models.",
        usage="/model [name]",
    ),
    CommandSpec(
        name="auth",
        category="MODELS & ACCESS",
        short_description="manage providers and credentials",
        detail_description="Configure provider API keys, manage custom endpoints, and inspect keyring credentials.",
        usage="/auth",
    ),
    # CAPABILITIES
    CommandSpec(
        name="skills",
        category="CAPABILITIES",
        short_description="view and manage runtime skills and proposals",
        detail_description="Open the SkillVault to inspect, equip, park, or test personal skills.",
        usage="/skills [vault|core|equip|swap]",
    ),
    CommandSpec(
        name="tools",
        category="CAPABILITIES",
        short_description="inspect registered tools and risk levels",
        detail_description="List available tools, permissions, parameter schemas, and execution policies.",
        usage="/tools",
    ),
    CommandSpec(
        name="learning",
        category="CAPABILITIES",
        short_description="inspect durable learning receipts",
        detail_description="Inspect durable learning receipts, verified evidence, and domain progression.",
        usage="/learning [receipt-id]",
    ),
    CommandSpec(
        name="lessons",
        category="CAPABILITIES",
        short_description="view learned lessons & feedback",
        detail_description="View accumulated lessons learned from errors & corrections.",
        usage="/lessons",
        aliases=("feedback",),
    ),
    CommandSpec(
        name="trace",
        category="CAPABILITIES",
        short_description="inspect the last run's redacted tool trace",
        detail_description="Show a compact redacted trace for the latest run in this session.",
        usage="/trace last",
    ),
    CommandSpec(
        name="domains",
        category="CAPABILITIES",
        short_description="domains + confidence",
        detail_description="View domain confidence and specializations.",
        usage="/domains",
    ),
    CommandSpec(
        name="progress",
        category="CAPABILITIES",
        short_description="domain progress bars",
        detail_description="View domain progression and confidence tiers.",
        usage="/progress",
    ),
    CommandSpec(
        name="memory",
        category="CAPABILITIES",
        short_description="persistent memory (user.md + environment.md)",
        detail_description="View, add, or inspect persistent user memories and preferences.",
        usage="/memory [add <text>]",
    ),
    # GENERAL
    CommandSpec(
        name="diff",
        category="GENERAL",
        short_description="view working tree modifications",
        detail_description="View uncommitted git modifications.",
        usage="/diff",
    ),
    CommandSpec(
        name="undo",
        category="GENERAL",
        short_description="file backup & restore information",
        detail_description="View file backup and restore instructions.",
        usage="/undo",
    ),
    CommandSpec(
        name="notifications",
        category="GENERAL",
        short_description="toggle desktop notifications",
        detail_description="Toggle desktop notifications on or off.",
        usage="/notifications [on|off]",
    ),
    CommandSpec(
        name="mascot",
        category="GENERAL",
        short_description="display pixel hound",
        detail_description="Display Hund ASCII mascot.",
        usage="/mascot",
    ),
    CommandSpec(
        name="theme",
        category="GENERAL",
        short_description="switch visual theme",
        detail_description="Switch terminal visual palette (Marshmallow signature theme).",
        usage="/theme [name]",
    ),
    CommandSpec(
        name="reset",
        category="GENERAL",
        short_description="reset progression and local data",
        detail_description="Reset local learning database, domain confidence, and session history.",
        usage="/reset",
    ),
    CommandSpec(
        name="help",
        category="GENERAL",
        short_description="display base stats and commands guide",
        detail_description="Display base stats explanation and all slash commands.",
        usage="/help",
        aliases=("?",),
    ),
)


def get_command_spec(name: str) -> CommandSpec | None:
    """Find a CommandSpec by primary name or alias (case-insensitive, with/without slash)."""
    clean_name = name.lstrip("/").lower().strip()
    for spec in COMMAND_REGISTRY:
        if spec.name == clean_name or clean_name in spec.aliases:
            return spec
    return None


def get_categorized_commands() -> dict[str, list[CommandSpec]]:
    """Return non-hidden commands grouped by category preserving canonical order."""
    grouped: dict[str, list[CommandSpec]] = {}
    for spec in COMMAND_REGISTRY:
        if spec.is_hidden:
            continue
        grouped.setdefault(spec.category, []).append(spec)
    return grouped


def get_autocomplete_metas() -> dict[str, str]:
    """Return dictionary of {f'/{name}': short_description} for autocomplete dropdown."""
    metas: dict[str, str] = {}
    for spec in COMMAND_REGISTRY:
        if spec.is_hidden or spec.is_planned:
            continue
        metas[f"/{spec.name}"] = spec.short_description
    return metas


def get_all_command_names() -> list[str]:
    """Return all primary names and aliases of available commands."""
    names: list[str] = []
    for spec in COMMAND_REGISTRY:
        if spec.is_hidden:
            continue
        names.append(spec.name)
        names.extend(spec.aliases)
    return names


def suggest_similar_command(unknown_name: str) -> str | None:
    """Suggest closest command name for a misspelled slash command."""
    clean = unknown_name.lstrip("/").lower().strip()
    if not clean:
        return None
    valid_names = [spec.name for spec in COMMAND_REGISTRY if not spec.is_hidden]
    matches = difflib.get_close_matches(clean, valid_names, n=1, cutoff=0.5)
    return matches[0] if matches else None


def find_command_by_topic(text: str) -> CommandSpec | None:
    """Find a relevant CommandSpec based on user question text or slash command reference."""
    clean = text.lower().strip()
    if not clean:
        return None

    # Check explicit slash command in text
    for spec in COMMAND_REGISTRY:
        if spec.is_hidden or spec.is_planned:
            continue
        if f"/{spec.name}" in clean:
            return spec
        for alias in spec.aliases:
            if f"/{alias}" in clean:
                return spec

    # Natural topic keywords
    if any(k in clean for k in ("skill", "skills", "färdighet", "färdigheter")):
        return get_command_spec("skills")
    if any(k in clean for k in ("history", "historik", "tidigare prompt", "tidigare svar")):
        return get_command_spec("history")
    if any(k in clean for k in ("session", "sessionen", "token", "tokens", "kostnad", "cost")):
        return get_command_spec("session")
    if any(k in clean for k in ("doctor", "hälsa", "health")):
        return get_command_spec("doctor")
    if any(k in clean for k in ("byt modell", "switch model", "välj modell", "select model")):
        return get_command_spec("model")
    if any(k in clean for k in ("api key", "nyckel", "credentials", "api-nyckel")):
        return get_command_spec("auth")
    if any(k in clean for k in ("help", "hjälp", "kommando", "kommandon", "commands")):
        return get_command_spec("help")
    if any(k in clean for k in ("rensa", "clear", "cls", "skärmen")):
        return get_command_spec("clear")
    if any(k in clean for k in ("base stats", "karaktärsblad", "character sheet")):
        return get_command_spec("stats")
    if any(k in clean for k in ("learning", "lärande", "receipts")):
        return get_command_spec("learning")
    if any(k in clean for k in ("progress", "framsteg")):
        return get_command_spec("progress")
    return None

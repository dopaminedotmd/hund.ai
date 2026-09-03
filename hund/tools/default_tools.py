"""Default tools + schemas. Registreras med workspace-known handlers."""
from __future__ import annotations

from pathlib import Path

from . import registry
from .file_tool import make_handlers as file_handlers
from .terminal_tool import make_handler as terminal_handler

_PATH_PARAM = {
    "type": "string",
    "description": (
        "Sökväg relativt workspace. För absoluta sökvägar utanför workspace: "
        "use the terminal with the user-provided absolute path or request workspace switch."
    ),
}


def register_defaults(workspace: Path) -> None:
    """Registrera alla tools med workspace-confined handlers."""
    handlers = {**file_handlers(workspace), **terminal_handler(workspace)}

    specs = [
        registry.Tool(
            name="read_file",
            description=(
                "Läs en fils innehåll (inom workspace). För absoluta sökvägar utanför workspace: "
                "use the terminal with the user-provided absolute path or request workspace switch."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _PATH_PARAM,
                    "offset": {"type": "integer", "description": "1-based starting line number (optional, default 1)"},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read (optional, default 500)"},
                },
                "required": ["path"],
            },
            base_risk="safe",
            handler=handlers["read_file"],
        ),
        registry.Tool(
            name="search_files",
            description=(
                "Sök filer med glob-mönster i workspace. För absoluta sökvägar utanför workspace: "
                "use the terminal with the user-provided absolute path or request workspace switch."
            ),
            parameters={
                "type": "object",
                "properties": {"path": _PATH_PARAM, "pattern": {"type": "string"}},
                "required": ["pattern"],
            },
            base_risk="safe",
            handler=handlers["search_files"],
        ),
        registry.Tool(
            name="write_file",
            description=(
                "Skriv/overskriv en fil i workspace. För absoluta sökvägar utanför workspace: "
                "use the terminal with the user-provided absolute path or request workspace switch."
            ),
            parameters={
                "type": "object",
                "properties": {"path": _PATH_PARAM, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            base_risk="write",
            handler=handlers["write_file"],
        ),
        registry.Tool(
            name="delete_file",
            description="Radera en fil i workspace.",
            parameters={"type": "object", "properties": {"path": _PATH_PARAM}, "required": ["path"]},
            base_risk="dangerous",
            handler=handlers["delete_file"],
        ),
        registry.Tool(
            name="terminal",
            description="Run a terminal command. cwd (optional): working directory relative to workspace root - use this instead of cd. Prefer python or find over cmd for /r; cmd doubles % in batch contexts.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run."},
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory relative to workspace root. Use this instead of cd.",
                    },
                    "timeout": {"type": "integer", "default": 60, "description": "Command timeout in seconds."},
                },
                "required": ["command"],
            },
            base_risk="confirm",
            handler=handlers["terminal"],
        ),
    ]
    for t in specs:
        registry.register(t)

    from .skill_tool import make_handler as skill_handler

    registry.register(registry.Tool(
        name="create_skill",
        description=(
            "Persist a validated Hund skill draft from the active authoring runtime. "
            "Requires an active authoring session with consumed exact-draft authorization."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "authorization_id": {"type": "string"},
                "payload_hash": {"type": "string"},
                "desired_disposition": {
                    "type": "string",
                    "enum": ["equip", "vault"],
                },
                "skill": {
                    "type": "object",
                    "description": "Complete schema_version 1 skill payload.",
                },
            },
            "required": ["session_id", "authorization_id", "payload_hash", "skill"],
        },
        base_risk="confirm",
        handler=skill_handler(workspace_path=workspace),
    ))

    from .web_search import search_web_typed
    from .web_extract import extract_web
    from .web_open import open_web

    registry.register(registry.Tool(
        name="web_search",
        description=(
            "Sok pa webben. Anvand for: aktuell info, okanda produkter/versioner, "
            "nyheter, verifierbara fakta. Anvand INTE for: statisk kunskap "
            "(for loops, Pythagoras), personliga fragor. Skala antal sok: "
            "1 for enkla fakta, 5-10 for research."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Sokfras (1-6 ord for basta resultat)"}},
            "required": ["query"],
        },
        base_risk="safe",
        handler=search_web_typed,
        context_mode="required",
    ))
    registry.register(registry.Tool(
        name="web_open",
        description=(
            "Öppna en URL som användaren eller web_search har tillhandahållit. "
            "Ger en säker semantisk vy med read, next, find och follow."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "page_id": {"type": "string"},
                "read": {"type": "integer"},
                "next": {"type": "boolean"},
                "find": {"type": "string"},
                "follow": {"type": "integer"},
                "full": {"type": "boolean"},
            },
        },
        base_risk="safe",
        handler=open_web,
        context_mode="required",
    ))
    registry.register(registry.Tool(
        name="web_extract",
        description=(
            "Bakåtkompatibelt alias för web_open. URL:en måste finnas i "
            "sessionens säkra provenienslista."
        ),
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL att hamta (https://...)"}},
            "required": ["url"],
        },
        base_risk="safe",
        handler=extract_web,
        context_mode="required",
    ))

    from .execute_code import run_code, BLOCKED_TOOLS

    registry.register(registry.Tool(
        name="execute_code",
        description=(
            "Kor ett Python-script som anropar Hunds tools programmatiskt. "
            "Scriptet har tillgang till call_tool(tool, args) for att anropa "
            "read_file, search_files, write_file, terminal och delete_file. "
            "Nätverksverktyg kräver sessionskontext och körs inte här. "
            "Anvand for komplexa pipelines dar "
            "flera tool-anrop behovs. Max 50 tool calls, 300s timeout. "
            f"Blockerade tools: {', '.join(sorted(BLOCKED_TOOLS))}."
        ),
        parameters={
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python-kod att exekvera"}},
            "required": ["code"],
        },
        base_risk="confirm",
        handler=run_code,
    ))

    from .delegate_task import run_delegation

    registry.register(registry.Tool(
        name="delegate_task",
        description=(
            "Spawna upp till 3 parallella subagents for oberoende deluppgifter. "
            "Varje subagent har begransade verktyg (endast SAFE, ingen TCB-access) "
            "och kor i isolerad session. Returnerar sammanfattningar. "
            "Anvand for: parallella sokningar, oberoende filanalyser, "
            "flera research-uppgifter samtidigt."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "Lista av tasks. Varje task har 'goal' (obligatorisk) och 'context' (valfri).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "Uppgift for subagenten"},
                            "context": {"type": "string", "description": "Bakgrundsinformation"},
                        },
                        "required": ["goal"],
                    },
                },
            },
            "required": ["tasks"],
        },
        base_risk="confirm",
        handler=run_delegation,
    ))

    from .session_search import search_sessions

    registry.register(registry.Tool(
        name="session_search",
        description=(
            "Sok i Hunds tidigare sessionshistorik. Anvand for att hitta "
            "vad som diskuterades tidigare, ateruppta tradar, eller hamta "
            "kontext fran aldre konversationer. Tva lagen: "
            "'search' (FTS5-fulltext, krav 'query'), "
            "'list' (senaste sessionerna). "
            "Sok INNAN du fragar anvandaren om nagot de redan berattat."
        ),
        parameters={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["search", "list"],
                    "description": "'search' = fulltext-sok (krav query), 'list' = senaste sessioner",
                },
                "query": {"type": "string", "description": "Sokfras (content nouns, t.ex. 'byggplan' inte 'vad diskuterade vi')"},
                "limit": {"type": "integer", "description": "Max resultat (default 5, max 20)"},
            },
            "required": ["mode"],
        },
        base_risk="safe",
        handler=search_sessions,
    ))

    from .cronjob import manage_cron

    registry.register(registry.Tool(
        name="cronjob",
        description=(
            "Hantera schemalagda tasks. Skapa, lista, pausa, ateruppta, ta bort. "
            "Schedule-format: '30m' (var 30e minut), 'every 2h' (varannan timme), "
            "eller cron-uttryck. Anvand for: dagliga rapporter, watchdog, "
            "aterkommande kontroller. CRON KAN ALDRIG SELF-IMPROVE."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list","create","pause","resume","remove"]},
                "name": {"type": "string"},
                "schedule": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["action"],
        },
        base_risk="confirm",
        handler=manage_cron,
    ))

    from ..desktop import make_desktop_handler

    registry.register(registry.Tool(
        name="create_desktop_shortcut",
        description=(
            "Create the Hund desktop shortcut (hund.lnk) that opens the Hund "
            "Windows Terminal profile. Idempotent and safe to re-run."
        ),
        parameters={"type": "object", "properties": {}},
        base_risk="confirm",
        handler=make_desktop_handler(),
    ))

    ui_metadata = {
        "read_file": ("Filesystem", "PermissionEngine classified"),
        "search_files": ("Filesystem", "PermissionEngine classified"),
        "write_file": ("Filesystem", "PermissionEngine classified"),
        "delete_file": ("Filesystem", "PermissionEngine classified"),
        "terminal": ("Execution", "PermissionEngine classified"),
        "create_skill": ("Skills", "Schema and lifecycle gated"),
        "web_search": ("Network", "Read-only search"),
        "web_open": ("Network", "Provenance and SSRF gated"),
        "web_extract": ("Network", "Provenance and SSRF gated"),
        "execute_code": ("Execution", "PermissionEngine classified"),
        "delegate_task": ("Agents", "Restricted child runtime"),
        "session_search": ("Memory", "Local read-only search"),
        "cronjob": ("Scheduling", "Confirmation gated"),
        "create_desktop_shortcut": ("System", "Confirmation gated"),
    }
    for tool in registry.all_tools():
        metadata = ui_metadata.get(tool.name)
        if metadata is not None:
            tool.category, tool.dispatch_description = metadata

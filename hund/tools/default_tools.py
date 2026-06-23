"""Default tools + schemas. Registreras med workspace-known handlers."""
from __future__ import annotations

from pathlib import Path

from . import registry
from .file_tool import make_handlers as file_handlers
from .terminal_tool import make_handler as terminal_handler

_PATH_PARAM = {"type": "string", "description": "Sökväg relativt workspace."}


def register_defaults(workspace: Path) -> None:
    """Registrera alla tools med workspace-confined handlers."""
    handlers = {**file_handlers(workspace), **terminal_handler(workspace)}

    specs = [
        registry.Tool(
            name="read_file",
            description="Läs en fils innehåll (inom workspace).",
            parameters={"type": "object", "properties": {"path": _PATH_PARAM}, "required": ["path"]},
            base_risk="safe",
            handler=handlers["read_file"],
        ),
        registry.Tool(
            name="search_files",
            description="Sök filer med glob-mönster i workspace.",
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
            description="Skriv/overskriv en fil i workspace.",
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
            description="Kör ett terminalkommando (cwd = workspace).",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "default": 60},
                },
                "required": ["command"],
            },
            base_risk="confirm",
            handler=handlers["terminal"],
        ),
    ]
    for t in specs:
        registry.register(t)

    from .web_search import search_web
    from .web_extract import extract_web

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
        handler=search_web,
    ))
    registry.register(registry.Tool(
        name="web_extract",
        description=(
            "Hamta och extrahera text fran en URL. Returnerar sidans textinnehall "
            "(HTML-taggar bortrensade). Max 50KB output. Endast http/https URLs."
        ),
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL att hamta (https://...)"}},
            "required": ["url"],
        },
        base_risk="safe",
        handler=extract_web,
    ))

    from .execute_code import run_code, BLOCKED_TOOLS

    registry.register(registry.Tool(
        name="execute_code",
        description=(
            "Kor ett Python-script som anropar Hunds tools programmatiskt. "
            "Scriptet har tillgang till call_tool(tool, args) for att anropa "
            "read_file, search_files, write_file, terminal, web_search, "
            "web_extract, delete_file. Anvand for komplexa pipelines dar "
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




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


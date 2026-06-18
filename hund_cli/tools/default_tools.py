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

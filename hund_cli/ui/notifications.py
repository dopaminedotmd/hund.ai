"""Markup-strängar för tillfälliga UI-notiser."""
from __future__ import annotations


def thinking(msg: str) -> str:
    return f"[dim]{msg}[/dim]"


def tool_line(tool: str, target: str) -> str:
    actions = {
        "read_file": "läser",
        "search_files": "söker",
        "list_files": "listar",
        "write_file": "skriver",
        "run_terminal": "kör",
    }
    action = actions.get(tool, tool.replace("_", " "))
    suffix = f" {target}" if target else ""
    return f"[dim]● {action}{suffix}[/dim]"


def write_confirm(path: str) -> str:
    _ = path
    return "[yellow]WRITE[/yellow] [dim]tillåt? [j/N][/dim]"


def level_up(stat: str, old: str, new: str) -> str:
    return (
        f"[bold gold1]₊⊹˖⭑ {stat}: {old} → {new}! "
        "⭑˖⊹₊[/bold gold1]"
    )

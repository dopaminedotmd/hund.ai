"""Markup-strängar för tillfälliga UI-notiser."""
from __future__ import annotations


def pick_thinking_text(user_input: str) -> str:
    """Välj kontextuell tänketext baserat på användarens prompt.

    Returnerar en phrase (utan prickar) som ThinkingAnimator cyklar prickar på.
    Matchas i ordning — första träffen vinner, annars default.
    """
    text = (user_input or "").lower()
    if any(w in text for w in ("vad", "hur", "varför", "när", "vilken", "?")):
        return "hund undersöker"
    if any(w in text for w in ("läs", "kolla", "visa", "titta")):
        return "hund läser"
    if any(w in text for w in ("hitta", "sök", "leta", "finns")):
        return "hund söker"
    if any(w in text for w in ("ändra", "skriv", "fixa", "uppdatera")):
        return "hund förbereder"
    if any(w in text for w in ("kör", "bygg", "testa", "starta")):
        return "hund kör"
    return "hund tänker"


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

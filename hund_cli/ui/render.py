"""Render helpers för Hunds terminal-UI.

De nya frame-first helpers är rena funktioner så splash, prompt och turn-markörer
kan testas utan att starta agentloopen. Färgvalen håller sig till varm offwhite
och subtila ramar/accenter för att undvika dashboardbrus.
"""

from rich.errors import MarkupError
from rich.text import Text

from .. import __version__

_COMMANDS = "/sessions · /exit · /stats · /profile · /tools"
_STAT_LABELS = {
    "token_efficiency": "TEF",
    "speed": "SPD",
    "tool_judgment": "JDG",
}
_CREAM = "#E8E0D5"  # varm offwhite — ersätter allt grönt
_BORDER = "#a09080"
_DIM = "dim"


def _fit(value: str, width: int) -> str:
    """Trimma text defensivt så Rich inte radbryter startup-canvasen."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: max(0, width - 1)] + "…"


def _plain_line(value: str, width: int, *, align: str = "left") -> str:
    fitted = _fit(value, width)
    if align == "right":
        return fitted.rjust(width)
    if align == "center":
        return fitted.center(width)
    return fitted.ljust(width)


def render_startup(
    width: int,
    height: int,
    workspace: str,
    version: str = __version__,
    model: str | None = None,
) -> Text:
    """Returnera Hunds fullhöjds-startup med tydlig, premium visuell reset.

    Splashen byggs som en hel canvas (nästan hela terminalhöjden) i stället för
    ett litet block, med varm ramton, negativ yta och metadata nära övre tredjedel.
    """
    width = max(40, int(width or 80))
    height = max(12, int(height or 24))
    workspace = workspace or "workspace"

    canvas_lines = max(1, height - 1)  # console.print lägger till sista radmatningen.
    intro_indent = min(max(4, width // 7), 16)
    content_width = max(18, width - intro_indent - 4)
    rule_width = min(max(24, width // 2), max(24, width - intro_indent - 2))
    top_breathing = max(3, min(8, height // 4))

    model_line = f"model      {model}" if model else "model      default provider"
    intro = [
        "─" * rule_width,
        f"◇ Hund CLI v{version}",
        "  local-first agentmotor",
        f"  workspace  {workspace}",
        f"  {model_line}",
        "  /sessions · /exit · /stats · /profile · /tools",
        "·" * max(12, rule_width // 2),
    ]
    help_row = "/sessions · /exit"

    rows: list[tuple[str, str]] = []
    for index in range(canvas_lines):
        if index < top_breathing:
            rows.append(("", _DIM))
            continue

        intro_index = index - top_breathing
        if intro_index < len(intro):
            value = " " * intro_indent + _fit(intro[intro_index], content_width)
            style = _BORDER if intro_index in {0, 6} else (_CREAM if intro_index == 1 else _DIM)
            rows.append((_plain_line(value, width), style))
            continue

        if index == canvas_lines - 2:
            rows.append((_plain_line(help_row, width, align="right"), _DIM))
        else:
            rows.append(("", _DIM))

    rendered = Text()
    for index, (line, style) in enumerate(rows):
        if line:
            rendered.append(line, style=style)
        if index != len(rows) - 1:
            rendered.append("\n")
    return rendered


def render_user_prompt() -> Text:
    """Promptindikator utan textetikett, tydligare än en enkel chevron."""
    return Text("◇ ", style=_CREAM)


def render_assistant_turn(text: str) -> Text:
    """Formattera Hunds svar med tydlig turn-hierarki.

    Första raden får Hund-markören, fortsättningsrader indenteras.
    Avslutas med en ren avskiljarlinje och luftig spacing.
    """
    body = (text or "").strip("\n")
    if not body.strip():
        return Text("")
    lines = body.splitlines()

    rendered = Text("\n")
    rendered.append("◆ ", style=_BORDER)
    rendered.append(lines[0], style=_CREAM)
    for line in lines[1:]:
        rendered.append("\n   ", style=_DIM)
        rendered.append(line, style=_CREAM)
    
    # Elegant divider line with nice spacing
    rendered.append("\n\n")
    rendered.append("─" * 40, style=_BORDER)
    rendered.append("\n")
    return rendered


def plain_error_message(message: str, *, prefix: str = "fel") -> str:
    """Returnera feltext utan Rich-markup för markup-säkra svarsbubblor."""
    raw = str(message or "")
    try:
        plain = Text.from_markup(raw).plain
    except MarkupError:
        plain = raw
    plain = plain.strip()
    if not plain:
        plain = "okänt fel"
    if plain.lower().startswith(f"{prefix.lower()}:"):
        return plain
    return f"{prefix}: {plain}"


def blocked_tool_message(name: str, reason: str = "") -> str:
    """Kort, markup-fri text för blockerade tool-anrop."""
    label = str(name or "okänt tool").strip() or "okänt tool"
    detail = str(reason or "").strip()
    return f"blocked: {label}" + (f" — {detail}" if detail else "")


def format_session_rows(rows: list[tuple]) -> str:
    """Formattera `/sessions`-listan utan Rich-markup."""
    if not rows:
        return "(inga sessioner)"
    lines: list[str] = []
    for sid, created, title, count, active in rows:
        mark = "*" if active else " "
        lines.append(f"{mark} #{str(sid)[:8]} ({count}) {str(title)[:40]} — {created}")
    return "\n".join(lines)


def format_session_search_rows(query: str, rows: list[tuple]) -> str:
    """Formattera `/sessions search`-träffar utan Rich-markup."""
    if not rows:
        return f"(inga träffar för '{query}')"
    return "\n".join(
        f"#{str(session_id)[:8]} [{role}] {snippet} — {created}"
        for session_id, role, snippet, created in rows
    )


def _mini_bar(pct: int, width: int = 8) -> str:
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def _status_mascot(_mascot: Text) -> Text:
    return Text("hund ", style=f"bold {_CREAM}")


def render_status(
    mascot: Text,
    session_id: str,
    msg_count: int,
    domain: str,
    locked: bool,
) -> Text:
    status = Text()
    status.append_text(_status_mascot(mascot))
    status.append(f"Hund {__version__}", style=f"bold {_CREAM}")
    status.append(" · ", style=_DIM)

    dom = domain or "general"
    if locked:
        status.append("[LAST] ", style="bold yellow")
        status.append(dom, style="bold yellow")
    else:
        status.append(dom, style="dim")

    status.append(" · ", style=_DIM)
    status.append(f"session #{session_id[:8]}", style=_CREAM)
    status.append(" · ", style=_DIM)
    status.append(f"{msg_count} msg", style=_CREAM)

    return status


def render_status_plain(
    session_id: str,
    msg_count: int,
    domain: str,
    version: str = __version__,
) -> str:
    """Ren textsträng för prompt_toolkits bottom_toolbar (Rich-Text ej tillåten där).

    Speglar vänsterdelen av render_status: version · domän · session · meddelandecount.
    """
    dom = domain or "general"
    sid = str(session_id or "")[:8]
    return (
        f"Hund {version} · {dom} · session #{sid} · {msg_count} msg"
        f"   {_COMMANDS}"
    )


def render_baserad(stats: dict) -> Text:
    result = Text()
    parts: list[Text] = []
    for key in ("token_efficiency", "speed", "tool_judgment"):
        data = stats.get(key, {})
        part = Text()
        part.append(f"{_STAT_LABELS[key]} ", style=_DIM)
        part.append(str(data.get("level", "n/a")))
        pct = data.get("success_rate_pct")
        if isinstance(pct, (int, float)):
            rounded = round(pct)
            part.append(f" {rounded}% ")
            part.append(_mini_bar(rounded), style=_CREAM)
        parts.append(part)

    for index, part in enumerate(parts):
        if index:
            result.append(" | ", style=_DIM)
        result.append_text(part)
    result.append("\n")
    result.append(_COMMANDS, style=_DIM)
    return result

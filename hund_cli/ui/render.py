"""Kompakta Rich-renderare för terminal-UI:ns fasta zoner."""

from rich.text import Text

from .. import __version__

_COMMANDS = "/exit · /stats · /profile · /tools"
_STAT_LABELS = {
    "token_efficiency": "TEF",
    "speed": "SPD",
    "tool_judgment": "JDG",
}
_CREAM = "#E8E0D5"  # varm offwhite — ersätter allt grönt
_DIM = "dim"


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
    status.append(f"{'[LAST] ' if locked else ''}{dom}")
    status.append(" · ", style=_DIM)
    status.append(f"session #{session_id[:8]}")
    status.append(" · ", style=_DIM)
    status.append(f"{msg_count} msg")
    return status


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

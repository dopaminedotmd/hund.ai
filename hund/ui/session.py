"""UI-session-helpers: resume-erbjudande + export.

ATERSKAPAR inget - tunna wrappers ovanpa hund.agent.sessions (som har SQLite +
FTS5). hund.agent.sessions agnar canonen; denna modul hanterar bara UI-formatering.
"""
from __future__ import annotations

from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console

from ..agent import sessions as S
from ..providers.base import Message

_RESUME_YES = {"", "j", "ja", "y", "yes"}


async def offer_resume(
    console: Console,
    prompt_session,
    rt,
    prev_active: dict | None,
) -> str:
    """Erbjud resume av fOrra aktiva sessionen. Returnera session_id att anvanda.

    prev_active = S.get_active() FÖRE _init_runtime (som skapar ny + deaktiverar).
    rt = fOrsk runtime; rt.session_id = ny tom session.
    """
    new_id = rt.session_id
    if not prev_active or not prev_active.get("message_count"):
        return new_id

    prev_id = prev_active["id"]
    count = prev_active["message_count"]
    prompt = FormattedText([
        ("bold", f"Resume session #{prev_id[:8]} ({count} msgs)? [Y/n] "),
    ])
    try:
        ans = (await prompt_session.prompt_async(prompt)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"

    if ans not in _RESUME_YES:
        return new_id

    S.set_active(prev_id)
    # behall systemprompten (messages[0]), ersatt resten med historik
    del rt.messages[1:]
    for role, content in S.history(prev_id):
        rt.messages.append(Message(role=role, content=content))
    console.print(f"[dim]resumed {count} messages.[/dim]")
    return prev_id


def export_session(session_id: str, output_path: str | None = None) -> str:
    """Exportera session till .md. Returnera skriven sOokvag."""
    msgs = S.list_messages(session_id)
    md = f"# Session {session_id[:8]}\n\n"
    for role, content in msgs:
        if role == "system":
            continue
        who = {"user": "du", "assistant": "hund"}.get(role, role)
        md += f"## {who}\n\n{content}\n\n"
    if not output_path:
        output_path = f"hund-session-{session_id[:8]}.md"
    Path(output_path).write_text(md, encoding="utf-8")
    return output_path

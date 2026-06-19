"""Hunds terminal-UI — helt strippad, clean, minimal.

Inga paneler. Inga borders. Inget "hund undersoker".
En rad status. Konversation. En rad stats. Input.
"""

from rich.console import Console
from rich.text import Text

from .. import __version__
from ..base_stats import compute
from ..providers.base import Message
from ..tools import registry
from .render import render_baserad

console = Console()
CREAM = "#E8E0D5"


def _status_line(session_id: str, msg_count: int, domain: str) -> str:
    dom = domain or "general"
    sid = session_id[:8]
    return f"hund {__version__}  {dom}  #{sid}  {msg_count} msg"


def _stats_line() -> str:
    stats = compute()
    parts = []
    for key in ("token_efficiency", "speed", "tool_judgment"):
        data = stats.get(key, {})
        level = data.get("level", "n/a")
        pct = data.get("success_rate_pct")
        label = {"token_efficiency": "tef", "speed": "spd", "tool_judgment": "jdg"}[key]
        part = f"{label} {level}"
        if isinstance(pct, (int, float)):
            part += f" {round(pct)}%"
        parts.append(part)
    return "  |  ".join(parts)


def run_repl_ui() -> int:
    from ..agent import sessions as S
    from ..agent.context import maybe_compress
    from ..agent.loop import (
        _agent_turn,
        _init_runtime,
        _session_save,
        _stats_text,
        assemble_system_prompt,
    )

    rt = _init_runtime()
    if not rt.key:
        console.print(f"[red]API-nyckel saknas.[/red]")
        return 1

    # Header — en gång
    console.print(f"[{CREAM}]{_status_line(rt.session_id, 0, rt.domain_hint)}[/{CREAM}]")
    console.print(f"[dim]{_stats_line()}[/dim]")
    console.print()

    class Sink:
        def thinking(self, msg=""):
            pass  # tyst — inget "hund undersoker"

        def clear_thinking(self):
            pass

        def chunk(self, text):
            console.print(text, end="", markup=False, highlight=False)

        def end_assistant(self):
            console.print()

        def error(self, msg):
            console.print(f"[red]{msg}[/red]")

        def tool_start(self, name, args):
            pass  # tyst

        def tool_result(self, name, shown):
            pass

        def blocked(self, name, reason):
            console.print(f"[red]blocked: {name}[/red]")

        def declined(self, name, reason):
            console.print(f"[dim]nekad: {name}[/dim]")

        def confirm(self, prompt):
            return console.input(f"[{CREAM}]{prompt} [j/N][/{CREAM}] ").strip().lower() in {"j", "ja", "y", "yes"}

        on_chunk = chunk
        on_thinking = thinking
        on_error = error

        def on_tool(self, name, args):
            pass

    sink = Sink()

    while True:
        try:
            user = console.input(f"[{CREAM}]du>[/{CREAM}] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user in {"/exit", "/quit"}:
            break
        if user == "/stats":
            console.print(_stats_text())
            continue
        if user == "/profile":
            console.print(rt.profile.summary())
            continue
        if user == "/tools":
            console.print(", ".join(f"{t.name}" for t in registry.all_tools()))
            continue

        rt.messages.append(Message(role="user", content=user))
        _session_save(rt.session_id, "user", user)
        rt.messages[0] = Message(
            role="system",
            content=assemble_system_prompt(
                rt.persona, rt.profile,
                knowledge=rt.knowledge, policy_rules=rt.policy_rules,
                skills=rt.skills, user_text=user,
                memory_lines=rt.memory_lines,
            ),
        )
        compressed = maybe_compress(rt.messages)
        if compressed.compressed:
            rt.messages[:] = compressed.messages

        _agent_turn(
            console, rt.client, rt.messages, rt.schemas,
            rt.engine, rt.cfg, rt.session_id, sink=sink,
        )
        console.print()

        info = S.info(rt.session_id)
        msg_count = info["message_count"] if info else len(rt.messages) - 1
        console.print(f"[dim]{_status_line(rt.session_id, msg_count, rt.domain_hint)}  {_stats_line()}[/dim]")
        console.print()

    return 0

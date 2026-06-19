"""Hunds terminal-UI — luftig, designad, Rich-baserad.

Layout per turn:
  ─── status · stats ───
  du> input

    indragen respons

  du> _
"""

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from .. import __version__
from ..base_stats import compute
from ..providers.base import Message
from ..tools import registry

console = Console()
CREAM = "#E8E0D5"
RULE = "#a09080"


def _header(session_id: str, msg_count: int, domain: str) -> None:
    dom = domain or "general"
    sid = session_id[:8]
    stats = compute()
    parts = []
    for key in ("token_efficiency", "speed", "tool_judgment"):
        d = stats.get(key, {})
        lvl = d.get("level", "n/a")
        pct = d.get("success_rate_pct")
        lbl = {"token_efficiency": "tef", "speed": "spd", "tool_judgment": "jdg"}[key]
        s = f"{lbl} {lvl}"
        if isinstance(pct, (int, float)):
            s += f" {round(pct)}%"
        parts.append(s)

    left = Text()
    left.append("hund ", style=f"bold {CREAM}")
    left.append(f"{__version__}", style=CREAM)
    left.append(f"  {dom}  #{sid}  {msg_count} msg", style="dim")

    right = Text("  " + "  |  ".join(parts), style="dim")

    console.print(Rule(style=RULE))
    console.print(left, right)
    console.print()


def _response(text: str) -> None:
    for line in text.strip().split("\n"):
        console.print(f"  {line}")
    console.print()


def run_repl_ui() -> int:
    from ..agent import sessions as S
    from ..agent.context import maybe_compress
    from ..agent.loop import (
        _agent_turn, _init_runtime, _session_save,
        _stats_text, assemble_system_prompt,
    )

    rt = _init_runtime()
    if not rt.key:
        console.print("[red]API-nyckel saknas.[/red]")
        return 1

    _header(rt.session_id, 0, rt.domain_hint)

    response_buffer: list[str] = []

    class Sink:
        def thinking(self, msg=""):
            pass

        def clear_thinking(self):
            pass

        def chunk(self, text):
            response_buffer.append(text)

        def end_assistant(self):
            pass

        def error(self, msg):
            response_buffer.append(f"[red]{msg}[/red]")

        def tool_start(self, name, args):
            pass

        def tool_result(self, name, shown):
            pass

        def blocked(self, name, reason):
            response_buffer.append(f"[red]blocked: {name}[/red]")

        def declined(self, name, reason):
            pass

        def confirm(self, prompt):
            return console.input(f"  [{CREAM}]{prompt} [j/N][/{CREAM}] ").strip().lower() in {"j", "ja", "y", "yes"}

        on_chunk = chunk
        on_thinking = thinking
        on_error = error

        def on_tool(self, name, args):
            pass

    sink = Sink()

    while True:
        try:
            user = console.input(f"[{CREAM}]du> [/{CREAM}]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user in {"/exit", "/quit"}:
            break
        if user == "/stats":
            console.print(f"  {_stats_text()}")
            console.print()
            continue
        if user == "/profile":
            console.print(f"  {rt.profile.summary()}")
            console.print()
            continue
        if user == "/tools":
            console.print(f"  {', '.join(t.name for t in registry.all_tools())}")
            console.print()
            continue

        console.print()

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
        maybe_compress(rt.messages)

        response_buffer.clear()
        _agent_turn(
            console, rt.client, rt.messages, rt.schemas,
            rt.engine, rt.cfg, rt.session_id, sink=sink,
        )

        full = "".join(response_buffer)
        _response(full)

        info = S.info(rt.session_id)
        _header(rt.session_id, info["message_count"] if info else len(rt.messages) - 1, rt.domain_hint)

    return 0

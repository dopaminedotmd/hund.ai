"""Hunds terminal-UI — panel-baserad, clean.

Tre sektioner med Rich Panel-borders: status, konversation, basrad.
Sekventiell rendering — ingen Layout/Live.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..base_stats import compute
from ..providers.base import Message
from ..tools import registry
from .mascot import render as render_mascot
from .notifications import tool_line
from .render import render_baserad, render_status

console = Console()


def _section(content, **kw):
    """Rendera en Panel-sektion utan border overflow."""
    return Panel(content, padding=(0, 1), border_style="dim", **kw)


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
        console.print(
            f"[red]API-nyckel saknas.[/red] Satt med `hund setup` eller "
            f"`setx {rt.cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    def _print_header(msg_count=0):
        mascot = render_mascot()
        status = render_status(mascot, rt.session_id, msg_count, rt.domain_hint, locked=True)
        console.print(_section(status))
        console.print(_section(render_baserad(compute())))

    _print_header()

    class Sink:
        def thinking(self, msg="hund undersoker"):
            console.print(f"  [dim]{msg}...[/dim]")

        def clear_thinking(self):
            pass

        def chunk(self, text):
            console.print(text, end="", markup=False, highlight=False)

        def end_assistant(self):
            console.print()

        def error(self, msg):
            console.print(f"  {msg}")

        def tool_start(self, name, args):
            target = ""
            for k in ("path", "pattern", "command", "query", "target"):
                v = args.get(k)
                if v:
                    target = str(v)
                    break
            console.print(f"  {tool_line(name, target)}")

        def tool_result(self, name, shown):
            pass

        def blocked(self, name, reason):
            console.print(f"  [red]BLOCKERAD[/red] {name} — {reason}")

        def declined(self, name, reason):
            console.print(f"  [dim]{name} nekad — {reason}[/dim]")

        def confirm(self, prompt):
            answer = console.input(f"  {prompt} ").strip().lower()
            return answer in {"j", "ja", "y", "yes"}

        on_chunk = chunk
        on_thinking = thinking
        on_error = error

        def on_tool(self, name, args):
            self.tool_start(name, args)

    sink = Sink()

    while True:
        try:
            user = console.input("[bold green]du>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
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
            console.print(
                ", ".join(f"{t.name}({t.base_risk})" for t in registry.all_tools())
            )
            continue

        rt.messages.append(Message(role="user", content=user))
        _session_save(rt.session_id, "user", user)
        rt.messages[0] = Message(
            role="system",
            content=assemble_system_prompt(
                rt.persona,
                rt.profile,
                knowledge=rt.knowledge,
                policy_rules=rt.policy_rules,
                skills=rt.skills,
                user_text=user,
                memory_lines=rt.memory_lines,
            ),
        )
        compressed = maybe_compress(rt.messages)
        if compressed.compressed:
            rt.messages[:] = compressed.messages
            console.print(
                f"  [dim]({compressed.dropped_turns} turns komprimerade)[/dim]"
            )

        console.print()
        _agent_turn(
            console,
            rt.client,
            rt.messages,
            rt.schemas,
            rt.engine,
            rt.cfg,
            rt.session_id,
            sink=sink,
        )
        console.print()
        info = S.info(rt.session_id)
        _print_header(info["message_count"] if info else len(rt.messages) - 1)

    return 0

"""Hunds terminal-UI — enkel, fungerande.

Ingen Rich Layout/Live (för buggig med screen=True + input).
Istället: rendera status överst, konversation därunder, basrad sist,
med Rich-färger. Input med vanlig console.input().
"""

from rich.console import Console
from rich.text import Text

from ..base_stats import compute
from ..providers.base import Message
from ..tools import registry
from .mascot import render as render_mascot
from .notifications import tool_line
from .render import render_baserad, render_status

console = Console()


def _update_status(
    session_id: str, msg_count: int, domain: str
) -> None:
    status = render_status(render_mascot(), session_id, msg_count, domain, locked=True)
    console.print(status)


def _update_baserad() -> None:
    console.print(render_baserad(compute()))


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
            f"[red]API-nyckel saknas.[/red] Sätt med `hund setup` eller "
            f"`setx {rt.cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    # Intro
    console.print()
    _update_status(rt.session_id, 0, rt.domain_hint)
    _update_baserad()
    console.print()

    class SimpleSink:
        def thinking(self, msg: str = "hund undersöker") -> None:
            console.print(f"[dim]{msg}...[/dim]")

        def chunk(self, text: str) -> None:
            console.print(text, end="", markup=False, highlight=False)

        def end_assistant(self) -> None:
            console.print()

        def error(self, msg: str) -> None:
            console.print(msg)

        def tool_start(self, name: str, args: dict) -> None:
            target = ""
            for key in ("path", "pattern", "command", "query", "target"):
                val = args.get(key)
                if val:
                    target = str(val)
                    break
            console.print(tool_line(name, target))

        def tool_result(self, name: str, shown: str) -> None:
            pass

        def blocked(self, name: str, reason: str) -> None:
            console.print(f"[red]BLOCKERAD[/red] {name} — {reason}")

        def declined(self, name: str, reason: str) -> None:
            console.print(f"[dim]{name} nekad — {reason}[/dim]")

        def confirm(self, prompt: str) -> bool:
            answer = console.input(prompt + " ").strip().lower()
            return answer in {"j", "ja", "y", "yes"}

        on_chunk = chunk
        on_thinking = thinking
        on_error = error

        def on_tool(self, name: str, args: dict) -> None:
            self.tool_start(name, args)

    sink = SimpleSink()

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
                ", ".join(f"{tool.name}({tool.base_risk})" for tool in registry.all_tools())
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
                f"[dim]({compressed.dropped_turns} turns komprimerade)[/dim]"
            )

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
        _update_status(
            rt.session_id,
            info["message_count"] if info else len(rt.messages) - 1,
            rt.domain_hint,
        )
        _update_baserad()
        console.print()

    return 0

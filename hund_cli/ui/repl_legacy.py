"""Legacy Rich-only REPL — fallback om prompt_toolkit-REPL:strilen krånglar.

Körs via `hund repl`. Sekventiell Rich-loop med Rule-separatorer (före
prompt_toolkit-omskrivningen). Oförändrad från den fungerande versionen.
"""
from pathlib import Path

from rich.console import Console

from .. import __version__
from ..providers.base import Message
from ..tools import registry
from .render import (
    blocked_tool_message,
    format_session_rows,
    format_session_search_rows,
    plain_error_message,
    render_assistant_turn,
    render_startup,
    render_user_prompt,
)

console = Console()
CREAM = "#E8E0D5"


def _response(text: str) -> None:
    console.print(render_assistant_turn(text), markup=False, highlight=False)


def run_repl_legacy() -> int:
    from ..agent import sessions as S
    from ..agent.context import maybe_compress
    from ..agent.loop import (
        _agent_turn,
        _init_runtime,
        _session_save,
        _stats_text,
        assemble_system_prompt,
    )
    from ..config import HundConfig

    try:
        cfg = HundConfig.load()
        model = cfg.provider.model
        workspace = (cfg.workspace_root or Path.cwd()).name
    except Exception:
        model = None
        workspace = Path.cwd().name

    console.clear()
    console.print(
        render_startup(
            console.size.width,
            console.size.height,
            workspace=workspace,
            version=__version__,
            model=model,
        ),
        markup=False,
        highlight=False,
    )

    rt = _init_runtime()
    if not rt.key:
        console.print("[red]API-nyckel saknas.[/red]")
        return 1

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
            if response_buffer and not response_buffer[-1].endswith("\n"):
                response_buffer.append("\n")
            response_buffer.append(plain_error_message(msg))

        def tool_start(self, name, args):
            pass

        def tool_result(self, name, shown):
            pass

        def blocked(self, name, reason):
            if response_buffer and not response_buffer[-1].endswith("\n"):
                response_buffer.append("\n")
            response_buffer.append(blocked_tool_message(name, reason))

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
            user = console.input(f"[{CREAM}]{render_user_prompt().plain}[/{CREAM}]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user in {"/exit", "/quit"}:
            break
        if user == "/stats":
            _response(_stats_text())
            continue
        if user == "/profile":
            _response(rt.profile.summary())
            continue
        if user == "/tools":
            _response(", ".join(t.name for t in registry.all_tools()))
            continue

        if user == "/sessions" or user.startswith("/sessions "):
            rest = user[len("/sessions"):].strip()
            if not rest:
                _response(format_session_rows(S.list_sessions(limit=5)))
                continue

            sub, _, arg = rest.partition(" ")
            arg = arg.strip()
            if sub == "search":
                _response(format_session_search_rows(arg, S.search(arg)))
                continue
            if sub == "resume":
                if not arg:
                    _response("användning: /sessions resume <id>")
                    continue
                if S.set_active(arg):
                    active = S.get_active()
                    rt.session_id = active["id"] if active else arg
                    del rt.messages[1:]  # behåll systemprompt
                    for role, content in S.history(rt.session_id):
                        rt.messages.append(Message(role=role, content=content))
                    _response(f"byt till session #{rt.session_id[:8]}")
                else:
                    _response(f"ingen session matchade '{arg}'")
                continue
            if sub == "new":
                rt.session_id = S.create()
                del rt.messages[1:]
                _response(f"ny session #{rt.session_id[:8]}")
                continue
            _response("användning: /sessions [search <q> | resume <id> | new]")
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
        comp = maybe_compress(rt.messages)
        if comp.compressed:
            rt.messages[:] = comp.messages
            console.print(f"  ({comp.dropped_turns} turns komprimerade)", style="dim")

        response_buffer.clear()
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

        full = "".join(response_buffer)
        _response(full)

    return 0

"""Agent loop — interaktiv REPL med tool-calling. Hjärtat i levande Hund.

Säkerhetsmodell per tool-anrop (se agent/tool_dispatch.py + safety.py):
  - BLOCKED  -> alltid nekad
  - SAFE     -> auto-tillåten
  - WRITE/CONFIRM/DANGEROUS -> användaren godkänner
Varje request loggas till SQLite. Iteration-cap mot oändlig tool-loop.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from .. import __version__
from ..config import HundConfig
from ..doctor import profile_environment
from ..persona import load_persona
from ..providers.base import Message
from ..providers.openai_compatible import OpenAICompatibleClient
from ..secrets import load_api_key
from ..store.sqlite import connect_requests
from ..tools import registry
from ..tools.default_tools import register_defaults
from .prompt_builder import build_system_prompt
from .context import maybe_compress
from .safety import PermissionEngine
from .tool_dispatch import dispatch_tool_call

HELP = "[dim]/exit · /stats · /profile · /tools[/dim]"
MAX_TOOL_ROUNDS = 8


def _safe_policy_rules() -> list[str]:
    try:
        from ..policy.loader import load_policy

        return load_policy().prompt_rules()
    except Exception:
        return []


def _safe_skills() -> list:
    try:
        from ..skills.loader import load_skills

        return load_skills()
    except Exception:
        return []


def assemble_system_prompt(
    persona: str,
    profile,
    *,
    knowledge: list[tuple[str, str]] | None = None,
    policy_rules: list[str] | None = None,
    skills: list | None = None,
    user_text: str = "",
    memory_lines: list[str] | None = None,
) -> str:
    """Bygg systemprompt med deklarativa lager.

    Policy/memory är session-stabila. Skills matchas mot senaste användartexten så
    bara relevanta sammanfattningar injiceras (inte hela biblioteket). Ren funktion
    → testbar utan provider/DB.
    """
    from ..skills.matcher import summaries as _summaries

    summ = _summaries(skills or [], user_text) if user_text else []
    return build_system_prompt(
        persona,
        profile,
        knowledge=knowledge or None,
        policy_rules=policy_rules or None,
        skill_summaries=summ or None,
        memory_lines=memory_lines or None,
    )


def _init_runtime():
    """Gemensam init för REPL och Rich-UI. Returnerar SimpleNamespace.

    Sätter upp cfg/key, workspace+tools, engine, profil, persona, domain+knowledge,
    policy, skills, memory, systemprompt, provider-client, messages + en ny session.
    Returnerar ns med .key=False-instans (bara cfg+key) om nyckel saknas — anroparen
    avgör hur det ska visas. Återanvänds av både run_repl (plain) och ui.repl.run_repl_ui
    så ingen agent-logik dupliceras.
    """
    import types

    cfg = HundConfig.load()
    key = load_api_key(cfg.provider.api_key_env)
    if not key:
        return types.SimpleNamespace(cfg=cfg, key=None)

    workspace = (cfg.workspace_root or Path.cwd()).resolve()
    register_defaults(workspace)
    schemas = registry.as_provider_schemas()
    engine = PermissionEngine(workspace_root=workspace)

    profile = profile_environment(workspace=workspace)
    persona = load_persona()
    # Domain-detection styr knowledge top-K (Fas 4). Offline, ingen provider.
    try:
        from ..domains import detector as ddet
        from ..knowledge import store as kstore

        detection = ddet.detect(workspace)
        ddet.record_detection(detection)
        domain_hint = ddet.get_primary() or detection.primary
        knowledge = kstore.top_k(domain_hint, k=5) or kstore.top_k("general", k=5)
    except Exception:
        domain_hint = workspace.name
        knowledge = []
    policy_rules = _safe_policy_rules()
    skills = _safe_skills()
    # Persistent minne (fas 9.5 Del A): seed user.md, snapshot env vid första körning.
    from .. import memory as _memory

    _memory.ensure_seed()
    if not _memory.env_path().exists():
        _memory.refresh_env(profile)
    memory_lines = _memory.inject()
    system_prompt = assemble_system_prompt(
        persona, profile, knowledge=knowledge, policy_rules=policy_rules,
        skills=skills, user_text="", memory_lines=memory_lines,
    )
    client = OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    messages: list[Message] = [Message(role="system", content=system_prompt)]

    from . import sessions as S

    session_id = S.create()

    return types.SimpleNamespace(
        cfg=cfg, key=key, workspace=workspace, schemas=schemas, engine=engine,
        profile=profile, persona=persona, domain_hint=domain_hint, knowledge=knowledge,
        policy_rules=policy_rules, skills=skills, memory_lines=memory_lines,
        client=client, messages=messages, session_id=session_id,
    )


def _stats_text() -> str:
    """Token/latency-rad som markup-sträng. Delas av REPL och UI."""
    conn = connect_requests()
    row = conn.execute(
        """SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0),
                  COALESCE(SUM(completion_tokens),0), COALESCE(SUM(latency_ms),0)
           FROM requests"""
    ).fetchone()
    conn.close()
    n, tin, tout, lat = row
    return (
        f"[bold]stats[/bold] · requests: {n} · "
        f"tokens in/out: {tin}/{tout} · total latency: {lat}ms"
    )


def run_repl() -> int:
    console = Console()
    rt = _init_runtime()
    if not rt.key:
        console.print(
            f"[red]API-nyckel saknas.[/red] Sätt med `hund setup` eller "
            f"`setx {rt.cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    cfg = rt.cfg
    client = rt.client
    messages = rt.messages
    schemas = rt.schemas
    engine = rt.engine
    profile = rt.profile
    persona = rt.persona
    knowledge = rt.knowledge
    policy_rules = rt.policy_rules
    skills = rt.skills
    memory_lines = rt.memory_lines
    workspace = rt.workspace

    # Sessions (fas 9.5 Del B): återuppta senaste aktiv eller skapa ny.
    from . import sessions as S

    session_id: str | None = None
    active = S.get_active()
    if active and active["message_count"] > 0:
        try:
            ans = console.input(
                f"Återuppta session #{active['id'][:8]} "
                f"({active['message_count']} meddelanden)? [j/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans in ("j", "ja", "y", "yes"):
            session_id = active["id"]
            for role, content in S.history(session_id):
                messages.append(Message(role=role, content=content))
            console.print(f"[dim]återupptog {active['message_count']} meddelanden.[/dim]")
    if session_id is None:
        session_id = rt.session_id

    console.print(
        f"[bold green]Hund {__version__}[/bold green] — agent i din maskin "
        f"({profile.os}, {profile.cpu_count} kärnor, ws: {workspace.name}). "
        f"[dim]/sessions · /exit[/dim]"
    )

    while True:
        try:
            user = console.input("[bold]du>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("")
            break
        if not user:
            continue
        if user in ("/exit", "/quit"):
            break
        if user == "/stats":
            _show_stats(console)
            continue
        if user == "/profile":
            console.print(profile.summary())
            continue
        if user == "/tools":
            console.print(
                ", ".join(f"{t.name}({t.base_risk})" for t in registry.all_tools())
            )
            continue

        # /sessions — list | search <q> | resume <id> | new
        if user == "/sessions" or user.startswith("/sessions"):
            rest = user[len("/sessions"):].strip()
            if not rest:
                rows = S.list_sessions(limit=5)
                if not rows:
                    console.print("(inga sessioner)")
                for sid, created, title, count, act in rows:
                    mark = "*" if act else " "
                    console.print(f"{mark} #{sid[:8]} ({count}) {title[:40]} — {created}")
                continue
            sub, _, arg = rest.partition(" ")
            arg = arg.strip()
            if sub == "search":
                hits = S.search(arg)
                if not hits:
                    console.print(f"(inga träffar för '{arg}')")
                for sid_, role, snip, created in hits:
                    console.print(f"#{sid_[:8]} [{role}] {snip} — {created}", markup=False)
                continue
            if sub == "resume":
                if S.set_active(arg):
                    session_id = S.get_active()["id"]
                    del messages[1:]  # behåll systemprompt
                    for role, content in S.history(session_id):
                        messages.append(Message(role=role, content=content))
                    console.print(f"[green]byt till session #{session_id[:8]}[/green]")
                else:
                    console.print(f"[yellow]ingen session matchade '{arg}'[/yellow]")
                continue
            if sub == "new":
                session_id = S.create()
                del messages[1:]
                console.print(f"[green]ny session #{session_id[:8]}[/green]")
                continue
            console.print("[yellow]användning: /sessions [search <q> | resume <id> | new][/yellow]")
            continue

        messages.append(Message(role="user", content=user))
        _session_save(session_id, "user", user)
        # Komprimera om sessionen växer (Fas 5). Tool-output förblir data.
        comp = maybe_compress(messages)
        if comp.compressed:
            messages[:] = comp.messages
            console.print(
                f"[dim]({comp.dropped_turns} turns komprimerade)[/dim]"
            )
        _agent_turn(console, client, messages, schemas, engine, cfg, session_id)
    return 0


def _session_save(session_id: str | None, role: str, content: str) -> None:
    """Spara meddelande till aktiv session. Får ej krascha agentloopen."""
    if not session_id or not content:
        return
    try:
        from . import sessions as S

        S.add_message(session_id, role, content)
    except Exception:
        pass


def _agent_turn(console, client, messages, schemas, engine, cfg, session_id, *, sink=None) -> None:
    """Kör agenten (streaming) tills text-svar eller iteration-cap.

    sink (valfritt, duck-typed UI-sink). Givet → streaming/thinking/fel och
    tool-anrop styrs via sink (se sink-protokollet nedan). Saknas → exakt dagens
    console-beteende (print rakt ut).

    Sink-protokoll:
      sink.thinking(msg=...)      innan första token (startar prick-animation)
      sink.clear_thinking()       vid första token / fel (stoppar animation)
      sink.chunk(text)            strömmad assistant-token
      sink.end_assistant()        newline efter strömmad text
      sink.error(markup)          felrad
    Dessutom agerar sink som tool-hooks mot dispatch_tool_call (tool_start,
    confirm, tool_result, blocked, declined) när det givet.
    """
    for _ in range(MAX_TOOL_ROUNDS):
        if sink is not None:
            sink.thinking()
        import time
        MAX_RETRIES = 3
        for attempt in range(MAX_RETRIES + 1):
            parts = []
            first = True
            try:
                for chunk in client.stream(messages, tools=schemas):
                    parts.append(chunk)
                    if sink is not None:
                        if first:
                            sink.clear_thinking()
                            first = False
                        sink.chunk(chunk)
                    else:
                        console.print(chunk, end="", markup=False, highlight=False)
                break  # lyckades
            except RuntimeError as e:
                msg_str = str(e)
                if "429" in msg_str and attempt < MAX_RETRIES:
                    delay = 2 ** attempt  # 1, 2, 4 sekunder
                    if sink is not None:
                        sink.error(f"[dim]rate limit — forsoker igen om {delay}s...[/dim]")
                    else:
                        console.print(f"[dim]rate limit — forsoker igen om {delay}s...[/dim]")
                    time.sleep(delay)
                    continue
                msg = f"\n[red]{e}[/red]" if parts else f"[red]{e}[/red]"
                if sink is not None:
                    if first:
                        sink.clear_thinking()
                    sink.error(msg)
                else:
                    console.print(msg)
                messages.pop()  # rensa misslyckad user-msg
                return

        result = client.last_result
        assert result is not None
        result.text = "".join(parts)
        if parts and sink is not None:
            sink.end_assistant()
        elif parts:
            console.print()  # newline efter live-text

        if not result.tool_calls:
            messages.append(Message(role="assistant", content=result.text))
            _session_save(session_id, "assistant", result.text)
            _log_request(cfg, result, tool_calls=0)
            if sink is None:
                console.print()
            return

        # Tool-anrop — logga, dispatch varje (med användarens godkännande)
        _log_request(cfg, result, tool_calls=len(result.tool_calls))
        messages.append(
            Message(role="assistant", content=result.text or "", tool_calls=result.tool_calls)
        )
        _session_save(session_id, "assistant", result.text or "")
        for tc in result.tool_calls:
            outcome = dispatch_tool_call(tc, engine, console, hooks=sink)
            tc_id = tc.get("id") if isinstance(tc, dict) else None
            messages.append(Message(role="tool", content=outcome, tool_call_id=tc_id))
            _session_save(session_id, "tool", outcome)
    if sink is not None:
        sink.error("[yellow]max tool-rundor nådda — avbryter turn.[/yellow]")
    else:
        console.print("[yellow]max tool-rundor nådda — avbryter turn.[/yellow]\n")


def _log_request(cfg: HundConfig, result, tool_calls: int) -> None:
    """Logga request till logs/requests.db. Får ej krascha agentloopen."""
    try:
        conn = connect_requests()
        conn.execute(
            """INSERT INTO requests
               (id, created_at, task_class, model_requested, model_actual, provider,
                finish_reason, prompt_tokens, completion_tokens, latency_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                "tool_call" if tool_calls else "conversation",
                cfg.provider.model,
                cfg.provider.model,
                cfg.provider.base_url,
                result.finish_reason,
                result.prompt_tokens,
                result.completion_tokens,
                result.latency_ms,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _show_stats(console: Console) -> None:
    console.print(_stats_text())

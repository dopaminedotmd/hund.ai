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
from ..store.sqlite import connect
from ..tools import registry
from ..tools.default_tools import register_defaults
from .prompt_builder import build_system_prompt
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
) -> str:
    """Bygg systemprompt med deklarativa lager.

    Policy är session-stabil. Skills matchas mot senaste användartexten så bara
    relevanta sammanfattningar injiceras (inte hela biblioteket). Ren funktion
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
    )


def run_repl() -> int:
    console = Console()
    cfg = HundConfig.load()
    key = load_api_key(cfg.provider.api_key_env)
    if not key:
        console.print(
            f"[red]API-nyckel saknas.[/red] Sätt med `hund setup` eller "
            f"`setx {cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    workspace = (cfg.workspace_root or Path.cwd()).resolve()
    register_defaults(workspace)
    schemas = registry.as_provider_schemas()
    engine = PermissionEngine(workspace_root=workspace)

    profile = profile_environment(workspace=workspace)
    persona = load_persona()
    # V1-domain-hint = workspace-dirnamn; top-K kunskap om domänen finns.
    domain_hint = workspace.name
    try:
        from ..knowledge import store as kstore

        knowledge = kstore.top_k(domain_hint, k=5) or kstore.top_k("general", k=5)
    except Exception:
        knowledge = []
    policy_rules = _safe_policy_rules()
    skills = _safe_skills()
    system_prompt = assemble_system_prompt(
        persona, profile, knowledge=knowledge, policy_rules=policy_rules,
        skills=skills, user_text="",
    )
    client = OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    messages: list[Message] = [Message(role="system", content=system_prompt)]

    console.print(
        f"[bold green]Hund {__version__}[/bold green] — agent i din maskin "
        f"({profile.os}, {profile.cpu_count} kärnor, ws: {workspace.name}). " + HELP
    )

    conn = connect()
    try:
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
                _show_stats(console, conn)
                continue
            if user == "/profile":
                console.print(profile.summary())
                continue
            if user == "/tools":
                console.print(
                    ", ".join(f"{t.name}({t.base_risk})" for t in registry.all_tools())
                )
                continue

            messages.append(Message(role="user", content=user))
            # Matcha skills mot senaste användartexten → endast relevanta injiceras.
            messages[0] = Message(
                role="system",
                content=assemble_system_prompt(
                    persona, profile, knowledge=knowledge,
                    policy_rules=policy_rules, skills=skills, user_text=user,
                ),
            )
            _agent_turn(console, client, messages, schemas, engine, cfg, conn)
    finally:
        conn.close()
    return 0


def _agent_turn(console, client, messages, schemas, engine, cfg, conn) -> None:
    """Kör agenten (streaming) tills text-svar eller iteration-cap."""
    for _ in range(MAX_TOOL_ROUNDS):
        parts: list[str] = []
        try:
            for chunk in client.stream(messages, tools=schemas):
                parts.append(chunk)
                console.print(chunk, end="", markup=False, highlight=False)
        except RuntimeError as e:
            console.print(f"\n[red]{e}[/red]" if parts else f"[red]{e}[/red]")
            messages.pop()  # rensa misslyckad user-msg
            return

        result = client.last_result
        assert result is not None
        result.text = "".join(parts)
        if parts:
            console.print()  # newline efter live-text

        if not result.tool_calls:
            messages.append(Message(role="assistant", content=result.text))
            _log_request(conn, cfg, result, tool_calls=0)
            console.print()
            return

        # Tool-anrop — logga, dispatch varje (med användarens godkännande)
        _log_request(conn, cfg, result, tool_calls=len(result.tool_calls))
        messages.append(
            Message(role="assistant", content=result.text or "", tool_calls=result.tool_calls)
        )
        for tc in result.tool_calls:
            outcome = dispatch_tool_call(tc, engine, console)
            tc_id = tc.get("id") if isinstance(tc, dict) else None
            messages.append(Message(role="tool", content=outcome, tool_call_id=tc_id))
    console.print("[yellow]max tool-rundor nådda — avbryter turn.[/yellow]\n")


def _log_request(conn, cfg: HundConfig, result, tool_calls: int) -> None:
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


def _show_stats(console: Console, conn) -> None:
    row = conn.execute(
        """SELECT COUNT(*),
                  COALESCE(SUM(prompt_tokens),0),
                  COALESCE(SUM(completion_tokens),0),
                  COALESCE(SUM(latency_ms),0)
           FROM requests"""
    ).fetchone()
    n, tin, tout, lat = row
    console.print(
        f"[bold]stats[/bold] · requests: {n} · "
        f"tokens in/out: {tin}/{tout} · total latency: {lat}ms"
    )

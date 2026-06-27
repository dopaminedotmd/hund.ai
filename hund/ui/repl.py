"""REPL-huvudloop (Prompt Toolkit + streaming).

Ateranvänder agent.loop-internals: _init_runtime, _agent_turn(sink=),
_session_save, sessions, komprimering. Ingen agent-logik dupliceras - se
_init_runtime docstring ("anvands av ... ui.repl").
"""
from __future__ import annotations

import asyncio
import uuid

from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console

from ..agent import sessions as S
from ..agent.context import estimate_tokens, maybe_compress
from ..agent.loop import (
    _agent_turn,
    _dynamic_context_message,
    _init_runtime,
    _restore_frozen_system_prompt,
    _session_save,
    _trace_event,
)
from ..providers.base import Message
from . import theme
from .animations import level_up
from .commands import CommandContext, dispatch_command, is_slash
from .input import PromptState, create_session
from .output import StreamingSink
from .render import refresh_stats, render_startup, separator
from .session import offer_resume

_PROMPT = FormattedText([("bold fg:ansigreen", "du> ")])


async def _amain() -> int:
    console = Console()
    prev_active = S.get_active()  # FÖRE _init_runtime (som skapar ny + deaktiverar)
    rt = _init_runtime()
    if not rt.key:
        console.print(
            "[red]API-nyckel saknas.[/red] Sätt med `hund setup` eller "
            f"`setx {rt.cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    state = PromptState()
    init_stats = refresh_stats(state)
    if init_stats:  # seed prev_tiers → inga spurious level-ups första turnen
        for k, s in init_stats.items():
            state.prev_tiers[k] = s.get("tier", theme.EMDASH)
    session = create_session(state)
    sink = StreamingSink(console)
    ctx = CommandContext(console=console, rt=rt, state=state)

    render_startup(console, rt)

    messages = rt.messages
    frozen = messages[0].content if messages else ""
    # Resume fOrra aktiva sessionen (om finns med meddelanden)
    session_id = await offer_resume(console, session, rt, prev_active)
    state.session_id = session_id

    while True:
        try:
            user = (await session.prompt_async(_prompt_for(state))).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("")
            break

        if not user:
            continue
        if user in ("/exit", "/quit"):
            break
        if user == "/retry":
            _retry(console, rt, messages, session_id, sink, frozen)
            _after_turn(console, state)
            continue
        if is_slash(user):
            dispatch_command(user, ctx)
            continue

        console.print()  # blank line före svar (plan §1.3 separering)
        messages.append(Message(role="user", content=user))
        run_id = uuid.uuid4().hex
        _session_save(session_id, "user", user, run_id=run_id)

        # Komprimering (samma logik som loop.run_repl - Fas 5)
        tokens_before = estimate_tokens(messages)
        comp = maybe_compress(messages, client=rt.client)
        if comp.compressed:
            messages[:] = comp.messages
            _restore_frozen_system_prompt(messages, frozen)
            _trace_event(
                rt.engine, session_id, run_id, "context_compressed",
                {
                    "turns_dropped": comp.dropped_turns,
                    "tokens_before": tokens_before,
                    "tokens_after": comp.tokens,
                    "method": comp.method,
                },
            )
            console.print(f"[dim]({comp.dropped_turns} turns komprimerade)[/dim]")

        dynamic_msg = _dynamic_context_message(
            skills=rt.skills,
            user_text=user,
            workspace_id=str(rt.workspace),
            domain_hint=rt.domain_hint,
        )
        if dynamic_msg is not None:
            messages.append(dynamic_msg)

        try:
            _agent_turn(
                console, rt.client, messages, rt.schemas, rt.engine, rt.cfg,
                session_id, sink=sink, run_id=run_id,
            )
        finally:
            if dynamic_msg is not None:
                messages[:] = [m for m in messages if m is not dynamic_msg]
            _restore_frozen_system_prompt(messages, frozen)

        await _after_turn(console, state)

    return 0


def _prompt_for(state: PromptState):
    """Bygg prompt-prefix per-turn från aktivt tema (låter /theme leva)."""
    pt_color = theme.get_theme(state.theme_name)["user_prefix_pt"]
    return FormattedText([(f"bold fg:{pt_color}", "du> ")])


def _retry(console, rt, messages, session_id, sink, frozen) -> None:
    """Återskapa senaste svar: släng allt efter senaste user-msg, kör om turn."""
    last_user = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user = i
            break
    if last_user == -1:
        console.print("[dim](inget att återskapa)[/dim]")
        return
    del messages[last_user + 1:]
    console.print()
    run_id = uuid.uuid4().hex
    try:
        _agent_turn(
            console, rt.client, messages, rt.schemas, rt.engine, rt.cfg,
            session_id, sink=sink, run_id=run_id,
        )
    finally:
        _restore_frozen_system_prompt(messages, frozen)


async def _after_turn(console, state) -> None:
    """Efter varje agent-turn: uppdatera stats, ev level-up, separator."""
    new_stats = refresh_stats(state)
    if new_stats:
        for key, s in new_stats.items():
            new_tier = s.get("tier", theme.EMDASH)
            old_tier = state.prev_tiers.get(key)
            if old_tier and old_tier != new_tier and new_tier != theme.EMDASH:
                await level_up(console, key, old_tier, new_tier, s.get("value"))
            state.prev_tiers[key] = new_tier
    separator(console)


def run_repl() -> int:
    """Entrypoint. Trådat av hund.main."""
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 0

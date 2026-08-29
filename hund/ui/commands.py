"""Slash-kommandon for hund.ui REPL.

Ateranvander befintlig data: hund.stats (compute_all/render_stat/compute_velocity),
rt.skills (Skill-dataclass), tools.registry.all_tools(), rt.profile.summary().
Inga emojis (CLAUDE.md). Inga lador/paneler for konversation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from rich.console import Console
from rich.table import Table

from ..agent import sessions as S
from ..config import HundConfig, KNOWN_MODELS
from ..domains import confidence, detector
from .. import memory
from ..stats import compute_all, compute_velocity
from ..stats.tiers import render_bar, render_stat
from ..store.sqlite import connect_requests
from ..tools import registry
from . import theme
from .input import PromptState
from .render import mascot, render_character_card
from .session import export_session

# /clear anvands i help-listan; /exit hanteras i repl (break) men listas har.


@dataclass
class CommandContext:
    console: Console
    rt: Any                 # _init_runtime() SimpleNamespace
    state: PromptState


def is_slash(user_input: str) -> bool:
    return bool(user_input) and user_input.lstrip().startswith("/")


# -- handlers ---------------------------------------------------------------

def cmd_help(ctx: CommandContext, args: list[str]) -> None:
    from .screen_render import render_help_inline

    width = getattr(ctx.console, "width", 80) or 80
    help_text = render_help_inline(width=width)
    ctx.console.print(help_text, markup=False, highlight=False)


def cmd_trace(ctx: CommandContext, args: list[str]) -> None:
    """Show a compact redacted trace for the latest run in this session."""
    if args and args[0].lower() != "last":
        ctx.console.print("[dim]usage: /trace last[/dim]")
        return
    from ..trace.events import list_events_by_session

    session_id = getattr(ctx.rt, "session_id", None) or getattr(ctx.state, "session_id", None)
    if not session_id:
        ctx.console.print("[dim](no active session trace)[/dim]")
        return
    try:
        events = list_events_by_session(str(session_id))
    except Exception as exc:
        ctx.console.print(f"[red]could not read trace: {exc}[/red]")
        return
    if not events:
        ctx.console.print("[dim](no trace events for this session)[/dim]")
        return
    run_id = events[-1].run_id
    run_events = [event for event in events if event.run_id == run_id]
    ctx.console.print(f"[bold cyan]trace[/bold cyan] [dim]{run_id[:12]}[/dim]")
    for event in run_events:
        tool = f" · {event.tool_name}" if event.tool_name else ""
        payload = json.dumps(event.payload_redacted, ensure_ascii=False, sort_keys=True)
        detail = f" · {payload[:160]}" if payload and payload != "{}" else ""
        ctx.console.print(f"  {event.event_type}{tool}{detail}")



def cmd_stats(ctx: CommandContext, args: list[str]) -> None:
    workspace = getattr(ctx.rt, "workspace", None)
    if args and args[0] == "velocity":
        _print_velocity(ctx.console)
        return
    try:
        stats = compute_all()
    except Exception as e:
        ctx.console.print(f"[red]could not read stats: {e}[/red]")
        return
    if args and args[0] in ("compact", "min", "short"):
        render_character_card(ctx.console, ctx.rt, stats, compact=True)
        return
    try:
        from .screen_render import render_stats
        from .snapshots import collect_stats

        snapshot = collect_stats(workspace=workspace)
        ctx.console.print("CHARACTER SHEET", markup=False, highlight=False)
        ctx.console.print(
            render_stats(
                snapshot,
                width=getattr(ctx.console, "width", 80),
                height=24,
            ),
            markup=False,
            highlight=False,
        )
    except Exception:
        # Plain terminals keep a useful representation if optional telemetry is broken.
        render_character_card(ctx.console, ctx.rt, stats)


def _print_velocity(console: Console) -> None:
    console.print("[bold cyan][Stats][/bold cyan] velocity (last 7 days)")
    try:
        vel = compute_velocity()
    except Exception:
        console.print("[dim](velocity unavailable)[/dim]")
        return
    if not vel:
        console.print("[dim](no data)[/dim]")
        return
    for key in ("clarity", "precision", "efficiency", "endurance", "mastery"):
        v = vel.get(key)
        if not v:
            continue
        arrow = "+" if v["improving"] else "-"
        mark = "[green]+[/green]" if v["improving"] else "[red]-[/red]"
        console.print(f"  {key:<12} {mark} {v['delta_display']}")


def cmd_skills(ctx: CommandContext, args: list[str]) -> None:
    from ..skills.scope import ScopedSkillId, compute_workspace_key
    from ..skills.vault import SkillVault
    from .skills_view import render_skill_detail, render_skills_panel

    # If rt.skills is explicitly empty list (e.g. test mock), render empty card
    explicit_skills = getattr(ctx.rt, "skills", None)
    if explicit_skills is not None and len(explicit_skills) == 0:
        card = theme.boxify("SKILLS", ["(no skills registered)"], width=70, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
        return

    vault = SkillVault()
    workspace = getattr(ctx.rt, "workspace", None)
    workspace_key = compute_workspace_key(workspace)

    def scoped_item(name: str) -> ScopedSkillId:
        skill = next(
            (
                item
                for item in vault.get_domain_skills(workspace=workspace)
                if item.name == name
            ),
            None,
        )
        if skill is None:
            return ScopedSkillId("global", "", name)
        scope_key = workspace_key if skill.scope == "project" else "global"
        capability_id = skill.capability_id or f"{skill.domain}/{skill.name}"
        return ScopedSkillId(scope_key, capability_id, skill.name)
    subcmd = args[0].lower() if args else "all"

    if subcmd in ("info", "inspect", "show"):
        if len(args) < 2:
            ctx.console.print("[yellow]Usage: /skills info <skill_name>[/yellow]")
            return
        target = args[1]
        width = getattr(ctx.console, "width", None)
        detail_card = render_skill_detail(target, ctx.rt, vault=vault, width=width)
        ctx.console.print(detail_card)
        return

    if subcmd in ("core", "instincts", "builtins"):
        from ..skills.loader import _builtins_dir, _read_skill_file
        bdir = _builtins_dir()
        lines: list[str] = []
        if bdir.exists():
            for f in sorted(bdir.glob("*.json")):
                sk = _read_skill_file(f)
                if sk:
                    lines.append(f"[bold]{sk.name}[/bold] [dim]({sk.domain})[/dim] [core instinct]")
                    if sk.when_to_use:
                        lines.append(f"  [dim]{sk.when_to_use}[/dim]")
        card = theme.boxify(
            f"CORE INSTINCTS ({len(lines)//2} constitutional skills)",
            lines,
            width=70,
            border_style="cyan",
            title_style="bold cyan",
        )
        ctx.console.print(card)
        return

    if subcmd in ("vault", "vaulted", "list-vault"):
        vaulted = vault.list_vaulted(workspace=workspace)
        lines: list[str] = []
        if not vaulted:
            lines.append("[dim](vault is empty — all skills equipped)[/dim]")
        else:
            for s in vaulted:
                lines.append(
                    f"[bold]{s.name}[/bold] [dim]({s.domain})[/dim] [vaulted] safety={s.safety_level}"
                )
                if s.when_to_use:
                    lines.append(f"  [dim]{s.when_to_use}[/dim]")
        card = theme.boxify(
            f"SKILL VAULT ({len(vaulted)} available to equip)",
            lines,
            width=70,
            border_style="cyan",
            title_style="bold cyan",
        )
        ctx.console.print(card)
        return

    if subcmd == "equip":
        if len(args) < 2:
            ctx.console.print("[yellow]Usage: /skills equip <skill_name>[/yellow]")
            return
        target = args[1]
        ok, msg = vault.equip(scoped_item(target))
        if ok:
            ctx.console.print(f"[green]{msg}[/green]")
        else:
            ctx.console.print(f"[red]{msg}[/red]")
        return

    if subcmd == "park":
        if len(args) < 2:
            ctx.console.print("[yellow]Usage: /skills park <skill_name>[/yellow]")
            return
        target = args[1]
        ok, msg = vault.park(scoped_item(target))
        if ok:
            ctx.console.print(f"[green]{msg}[/green]")
        else:
            ctx.console.print(f"[red]{msg}[/red]")
        return

    if subcmd == "swap":
        if len(args) < 3:
            ctx.console.print("[yellow]Usage: /skills swap <old_skill> <new_skill>[/yellow]")
            return
        old_name, new_name = args[1], args[2]
        ok, msg = vault.swap(scoped_item(old_name), scoped_item(new_name))
        if ok:
            ctx.console.print(f"[green]{msg}[/green]")
        else:
            ctx.console.print(f"[red]{msg}[/red]")
        return

    # Default view contains domain skills only. Constitutional skills live in /tools.
    from .screen_render import render_skills
    from .snapshots import collect_skills

    panel = render_skills(
        collect_skills(workspace=workspace), width=getattr(ctx.console, "width", 80),
        height=24,
    )
    ctx.console.print(panel, markup=False, highlight=False)


def cmd_lessons(ctx: CommandContext, args: list[str]) -> None:
    """ /lessons            view accumulated lessons learned from errors & corrections """
    try:
        from ..feedback.store import FeedbackStore
        store = FeedbackStore()
        ws = getattr(ctx.rt, "workspace", None) or "."
        domain = getattr(ctx.rt, "domain_hint", None) or "general"
        lessons = store.query_top_lessons(str(ws), domain, limit=10)
        store.close()
    except Exception as e:
        ctx.console.print(f"[red]could not read lessons: {e}[/red]")
        return

    if not lessons:
        card = theme.boxify("LEARNED LESSONS", ["(no lessons accumulated yet for this workspace)"], width=70, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
        return

    lines = []
    for l in lessons:
        cat = l.get("category", "info")
        conf = l.get("confidence", 0.5)
        seen = l.get("seen_count", 1)
        text = l.get("lesson_text", "")
        lines.append(f"[bold cyan][{cat}][/bold cyan] (seen: {seen}x, conf: {conf:.2f})")
        lines.append(f"  {text}")
    card = theme.boxify(f"LEARNED LESSONS ({len(lessons)} active)", lines, width=70, border_style="cyan", title_style="bold cyan")
    ctx.console.print(card)

def cmd_learning(ctx: CommandContext, args: list[str]) -> None:
    """ /learning [receipt-id]    inspect durable learning receipts """
    try:
        from ..learning.runtime import format_receipt_bundle, list_receipts, receipt_detail_lines

        receipts = list_receipts(limit=100 if args else 20)
    except Exception as exc:
        ctx.console.print(f"[red]could not read learning history: {exc}[/red]")
        return
    if args:
        prefix = args[0]
        receipts = [item for item in receipts if item.receipt_id.startswith(prefix)]
    if not receipts:
        ctx.console.print("[dim](no learning receipts)[/dim]")
        return
    lines: list[str] = []
    for receipt in receipts:
        lines.append(f"[bold cyan]{receipt.receipt_id}[/bold cyan]  [dim]{receipt.status}[/dim]")
        lines.extend(format_receipt_bundle(receipt))
        if args:
            lines.extend(f"  {line}" for line in receipt_detail_lines(receipt))
        lines.append("")
    card = theme.boxify("LEARNING HISTORY", lines, width=76, border_style="cyan", title_style="bold cyan")
    ctx.console.print(card)



def cmd_profile(ctx: CommandContext, args: list[str]) -> None:
    """ /profile           system info migration notice """
    ctx.console.print("[bold cyan]System information has moved to /system[/bold cyan]")
    ctx.console.print("  Run [bold]/system[/bold] to inspect host hardware, storage, and runtimes.")
    ctx.console.print("  [dim](Named context profiles are planned for a future release)[/dim]")


def cmd_tools(ctx: CommandContext, args: list[str]) -> None:
    try:
        from .screen_render import render_tools
        from .snapshots import collect_tools

        snapshot = collect_tools()
    except Exception as e:
        ctx.console.print(f"[red]could not read tools: {e}[/red]")
        return
    ctx.console.print(
        render_tools(snapshot, width=getattr(ctx.console, "width", 80), height=24),
        markup=False,
        highlight=False,
    )


def cmd_clear(ctx: CommandContext, args: list[str]) -> None:
    ctx.console.clear()


def cmd_history(ctx: CommandContext, args: list[str]) -> None:
    """ /history            recent messages in active session
        /history search <q> FTS5 search across all sessions
        /history <id>       messages in session <id>
    """
    sid = getattr(ctx.state, "session_id", None)
    if args and args[0] == "search" and len(args) > 1:
        q = " ".join(args[1:])
        try:
            hits = S.search(q)
        except Exception as e:
            ctx.console.print(f"[red]search failed: {e}[/red]")
            return
        if not hits:
            ctx.console.print(f"[dim](no matches for '{q}')[/dim]")
            return
        for h_sid, role, snip, created in hits:
            mark = "user>" if role == "user" else "hund"
            ctx.console.print(f"[dim]#{h_sid[:8]}[/dim] [bold green]{mark}[/bold green] ", end="")
            ctx.console.print(snip, markup=False, highlight=False)
        return

    target = args[0] if args else sid
    if not target:
        ctx.console.print("[dim](no active session)[/dim]")
        return
    try:
        msgs = S.list_messages(target)
    except Exception as e:
        ctx.console.print(f"[red]could not read session: {e}[/red]")
        return
    if not msgs:
        ctx.console.print("[dim](empty session)[/dim]")
        return
    for role, content in msgs[-20:]:
        if role == "system":
            continue
        mark = "user>" if role == "user" else "hund"
        ctx.console.print(f"[bold green]{mark}[/bold green] ", end="")
        ctx.console.print(content, markup=False, highlight=False)


def cmd_export(ctx: CommandContext, args: list[str]) -> None:
    sid = getattr(ctx.state, "session_id", None)
    if not sid:
        ctx.console.print("[dim](no active session)[/dim]")
        return
    out = args[0] if args else None
    try:
        path = export_session(sid, out)
    except Exception as e:
        ctx.console.print(f"[red]export failed: {e}[/red]")
        return
    ctx.console.print(f"[green][OK][/green] exported to {path}")


# -- /session ---------------------------------------------------------------

def _age(created_at: str) -> str:
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        return "?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _global_tokens() -> int | None:
    try:
        conn = connect_requests()
        row = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) FROM requests"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return None


def cmd_session(ctx: CommandContext, args: list[str]) -> None:
    sid = getattr(ctx.state, "session_id", None)
    if not sid:
        ctx.console.print("[dim](no active session)[/dim]")
        return
    info = S.info(sid)
    if not info:
        ctx.console.print("[dim](session not found)[/dim]")
        return
    ctx.console.print(f"[bold]session[/bold] #{info['id'][:8]}")
    ctx.console.print(f"  created    {info['created_at']} ({_age(info['created_at'])} ago)")
    if info.get("title"):
        ctx.console.print(f"  title      {info['title']}")
    ctx.console.print(f"  messages   {info['message_count']}")
    ctx.console.print(f"  active     {'yes' if info['active'] else 'no'}")
    ctx.console.print(f"  domain     {getattr(ctx.rt, 'domain_hint', '?')}")
    ctx.console.print(f"  workspace  {getattr(ctx.rt, 'workspace', '?')}")
    tokens = _global_tokens()
    if tokens is not None:
        ctx.console.print(f"  tokens     {tokens} (global)")


def cmd_restore(ctx: CommandContext, args: list[str]) -> None:
    """Restore messages from previous session into active context."""
    target_id = args[0] if args else S.get_active()
    if not target_id:
        try:
            recent = S.list_sessions(limit=5)
            for s in recent:
                if s["id"] != ctx.state.session_id and s["message_count"] > 0:
                    target_id = s["id"]
                    break
        except Exception:
            pass

    if not target_id:
        ctx.console.print("[dim](no previous session to restore)[/dim]")
        return

    try:
        prev_msgs = S.list_messages(target_id)
        if not prev_msgs:
            ctx.console.print("[dim](session is empty)[/dim]")
            return

        from ..providers.base import Message
        from ..agent.context import estimate_tokens
        system_msgs = [m for m in ctx.rt.messages if m.role == "system"]
        restored = [
            Message(role=role, content=content)
            for role, content in prev_msgs
            if role in ("user", "assistant")
        ]
        ctx.rt.messages[:] = system_msgs + restored
        ctx.state.session_id = target_id
        ctx.state.extra["tokens"] = estimate_tokens(ctx.rt.messages)
        ctx.console.print(f"[green][OK][/green] restored #{target_id[:8]} ({len(restored)} messages).")
    except Exception as e:
        ctx.console.print(f"[red]could not restore session: {e}[/red]")


# -- /config ----------------------------------------------------------------


_CONFIG_KEYS = {"model", "base_url", "api_key_env", "workspace_root",
                "telemetry_local", "telemetry_upload"}


def _config_set(cfg: HundConfig, key: str, val: str) -> bool:
    if key not in _CONFIG_KEYS:
        return False
    if key in ("model", "base_url", "api_key_env"):
        setattr(cfg.provider, key, val)
    elif key == "workspace_root":
        cfg.workspace_root = None if val.lower() in ("none", "") else val  # type: ignore[assignment]
    elif key in ("telemetry_local", "telemetry_upload"):
        setattr(cfg, key, val.lower() in ("true", "1", "yes", "on", "j", "ja"))
    return True


def cmd_config(ctx: CommandContext, args: list[str]) -> None:
    cfg = getattr(ctx.rt, "cfg", None) or HundConfig.load()
    if args and args[0] == "set" and len(args) >= 3:
        key, val = args[1], " ".join(args[2:])
        if _config_set(cfg, key, val):
            try:
                cfg.save()
            except Exception as e:
                ctx.console.print(f"[red]could not save config: {e}[/red]")
                return
            ctx.console.print(f"[green][OK][/green] {key} = {val}")
        else:
            ctx.console.print(f"[red]unknown key: {key}. available: {', '.join(sorted(_CONFIG_KEYS))}[/red]")
        return
    ctx.console.print(f"  provider.base_url    {cfg.provider.base_url}")
    ctx.console.print(f"  provider.model       {cfg.provider.model}")
    ctx.console.print(f"  provider.api_key_env {cfg.provider.api_key_env}")
    ctx.console.print(f"  workspace_root       {cfg.workspace_root}")
    ctx.console.print(f"  telemetry_local      {cfg.telemetry_local}")
    ctx.console.print(f"  telemetry_upload     {cfg.telemetry_upload}")


# -- /theme -----------------------------------------------------------------

def cmd_theme(ctx: CommandContext, args: list[str]) -> None:
    if args:
        name = args[0].lower().strip()
        if name == "bone":
            name = "marshmallow"
        if name in theme.SKINS:
            ctx.state.theme_name = name
            # Persist skin selection to HundConfig
            cfg = getattr(ctx.rt, "cfg", None) or HundConfig.load()
            cfg.theme = name
            try:
                cfg.save()
            except Exception:
                pass
            # Dynamically update active Prompt Toolkit application style if running
            try:
                from prompt_toolkit.application.current import get_app
                app = get_app()
                if app is not None:
                    app.style = theme.make_pt_style(name)
                    app.invalidate()
            except Exception:
                pass
            ctx.console.print(f"[green][OK][/green] theme: {name}")
        else:
            ctx.console.print(
                f"[red]unknown theme: {name}. available: {', '.join(theme.theme_names())}[/red]"
            )
        return
    ctx.console.print(f"  current    {ctx.state.theme_name}")
    ctx.console.print(f"  available  {', '.join(theme.theme_names())}")


# -- /domains + /progress ---------------------------------------------------

def cmd_domains(ctx: CommandContext, args: list[str]) -> None:
    try:
        rows = detector.list_domains()
        primary = detector.get_primary()
    except Exception as e:
        ctx.console.print(f"[red]could not read domains: {e}[/red]")
        return
    if not rows:
        ctx.console.print("[dim](no domains detected)[/dim]")
        return
    for domain, status, conf, _det in rows:
        mark = "*" if domain == primary else " "
        ctx.console.print(f"  {mark} [bold]{domain}[/bold] [dim]{status}/{conf}[/dim]")


def cmd_progress(ctx: CommandContext, args: list[str]) -> None:
    try:
        items = confidence.list_confidence()
    except Exception as e:
        ctx.console.print(f"[red]could not read progress: {e}[/red]")
        return
    if not items:
        ctx.console.print("[dim](no domain progress recorded)[/dim]")
        return
    for it in items:
        domain = it.get("domain", "?")
        score = int(it.get("score", 0) or 0)
        tier = it.get("confidence_tier", "?")
        bar = render_bar(score, width=20)
        ctx.console.print(f"  {domain:<20} {bar} {score:>3}  {tier}")


# -- /mascot + /memory + /notifications ------------------------------------

def cmd_mascot(ctx: CommandContext, args: list[str]) -> None:
    ctx.console.print(mascot())


def cmd_memory(ctx: CommandContext, args: list[str]) -> None:
    """ /memory                      view user.md + environment.md
        /memory list                 view active verified memories
        /memory show                 view raw user.md + environment.md
        /memory add <text>           add verified preference
        /memory core <text>          add immutable core memory
        /memory why <id>             show provenance and audit trail
        /memory forget <id>          forget a memory item
        /memory conflicts            list flagged or contradicted items
    """
    if not args or (args and args[0] == "add" and len(args) < 2) or (args and args[0] == "show"):
        try:
            ctx.console.print(memory.show())
        except Exception as e:
            ctx.console.print(f"[red]could not read memory: {e}[/red]")
        return

    sub = args[0].lower()

    if sub == "list":
        memories = memory.list_active_memories()
        if not memories:
            ctx.console.print("[dim](no active memories in database)[/dim]")
            return

        lines: list[str] = []
        for m in memories:
            tag = "[bold cyan][CORE][/bold cyan]" if m.is_core else f"[dim]{m.category}[/dim]"
            lines.append(f"  • {tag} [bold]{m.memory_id}[/bold] (conf {m.confidence:.2f}): {m.statement}")

        card = theme.boxify("PERSISTENT USER MEMORY", lines, width=72, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
        return

    if sub == "add" and len(args) >= 2:
        text = " ".join(args[1:])
        try:
            existing = memory.user_bullets()
            existing.append(text)
            memory.update_user("\n".join(f"- {b}" for b in existing))
        except Exception as e:
            ctx.console.print(f"[red]could not write memory: {e}[/red]")
            return
        ctx.console.print(f"[green][OK][/green] memory updated: {text}")
        return

    if sub == "core" and len(args) >= 2:
        text = " ".join(args[1:])
        try:
            item = memory.record_memory(text, category="core", source_type="user", is_core=True)
            memory.sync_user_md()
            ctx.console.print(f"[green][OK][/green] core memory added ({item.memory_id}): {text}")
        except Exception as e:
            ctx.console.print(f"[red]could not add core memory: {e}[/red]")
        return

    if sub == "forget" and len(args) >= 2:
        target_id = args[1]
        try:
            ok = memory.forget_memory(target_id)
            if ok:
                memory.sync_user_md()
                ctx.console.print(f"[green][OK][/green] forgotten memory: {target_id}")
            else:
                ctx.console.print(f"[yellow]no memory item '{target_id}'[/yellow]")
        except Exception as e:
            ctx.console.print(f"[red]could not forget memory: {e}[/red]")
        return

    if sub == "why" and len(args) >= 2:
        target_id = args[1]
        item = memory.get_memory(target_id)
        if not item:
            ctx.console.print(f"[yellow]no memory item '{target_id}'[/yellow]")
            return

        lines = [
            f"statement:     {item.statement}",
            f"category:      {item.category}",
            f"scope:         {item.scope}",
            f"status:        {item.status}",
            f"confidence:    {item.confidence:.2f}",
            f"source_type:   {item.source_type}",
            f"is_core:       {item.is_core}",
            f"first_seen:    {item.first_seen}",
            f"last_seen:     {item.last_seen}",
            f"support_count: {item.support_count}",
            f"contradictions:{item.contradiction_count}",
        ]
        if item.supersedes:
            lines.append(f"supersedes:    {item.supersedes}")
        if item.superseded_by:
            lines.append(f"superseded_by: {item.superseded_by}")
        if item.evidence_ids:
            lines.append(f"evidence_ids:  {', '.join(item.evidence_ids)}")

        audits = memory.get_audit_history(target_id)
        if audits:
            lines.append("")
            lines.append("Audit Trail:")
            for a in audits:
                lines.append(f"  • {a.timestamp[:19]} [{a.action}] {a.reason or ''}")

        card = theme.boxify(f"MEMORY PROVENANCE: {target_id}", lines, width=72, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
        return

    if sub == "conflicts":
        conflicts = memory.list_conflicts()
        if not conflicts:
            ctx.console.print("[dim](no memory conflicts found)[/dim]")
            return
        lines = []
        for c in conflicts:
            lines.append(f"  • [{c.status}] {c.memory_id} (conf {c.confidence:.2f}, contra {c.contradiction_count}): {c.statement}")
        card = theme.boxify("MEMORY CONFLICTS", lines, width=72, border_style="yellow", title_style="bold yellow")
        ctx.console.print(card)
        return

    ctx.console.print(f"[yellow]unknown memory action '{sub}'. usage: /memory [add|core|forget|why|conflicts|list|show][/yellow]")


_ON_VALUES = {"on", "1", "true", "yes", "j", "ja"}


def cmd_notifications(ctx: CommandContext, args: list[str]) -> None:
    if args:
        ctx.state.notifications_enabled = args[0].lower() in _ON_VALUES
    state = "on" if ctx.state.notifications_enabled else "off"
    ctx.console.print(f"  notifications  {state}")


# -- /model, /usage, /doctor, /compress, /diff, /undo -----------------------

def cmd_model(ctx: CommandContext, args: list[str]) -> None:
    """ /model [name]      view or switch active LLM model """
    cfg = getattr(ctx.rt, "cfg", None) or HundConfig.load()
    if args:
        new_model = args[0]
        client = getattr(ctx.rt, "client", None)
        if client is not None:
            from ..providers.catalog import (
                MODEL_OPTIONS,
                activate_model,
                custom_model,
            )

            option = next((item for item in MODEL_OPTIONS if item.model_id == new_model), None)
            if option is None:
                option = custom_model(
                    getattr(cfg.provider, "provider_id", "custom"),
                    cfg.provider.base_url,
                    new_model,
                    getattr(cfg.provider, "context_window", 64_000),
                    credential_id=getattr(cfg.provider, "credential_id", "custom"),
                )
            ok, message = activate_model(ctx.rt, option)
            if not ok:
                ctx.console.print(f"[red]{message}[/red]")
                return
            ctx.state.extra["model"] = option.model_id
            ctx.state.extra["token_limit"] = option.context_window
            ctx.console.print(f"[green][OK][/green] active model: [bold]{new_model}[/bold]")
            return
        cfg.provider.model = new_model
        try:
            cfg.save()
        except Exception as e:
            ctx.console.print(f"[red]could not save model: {e}[/red]")
            return
        ctx.console.print(f"[green][OK][/green] active model: [bold]{new_model}[/bold]")
        return
    ctx.console.print(f"  model:      [bold]{cfg.provider.model}[/bold]")
    ctx.console.print(f"  base_url:   {cfg.provider.base_url}")
    from ..providers.catalog import MODEL_OPTIONS
    ctx.console.print(
        f"  available:  [dim]{', '.join(item.model_id for item in MODEL_OPTIONS)}[/dim]"
    )
    ctx.console.print("  switch:     /model deepseek-v4-flash   (flash = cheaper)")


def cmd_usage(ctx: CommandContext, args: list[str]) -> None:
    """ /usage             view session and global token usage """
    sid = getattr(ctx.state, "session_id", None)
    try:
        from .screen_render import render_usage
        from .snapshots import collect_usage

        snapshot = collect_usage(session_id=sid)
        card = render_usage(
            snapshot, width=getattr(ctx.console, "width", 80), height=24,
        )
    except Exception as exc:
        ctx.console.print(f"[red]could not read usage: {exc}[/red]")
        return
    ctx.console.print("Usage · tokens by local calendar", markup=False, highlight=False)
    ctx.console.print(card, markup=False, highlight=False)


def cmd_system(ctx: CommandContext, args: list[str]) -> None:
    """ /system [refresh|changes]    view known machine and environment snapshot """
    from ..stats.environment_snapshot import create_environment_snapshot
    from .screen_render import render_system

    force_fresh = bool(args and args[0].lower() in ("refresh", "-r", "--refresh"))
    changes_only = bool(args and args[0].lower() in ("changes", "-c", "--changes"))

    snapshot = create_environment_snapshot(force_fresh=force_fresh)
    width = getattr(ctx.console, "width", 80) or 80
    rendered = render_system(snapshot, width=width, height=24, changes_only=changes_only)
    ctx.console.print(rendered, markup=False, highlight=False)


def cmd_doctor(ctx: CommandContext, args: list[str]) -> None:
    """ /doctor [--fix|providers|learning|ui]    run read-only health checks """
    from ..doctor import diagnose_system
    from .screen_render import render_doctor

    review_fixes = bool(args and any(arg.lower() in ("--fix", "-f", "fix") for arg in args))
    report = diagnose_system(ctx.rt, getattr(ctx.rt, "workspace", None))
    width = getattr(ctx.console, "width", 80) or 80
    rendered = render_doctor(report, width=width, height=24, review_fixes=review_fixes)
    ctx.console.print(rendered, markup=False, highlight=False)


def cmd_retry(ctx: CommandContext, args: list[str]) -> None:
    """ /retry             regenerate last assistant response """
    ctx.console.print("[dim](retry is handled interactively in active turn)[/dim]")


def cmd_compress(ctx: CommandContext, args: list[str]) -> None:
    """ /compress          force context compression to save tokens """
    from ..agent.context import compress, compress_llm, estimate_tokens
    messages = getattr(ctx.rt, "messages", None)
    if not messages or len(messages) <= 2:
        ctx.console.print("[dim](too little context to compress)[/dim]")
        return
    tokens_before = estimate_tokens(messages)
    client = getattr(ctx.rt, "client", None)
    comp = None
    if client is not None:
        try:
            comp = compress_llm(client, messages)
        except Exception:
            comp = None
    if comp is None:
        comp = compress(messages)
    if comp.compressed:
        messages[:] = comp.messages
        ctx.console.print(
            f"[green][OK][/green] context compressed ({comp.method}): {tokens_before} -> {comp.tokens} tokens "
            f"({comp.dropped_turns} turns summarized)"
        )
    else:
        ctx.console.print(f"[dim]context is already compact ({tokens_before} tokens)[/dim]")


def cmd_diff(ctx: CommandContext, args: list[str]) -> None:
    """ /diff              view working tree modifications """
    import subprocess
    try:
        res = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            ctx.console.print("[bold cyan][Diff][/bold cyan] modified files in git tree:")
            ctx.console.print(res.stdout.strip())
        else:
            ctx.console.print("[dim](no uncommitted changes in git tree)[/dim]")
    except Exception as e:
        ctx.console.print(f"[dim](could not read git diff: {e})[/dim]")


def cmd_undo(ctx: CommandContext, args: list[str]) -> None:
    """ /undo              backup & restore instructions """
    ctx.console.print("[bold cyan][Undo][/bold cyan] backups & restore")
    ctx.console.print("  hund creates backups on workspace file modifications.")
    ctx.console.print("  to restore uncommitted git changes: [bold]git restore <file>[/bold]")


def cmd_auth(ctx: CommandContext, args: list[str]) -> None:
    """ /auth               manage model providers and credentials """
    ctx.console.print("[bold cyan]Authentication & Providers[/bold cyan]")
    ctx.console.print("  In fullscreen TUI, /auth opens the interactive provider manager.")
    ctx.console.print("  In CLI mode, configure API keys via environment variables or Windows Credential Manager.")


def cmd_reset(ctx: CommandContext, args: list[str]) -> None:
    """ /reset             reset all learned progression & data """
    from ..reset import reset_all_progress
    results = reset_all_progress()
    ctx.console.print("[bold cyan]hund reset complete:[/bold cyan]")
    for r in results:
        ctx.console.print(f"  • {r}")


def cmd_exit(ctx: CommandContext, args: list[str]) -> None:
    """ /exit              exit session """
    ctx.console.print("[dim]exiting session...[/dim]")


COMMANDS = {
    "help": cmd_help,
    "?": cmd_help,
    "system": cmd_system,
    "sys": cmd_system,
    "env": cmd_system,
    "doctor": cmd_doctor,
    "diag": cmd_doctor,
    "health": cmd_doctor,
    "profile": cmd_profile,
    "auth": cmd_auth,
    "reset": cmd_reset,
    "stats": cmd_stats,
    "sheet": cmd_stats,
    "character": cmd_stats,
    "skills": cmd_skills,
    "tools": cmd_tools,
    "history": cmd_history,
    "export": cmd_export,
    "session": cmd_session,
    "config": cmd_config,
    "model": cmd_model,
    "usage": cmd_usage,
    "cost": cmd_usage,
    "compress": cmd_compress,
    "compact": cmd_compress,
    "diff": cmd_diff,
    "undo": cmd_undo,
    "theme": cmd_theme,
    "domains": cmd_domains,
    "progress": cmd_progress,
    "mascot": cmd_mascot,
    "memory": cmd_memory,
    "lessons": cmd_lessons,
    "feedback": cmd_lessons,
    "learning": cmd_learning,
    "trace": cmd_trace,
    "notifications": cmd_notifications,
    "clear": cmd_clear,
    "cls": cmd_clear,
    "restore": cmd_restore,
    "retry": cmd_retry,
    "exit": cmd_exit,
    "quit": cmd_exit,
    "q": cmd_exit,
}

from .command_spec import COMMAND_REGISTRY, suggest_similar_command

HELP_ROWS: list[tuple[str, str]] = [
    (spec.usage or f"/{spec.name}", spec.short_description)
    for spec in COMMAND_REGISTRY
    if not spec.is_hidden and not spec.is_planned
]


def dispatch_command(user_input: str, ctx: CommandContext) -> bool:
    """Execute slash command. Return True if input was a slash command."""
    parts = user_input.strip().split()
    if not parts or not parts[0].startswith("/"):
        return False
    cmd = parts[0][1:].lower()
    args = parts[1:]
    handler = COMMANDS.get(cmd)
    if handler is None:
        suggestion = suggest_similar_command(cmd)
        if suggestion:
            ctx.console.print(f"[red]unknown command: /{cmd}. Did you mean [bold]/{suggestion}[/bold]?[/red]")
        else:
            ctx.console.print(f"[red]unknown command: /{cmd}. Type /help for available commands.[/red]")
        return True
    handler(ctx, args)
    return True

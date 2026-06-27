"""Slash-kommandon for hund.ui REPL.

Ateranvander befintlig data: hund.stats (compute_all/render_stat/compute_velocity),
rt.skills (Skill-dataclass), tools.registry.all_tools(), rt.profile.summary().
Inga emojis (CLAUDE.md). Inga lador/paneler for konversation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

from ..agent import sessions as S
from ..config import HundConfig
from ..domains import confidence, detector
from .. import memory
from ..stats import compute_all, compute_velocity
from ..stats.tiers import render_bar, render_stat
from ..store.sqlite import connect_requests
from ..tools import registry
from . import theme
from .input import PromptState
from .render import mascot
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
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Kommando", style="bold")
    t.add_column("Vad")
    for cmd, desc in HELP_ROWS:
        t.add_row(cmd, desc)
    ctx.console.print(t)


def cmd_stats(ctx: CommandContext, args: list[str]) -> None:
    ctx.console.print("[bold cyan][Stats][/bold cyan] base stats")
    try:
        stats = compute_all()
    except Exception as e:
        ctx.console.print(f"[red]kunde inte lasa stats: {e}[/red]")
        return
    if args and args[0] == "velocity":
        _print_velocity(ctx.console)
        return
    for key in ("clarity", "precision", "efficiency", "endurance", "mastery"):
        s = stats.get(key)
        if s:
            ctx.console.print(render_stat(s))
    ctx.console.print()
    _print_velocity(ctx.console)


def _print_velocity(console: Console) -> None:
    console.print("[bold cyan][Stats][/bold cyan] velocity (senaste veckan)")
    try:
        vel = compute_velocity()
    except Exception:
        console.print("[dim](velocity ej tillganglig)[/dim]")
        return
    if not vel:
        console.print("[dim](ingen data)[/dim]")
        return
    for key in ("clarity", "precision", "efficiency", "endurance", "mastery"):
        v = vel.get(key)
        if not v:
            continue
        arrow = "+" if v["improving"] else "-"
        mark = "[green]+[/green]" if v["improving"] else "[red]-[/red]"
        console.print(f"  {key:<12} {mark} {v['delta_display']}")


def cmd_skills(ctx: CommandContext, args: list[str]) -> None:
    skills = getattr(ctx.rt, "skills", None) or []
    if not skills:
        ctx.console.print("[dim](inga skills)[/dim]")
        return
    for s in skills:
        name = getattr(s, "name", "?")
        domain = getattr(s, "domain", "?")
        status = getattr(s, "status", "?")
        safety = getattr(s, "safety_level", "?")
        wtu = getattr(s, "when_to_use", "")
        ctx.console.print(
            f"[bold]{name}[/bold] [dim]({domain})[/dim] "
            f"[{status}] safety={safety}"
        )
        if wtu:
            ctx.console.print(f"[dim]  {wtu}[/dim]")


def cmd_profile(ctx: CommandContext, args: list[str]) -> None:
    profile = getattr(ctx.rt, "profile", None)
    if profile is None:
        ctx.console.print("[dim](profil saknas)[/dim]")
        return
    summary = profile.summary() if hasattr(profile, "summary") else str(profile)
    ctx.console.print(summary)


def cmd_tools(ctx: CommandContext, args: list[str]) -> None:
    try:
        tools = registry.all_tools()
    except Exception as e:
        ctx.console.print(f"[red]kunde inte lasa tools: {e}[/red]")
        return
    if not tools:
        ctx.console.print("[dim](inga tools)[/dim]")
        return
    for tool in tools:
        name = getattr(tool, "name", "?")
        risk = getattr(tool, "base_risk", "?")
        ctx.console.print(f"  [bold]{name}[/bold] [dim]risk={risk}[/dim]")


def cmd_clear(ctx: CommandContext, args: list[str]) -> None:
    ctx.console.clear()


def cmd_history(ctx: CommandContext, args: list[str]) -> None:
    """ /history            senaste meddelanden i aktuell session
        /history search <q> FTS5-sok over alla sessioner
        /history <id>       meddelanden i session <id>
    """
    sid = ctx.state.session_id
    if args and args[0] == "search" and len(args) > 1:
        q = " ".join(args[1:])
        try:
            hits = S.search(q)
        except Exception as e:
            ctx.console.print(f"[red]sokning misslyckades: {e}[/red]")
            return
        if not hits:
            ctx.console.print(f"[dim](inga traffar for '{q}')[/dim]")
            return
        for h_sid, role, snip, created in hits:
            mark = "du>" if role == "user" else "hund"
            ctx.console.print(f"[dim]#{h_sid[:8]}[/dim] [bold green]{mark}[/bold green] ", end="")
            ctx.console.print(snip, markup=False, highlight=False)
        return

    target = args[0] if args else sid
    if not target:
        ctx.console.print("[dim](ingen aktiv session)[/dim]")
        return
    try:
        msgs = S.list_messages(target)
    except Exception as e:
        ctx.console.print(f"[red]kunde inte lasa session: {e}[/red]")
        return
    if not msgs:
        ctx.console.print("[dim](tom session)[/dim]")
        return
    for role, content in msgs[-20:]:
        if role == "system":
            continue
        mark = "du>" if role == "user" else "hund"
        ctx.console.print(f"[bold green]{mark}[/bold green] ", end="")
        ctx.console.print(content, markup=False, highlight=False)


def cmd_export(ctx: CommandContext, args: list[str]) -> None:
    sid = ctx.state.session_id
    if not sid:
        ctx.console.print("[dim](ingen aktiv session)[/dim]")
        return
    out = args[0] if args else None
    try:
        path = export_session(sid, out)
    except Exception as e:
        ctx.console.print(f"[red]export misslyckades: {e}[/red]")
        return
    ctx.console.print(f"[green][OK][/green] exporterade till {path}")


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
    sid = ctx.state.session_id
    if not sid:
        ctx.console.print("[dim](ingen aktiv session)[/dim]")
        return
    info = S.info(sid)
    if not info:
        ctx.console.print("[dim](session hittades inte)[/dim]")
        return
    ctx.console.print(f"[bold]session[/bold] #{info['id'][:8]}")
    ctx.console.print(f"  created    {info['created_at']} ({_age(info['created_at'])} sedan)")
    if info.get("title"):
        ctx.console.print(f"  title      {info['title']}")
    ctx.console.print(f"  messages   {info['message_count']}")
    ctx.console.print(f"  active     {'yes' if info['active'] else 'no'}")
    ctx.console.print(f"  domain     {getattr(ctx.rt, 'domain_hint', '?')}")
    ctx.console.print(f"  workspace  {getattr(ctx.rt, 'workspace', '?')}")
    tokens = _global_tokens()
    if tokens is not None:
        ctx.console.print(f"  tokens     {tokens} (global)")


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
                ctx.console.print(f"[red]kunde inte spara: {e}[/red]")
                return
            ctx.console.print(f"[green][OK][/green] {key} = {val}")
        else:
            ctx.console.print(f"[red]okand nyckel: {key}. valbara: {', '.join(sorted(_CONFIG_KEYS))}[/red]")
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
        name = args[0]
        if name in theme.THEMES:
            ctx.state.theme_name = name
            ctx.console.print(f"[green][OK][/green] tema: {name}")
        else:
            ctx.console.print(
                f"[red]okant tema: {name}. valbara: {', '.join(theme.theme_names())}[/red]"
            )
        return
    ctx.console.print(f"  aktuellt   {ctx.state.theme_name}")
    ctx.console.print(f"  valbara    {', '.join(theme.theme_names())}")


# -- /domains + /progress ---------------------------------------------------

def cmd_domains(ctx: CommandContext, args: list[str]) -> None:
    try:
        rows = detector.list_domains()
        primary = detector.get_primary()
    except Exception as e:
        ctx.console.print(f"[red]kunde inte lasa domaner: {e}[/red]")
        return
    if not rows:
        ctx.console.print("[dim](inga domaner detekterade)[/dim]")
        return
    for domain, status, conf, _det in rows:
        mark = "*" if domain == primary else " "
        ctx.console.print(f"  {mark} [bold]{domain}[/bold] [dim]{status}/{conf}[/dim]")


def cmd_progress(ctx: CommandContext, args: list[str]) -> None:
    try:
        items = confidence.list_confidence()
    except Exception as e:
        ctx.console.print(f"[red]kunde inte lasa progress: {e}[/red]")
        return
    if not items:
        ctx.console.print("[dim](ingen doman-progress)[/dim]")
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
    """ /memory            visa user.md + environment.md
        /memory add <text>  append bullet till user.md
    """
    if args and args[0] == "add" and len(args) >= 2:
        text = " ".join(args[1:])
        try:
            existing = memory.user_bullets()
            existing.append(text)
            memory.update_user("\n".join(f"- {b}" for b in existing))
        except Exception as e:
            ctx.console.print(f"[red]kunde inte skriva minne: {e}[/red]")
            return
        ctx.console.print(f"[green][OK][/green] minne uppdaterat: {text}")
        return
    try:
        ctx.console.print(memory.show())
    except Exception as e:
        ctx.console.print(f"[red]kunde inte lasa minne: {e}[/red]")


_ON_VALUES = {"on", "1", "true", "yes", "j", "ja"}


def cmd_notifications(ctx: CommandContext, args: list[str]) -> None:
    if args:
        ctx.state.notifications_enabled = args[0].lower() in _ON_VALUES
    state = "on" if ctx.state.notifications_enabled else "off"
    ctx.console.print(f"  notiser  {state}")


# -- dispatch ---------------------------------------------------------------

COMMANDS = {
    "help": cmd_help,
    "stats": cmd_stats,
    "skills": cmd_skills,
    "profile": cmd_profile,
    "tools": cmd_tools,
    "history": cmd_history,
    "export": cmd_export,
    "session": cmd_session,
    "config": cmd_config,
    "theme": cmd_theme,
    "domains": cmd_domains,
    "progress": cmd_progress,
    "mascot": cmd_mascot,
    "memory": cmd_memory,
    "notifications": cmd_notifications,
    "clear": cmd_clear,
}

HELP_ROWS = [
    ("/help", "lista kommandon"),
    ("/stats [velocity]", "base stats + velocity"),
    ("/skills", "deklarativa skills"),
    ("/profile", "anvandarprofil + miljo"),
    ("/tools", "tillgangliga tools + risk"),
    ("/history [search <q> | <id>]", "session-meddelanden / sok"),
    ("/export [fil]", "exportera session till .md"),
    ("/session", "session-stats (tid, meddelanden, tokens)"),
    ("/config [set <k> <v>]", "visa/andra installningar"),
    ("/theme [namn]", "byt tema (farger)"),
    ("/domains", "domaner + confidence"),
    ("/progress", "doman-progressbars"),
    ("/memory [add <text>]", "persistent minne (user.md + environment.md)"),
    ("/notifications [on|off]", "notiser pa/av"),
    ("/mascot", "visa pixel-hund"),
    ("/clear", "rensa skarm"),
    ("/exit", "avsluta"),
    ("/retry", "aterskapa senaste svar"),
]


def dispatch_command(user_input: str, ctx: CommandContext) -> bool:
    """Kor slash-kommando. Returnera True om det var ett kommando."""
    parts = user_input.strip().split()
    if not parts or not parts[0].startswith("/"):
        return False
    cmd = parts[0][1:]
    args = parts[1:]
    handler = COMMANDS.get(cmd)
    if handler is None:
        ctx.console.print(f"[red]okant kommando: /{cmd}. /help for lista.[/red]")
        return True
    handler(ctx, args)
    return True

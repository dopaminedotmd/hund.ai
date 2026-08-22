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
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("Command", style="bold")
    t.add_column("Description")
    for cmd, desc in HELP_ROWS:
        t.add_row(cmd, desc)
    ctx.console.print(t)
    ctx.console.print()
    from .keys import format_keymap_summary
    for line in format_keymap_summary():
        ctx.console.print(line)



def cmd_stats(ctx: CommandContext, args: list[str]) -> None:
    try:
        stats = compute_all()
    except Exception as e:
        ctx.console.print(f"[red]could not read stats: {e}[/red]")
        return
    if args and args[0] == "velocity":
        _print_velocity(ctx.console)
        return
    if args and args[0] in ("compact", "min", "short"):
        render_character_card(ctx.console, ctx.rt, stats, compact=True)
        return
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
    from ..skills.vault import SkillVault

    # If rt.skills is explicitly empty list (e.g. test mock), render empty card
    explicit_skills = getattr(ctx.rt, "skills", None)
    if explicit_skills is not None and len(explicit_skills) == 0:
        card = theme.boxify("SKILLS", ["(no skills registered)"], width=70, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
        return

    vault = SkillVault()
    subcmd = args[0].lower() if args else "active"


    if subcmd in ("vault", "vaulted", "list-vault"):
        vaulted = vault.list_vaulted()
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
        ok, msg = vault.equip(target)
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
        ok, msg = vault.park(target)
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
        ok, msg = vault.swap(old_name, new_name)
        if ok:
            ctx.console.print(f"[green]{msg}[/green]")
        else:
            ctx.console.print(f"[red]{msg}[/red]")
        return

    # Default: show active skills
    active = vault.get_active_skills()
    if not active:
        card = theme.boxify("ACTIVE SKILLS", ["(no active skills)"], width=70, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
        return

    lines = []
    for s in active:
        lines.append(
            f"[bold]{s.name}[/bold] [dim]({s.domain})[/dim] [active] safety={s.safety_level}"
        )
        if s.when_to_use:
            lines.append(f"  [dim]{s.when_to_use}[/dim]")
    card = theme.boxify(
        f"EQUIPPED SKILLS [{len(active)}/{vault.max_active} active]",
        lines,
        width=70,
        border_style="cyan",
        title_style="bold cyan",
    )
    ctx.console.print(card)



def cmd_profile(ctx: CommandContext, args: list[str]) -> None:
    profile = getattr(ctx.rt, "profile", None)
    if profile is None:
        ctx.console.print("[dim](profile unavailable)[/dim]")
        return
    summary = profile.summary() if hasattr(profile, "summary") else str(profile)
    ctx.console.print(summary)


def cmd_tools(ctx: CommandContext, args: list[str]) -> None:
    try:
        tools = registry.all_tools()
    except Exception as e:
        ctx.console.print(f"[red]could not read tools: {e}[/red]")
        return
    if not tools:
        ctx.console.print("[dim](no tools available)[/dim]")
        return
    for tool in tools:
        name = getattr(tool, "name", "?")
        risk = getattr(tool, "base_risk", "?")
        ctx.console.print(f"  [bold]{name}[/bold] [dim]risk={risk}[/dim]")


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
        name = args[0]
        if name in theme.THEMES:
            ctx.state.theme_name = name
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
    """ /memory            view user.md + environment.md
        /memory add <text>  append bullet to user.md
    """
    if args and args[0] == "add" and len(args) >= 2:
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
    try:
        ctx.console.print(memory.show())
    except Exception as e:
        ctx.console.print(f"[red]could not read memory: {e}[/red]")


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
        cfg.provider.model = new_model
        try:
            cfg.save()
        except Exception as e:
            ctx.console.print(f"[red]could not save model: {e}[/red]")
            return
        client = getattr(ctx.rt, "client", None)
        if client and hasattr(client, "model"):
            client.model = new_model
        ctx.console.print(f"[green][OK][/green] active model: [bold]{new_model}[/bold]")
        return
    ctx.console.print(f"  model:      [bold]{cfg.provider.model}[/bold]")
    ctx.console.print(f"  base_url:   {cfg.provider.base_url}")


def cmd_usage(ctx: CommandContext, args: list[str]) -> None:
    """ /usage             view session and global token usage """
    global_tok = _global_tokens()
    sid = getattr(ctx.state, "session_id", None)
    msg_count = 0
    if sid:
        info = S.info(sid)
        if info:
            msg_count = info.get("message_count", 0)

    lines: list[str] = []
    if sid:
        lines.append(f"active session:  #{sid[:8]}")
        lines.append(f"messages:        {msg_count}")
    if global_tok is not None:
        lines.append(f"global tokens:   {global_tok:,}")
    else:
        lines.append("global tokens:   (unavailable)")
    card = theme.boxify("[Usage] Resource Consumption", lines, width=68, border_style="cyan", title_style="bold cyan")
    ctx.console.print(card)


def cmd_doctor(ctx: CommandContext, args: list[str]) -> None:
    """ /doctor            run hardware and system environment diagnosis """
    from ..doctor import profile_environment
    ctx.console.print("[bold cyan][Doctor][/bold cyan] analyzing hardware and system environment...")
    try:
        profile = profile_environment()
        ctx.rt.profile = profile
        card = theme.boxify("SYSTEM DOCTOR", str(profile).splitlines(), width=70, border_style="cyan", title_style="bold cyan")
        ctx.console.print(card)
    except Exception as e:
        ctx.console.print(f"[red]diagnosis failed: {e}[/red]")


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


# -- dispatch ---------------------------------------------------------------

COMMANDS = {
    "help": cmd_help,
    "stats": cmd_stats,
    "sheet": cmd_stats,
    "character": cmd_stats,
    "skills": cmd_skills,
    "profile": cmd_profile,
    "tools": cmd_tools,
    "history": cmd_history,
    "export": cmd_export,
    "session": cmd_session,
    "config": cmd_config,
    "model": cmd_model,
    "usage": cmd_usage,
    "cost": cmd_usage,
    "doctor": cmd_doctor,
    "compress": cmd_compress,
    "compact": cmd_compress,
    "diff": cmd_diff,
    "undo": cmd_undo,
    "theme": cmd_theme,
    "domains": cmd_domains,
    "progress": cmd_progress,
    "mascot": cmd_mascot,
    "memory": cmd_memory,
    "notifications": cmd_notifications,
    "clear": cmd_clear,
}

HELP_ROWS = [
    ("/help", "list available commands"),
    ("/stats [velocity|compact]", "RPG character sheet, base stats & trend"),
    ("/model [name]", "view or switch active LLM model"),
    ("/usage", "token & resource consumption"),
    ("/doctor", "run hardware and system environment diagnosis"),
    ("/compress", "compress context to save tokens"),
    ("/diff", "view working tree modifications"),
    ("/undo", "file backup & restore information"),
    ("/skills", "declarative skills"),
    ("/profile", "user profile + environment"),
    ("/tools", "available tools + risk levels"),
    ("/history [search <q> | <id>]", "session messages / search"),
    ("/export [file]", "export session to .md"),
    ("/session", "session stats (time, messages, tokens)"),
    ("/config [set <k> <v>]", "view/update settings"),
    ("/theme [name]", "switch theme (colors)"),
    ("/domains", "domains + confidence"),
    ("/progress", "domain progress bars"),
    ("/memory [add <text>]", "persistent memory (user.md + environment.md)"),
    ("/notifications [on|off]", "toggle notifications on/off"),
    ("/mascot", "display pixel hound"),
    ("/clear", "clear screen"),
    ("/exit", "exit session"),
    ("/retry", "regenerate last assistant response"),
]


def dispatch_command(user_input: str, ctx: CommandContext) -> bool:
    """Execute slash command. Return True if input was a slash command."""
    parts = user_input.strip().split()
    if not parts or not parts[0].startswith("/"):
        return False
    cmd = parts[0][1:]
    args = parts[1:]
    handler = COMMANDS.get(cmd)
    if handler is None:
        ctx.console.print(f"[red]unknown command: /{cmd}. type /help for list.[/red]")
        return True
    handler(ctx, args)
    return True

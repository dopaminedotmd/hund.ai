"""Hund CLI entrypoint: `hund`.

Skelett 0.1.0. Subkommandon är stubbar som växer in enligt docs/mvp.md.
Körningen nås via entrypoint `hund = "hund_cli.main:app"` i pyproject.toml.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows console defaultar till cp1252 → kraschar på å/ä/ö/Σ i piped output.
# Tvinga UTF-8 tidigt (review flaggade Windows-encoding som verklig risk).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from rich.console import Console

from . import __version__

app = typer.Typer(
    name="hund",
    help="Hund — agenten som lever i din hårdvara.",
    no_args_is_help=False,
    add_completion=False,
)
console = Console()

# Sub-apps
learning_app = typer.Typer(help="Lokal learning/gap-events. Aldrig extern upload.")
proposals_app = typer.Typer(help="Self-improvement proposals (deklarativa, human-gated).")
knowledge_app = typer.Typer(help="Kunskapsenheter (LFU/MRU).")
stats_app = typer.Typer(help="Statistik och base stats.")
privacy_app = typer.Typer(help="Privacy/redaction. Offline, ingen upload.")
policy_app = typer.Typer(help="Runtime policy (deklarativ, ej core-kod).")
app.add_typer(learning_app, name="learning")
app.add_typer(proposals_app, name="proposals")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(stats_app, name="stats")
app.add_typer(privacy_app, name="privacy")
app.add_typer(policy_app, name="policy")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Visa version och avsluta.",
        is_eager=True,
    ),
) -> None:
    """Hund — agenten som lever i din hårdvara."""
    if version:
        console.print(f"hund {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from .agent.loop import run_repl

        raise SystemExit(run_repl())


@app.command()
def doctor() -> None:
    """Analysera hårdvara/miljö och spara profil lokalt.

    Differentiatorn: profilen ska INJICERAS i systemprompten och ändra Hundens
    beteende (se docs/mvp.md komponent 2). Stub i 0.1.0.
    """
    from .doctor import profile_environment

    profile = profile_environment()
    console.print(profile)


@app.command()
def setup() -> None:
    """Konfigurera provider + spara API-nyckel i OS-nyckelring (DPAPI)."""
    from .config import HundConfig
    from .secrets import load_api_key, save_api_key

    console.print("[bold]hund setup[/bold]")
    cfg = HundConfig.load()
    base = console.input(
        f"provider base_url [{cfg.provider.base_url}]: "
    ).strip() or cfg.provider.base_url
    model = (
        console.input(f"model [{cfg.provider.model}]: ").strip() or cfg.provider.model
    )
    cfg.provider.base_url = base
    cfg.provider.model = model
    cfg.save()
    console.print(f"[green]sparat:[/green] {base} · {model}")

    key = console.input("API-nyckel (Enter = behåll): ").strip()
    if key:
        if save_api_key(key):
            console.print("[green]nyckel sparad i OS-nyckelring.[/green]")
        else:
            console.print(
                "[yellow]kunde ej spara i nyckelring — sätt HUND_API_KEY i env.[/yellow]"
            )
    else:
        console.print(
            f"nuvarande nyckel: {'finns' if load_api_key() else '[red]saknas[/red]'}"
        )
    console.print("klart. kör [bold]hund[/bold].")


@app.command()
def propose() -> None:
    """Hund sammanfattar öppna gaps till ett DEKLARATIVT förslag (ej kod).

    Säkerhet: change_type tvingas runtime_policy/skill/hundk/prompt/test.
    Core/TCB får aldrig föreslås. Kräver human gate (hund proposals approve).
    """
    import json

    from .config import HundConfig
    from .learning.observer import list_gap_events
    from .providers.base import Message
    from .providers.openai_compatible import OpenAICompatibleClient
    from .secrets import load_api_key
    from .selfimprovement import proposal as P

    cfg = HundConfig.load()
    key = load_api_key(cfg.provider.api_key_env)
    gaps = list_gap_events(status="open")
    if not gaps:
        console.print("(inga öppna gaps att föreslå från — logga med `hund learning gap`).")
        return
    if not key:
        console.print("[red]API-nyckel saknas.[/red]")
        return

    from .learning.redactor import redact_text

    gap_text = "\n".join(f"- [{g[2]}] {redact_text(g[3]).text}" for g in gaps)
    sysp = (
        "Du granskar gap-events (kunskapsluckor) och föreslår EN deklarativ "
        "förbättring av Hunds beteende. Svara ENDAST med giltig JSON, inga "
        "markdown-backticks: "
        '{"title","problem","proposed_change",'
        '"change_type" (en av: runtime_policy|skill|hundk|prompt|test),'
        '"risk","tests_needed"}. '
        "change_type får ALDRIG vara core/engine/safety/updater — de är TCB."
    )
    client = OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    try:
        r = client.complete([Message(role="system", content=sysp),
                             Message(role="user", content=f"Gaps:\n{gap_text}")])
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        return

    text = r.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        summary = json.loads(text)
    except json.JSONDecodeError:
        console.print("[red]kunde ej tolka svaret som JSON:[/red]")
        console.print(text[:400])
        return

    prop = P.build_from_gaps(gaps, summary)
    P.create(prop)
    console.print(prop.as_markdown())
    console.print(
        f"[green]proposal skapad[/green] {prop.id[:8]} — "
        f"granska: `hund proposals show {prop.id[:8]}`"
    )


@app.command()
def verify() -> None:
    """Verifiera Hund-systemet (persona laddad, permission-block aktivt)."""
    console.print("[green]verify[/green]: hund_cli importerar OK.")
    console.print(f"version: {__version__}")


def _privacy_input(text: str, file: Path | None) -> str:
    if file:
        return file.read_text(encoding="utf-8", errors="replace")
    if text:
        return text
    console.print("[red]ange --text eller --file[/red]")
    raise typer.Exit(1)


@privacy_app.command("check")
def privacy_check(
    text: str = typer.Option("", "--text", "-t", help="Text att redaktera."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Fil att läsa och redaktera."),
) -> None:
    """Förhandsgranska redaction lokalt. Ingen data lämnar maskinen."""
    from .learning.redactor import redact_text

    result = redact_text(_privacy_input(text, file))
    console.print(result.text, markup=False, highlight=False)
    console.print(f"risk: {result.risk_level}")
    console.print("blocked_fields: " + (", ".join(result.blocked_fields) or "none"))


@privacy_app.command("preview-export")
def privacy_preview_export(
    text: str = typer.Option("", "--text", "-t", help="Text att förhandsgranska."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Fil att läsa."),
) -> None:
    """Visa structured-only JSON som skulle kunna exporteras. Ingen upload."""
    from .learning.redactor import build_export_preview

    payload = build_export_preview(_privacy_input(text, file), source="privacy_cli")
    console.print(json.dumps(payload, ensure_ascii=False, indent=2), markup=False, highlight=False)


@policy_app.command("show")
def policy_show() -> None:
    """Visa aktiv policy (lokal om giltig, annars default). Locked regler markeras."""
    from .policy.loader import load_policy

    policy = load_policy()
    console.print(f"[bold]policy[/bold] · version {policy.version}")
    for r in policy.rules:
        lock = " [locked]" if r.locked else ""
        console.print(f"  ({r.scope}) {r.id}{lock}: {r.text}")
    if policy.forbidden_core_paths:
        console.print("[dim]forbidden_core_paths:[/dim]")
        for p in policy.forbidden_core_paths:
            console.print(f"  - {p}")


@policy_app.command("validate")
def policy_validate(
    path: Path | None = typer.Option(
        None, "--file", "-f", help="Validera en specifik policyfil (annars aktiv policy)."
    ),
) -> None:
    """Validera policystruktur + locked-regler. Utan --file valideras aktiv policy."""
    from .policy.defaults import default_policy
    from .policy.loader import load_file, load_policy, validate

    if path is None:
        errors = validate(load_policy())
        target = "aktiv policy"
    else:
        policy, errors = load_file(path)
        if policy is None:
            console.print(f"[red]{path}: ogiltig[/red]")
            for e in errors:
                console.print(f"  - {e}")
            raise typer.Exit(1)
        errors = validate(policy, baseline=default_policy())
        target = str(path)

    if errors:
        console.print(f"[red]{target}: OGILTIG[/red]")
        for e in errors:
            console.print(f"  - {e}")
        raise typer.Exit(1)
    console.print(f"[green]{target}: giltig[/green]")


if __name__ == "__main__":
    app()


@learning_app.command("inspect")
def learning_inspect() -> None:
    """Visa lokala gap-events (prestation om Hund)."""
    from .learning.observer import list_gap_events

    rows = list_gap_events()
    if not rows:
        console.print("(inga gap-events ännu)")
        return
    for gid, created, domain, symptom, status in rows:
        console.print(f"[{status}] {created} {domain} ({gid}) — {symptom[:70]}")


@learning_app.command("gap")
def learning_gap(
    symptom: str = typer.Argument(..., help="Vad Hund missade/felade i."),
    domain: str = typer.Option("unknown", "--domain", "-d"),
) -> None:
    """Logga ett gap-event manuellt (lokal prestation, ej användardata)."""
    from .learning.observer import add_gap_event

    gid = add_gap_event(symptom, domain)
    console.print(f"[green]gap loggat[/green] {gid[:8]} · {domain}")


@learning_app.command("close")
def learning_close(gid_prefix: str = typer.Argument(..., help="id-prefix")) -> None:
    """Stäng ett gap-event."""
    from .learning.observer import set_gap_status

    n = set_gap_status(gid_prefix, "closed")
    console.print(f"stängde {n} gap." if n else "[yellow]inget gap matchade[/yellow]")


@learning_app.command("study")
def learning_study(
    gid_prefix: str = typer.Argument(..., help="gap-id-prefix att studera"),
    rule: str = typer.Option(..., "--rule", "-r", help="Destillerad regel från studien."),
    trigger: str = typer.Option("", "--trigger", "-t"),
) -> None:
    """Studera ett gap → destillera till en knowledge unit (lokal mastery)."""
    from .knowledge import store as kstore
    from .learning.observer import list_gap_events

    gaps = list_gap_events()
    match = next((g for g in gaps if g[0].startswith(gid_prefix)), None)
    if not match:
        console.print("[yellow]inget gap matchade prefix[/yellow]")
        return
    domain = match[2] or "general"
    trig = trigger or (match[3][:30])
    uid = kstore.add(domain=domain, trigger=trig, rule=rule, source="study")
    console.print(f"[green]knowledge unit skapad[/green] {uid[:8]} · {domain}")
    console.print(f"[dim]regel: {rule}[/dim]")


# ---- stats ----
@stats_app.callback(invoke_without_command=True)
def stats_default(ctx: typer.Context) -> None:
    """Token/latency-sammanställning."""
    from .store.sqlite import connect

    conn = connect()
    row = conn.execute(
        """SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0),
                  COALESCE(SUM(completion_tokens),0), COALESCE(SUM(latency_ms),0)
           FROM requests"""
    ).fetchone()
    conn.close()
    n, tin, tout, lat = row
    console.print(
        f"[bold]stats[/bold] · requests: {n} · tokens in/out: {tin}/{tout} · "
        f"total latency: {lat}ms"
    )


@stats_app.command("base")
def stats_base() -> None:
    """3 base stats (råa ur loggen, inga fejkade %)."""
    from .base_stats import compute

    s = compute()
    console.print("[bold]Hund base stats[/bold]")
    for k, v in s.items():
        name = k.replace("_", " ").title()
        val = next((x for x in v.values() if x is not None), "n/a")
        console.print(f"  {name:20} ({v['level']})  {val}")


# ---- proposals ----
@proposals_app.command("list")
def proposals_list(
    status: str = typer.Option(None, "--status", "-s"),
) -> None:
    """Lista proposals."""
    from .selfimprovement import proposal as P

    props = P.list_proposals(status)
    if not props:
        console.print("(inga proposals)")
        return
    for p in props:
        console.print(f"[{p.status}] {p.id[:8]} ({p.change_type}) {p.title}")


@proposals_app.command("show")
def proposals_show(pid: str = typer.Argument(..., help="id-prefix")) -> None:
    """Visa en proposal."""
    from .selfimprovement import proposal as P

    p = P.get(pid)
    if not p:
        console.print("[yellow]ingen proposal matchade[/yellow]")
        return
    console.print(p.as_markdown())


@proposals_app.command("approve")
def proposals_approve(pid: str = typer.Argument(...)) -> None:
    """Mänsklig gate: godkänn en proposal (markerar, applicerar ej auto)."""
    from .selfimprovement import proposal as P

    n = P.set_status(pid, "approved")
    console.print(f"[green]godkänd[/green] {n} proposal." if n else "[yellow]ingen match[/yellow]")
    console.print("[dim]observera: Hund applicerar ALDRIG auto. Ändra filer manuellt.[/dim]")


@proposals_app.command("reject")
def proposals_reject(pid: str = typer.Argument(...)) -> None:
    from .selfimprovement import proposal as P

    n = P.set_status(pid, "rejected")
    console.print(f"avvisad {n} proposal." if n else "[yellow]ingen match[/yellow]")


# ---- knowledge ----
@knowledge_app.command("add")
def knowledge_add(
    rule: str = typer.Option(..., "--rule", "-r"),
    domain: str = typer.Option("general", "--domain", "-d"),
    trigger: str = typer.Option("", "--trigger", "-t"),
) -> None:
    """Lägg till en knowledge unit manuellt."""
    from .knowledge import store as kstore

    uid = kstore.add(domain=domain, trigger=trigger or rule[:30], rule=rule)
    console.print(f"[green]unit skapad[/green] {uid[:8]} · {domain}")


@knowledge_app.command("list")
def knowledge_list(
    domain: str = typer.Option(None, "--domain", "-d"),
) -> None:
    """Lista knowledge units (LFU-ordning)."""
    from .knowledge import store as kstore

    rows = kstore.list_units(domain)
    if not rows:
        console.print("(inga knowledge units — lägg till med `hund knowledge add`)")
        return
    for uid, dom, trig, rule, freq, succ in rows:
        console.print(f"{uid} [{dom}] freq={freq} ok={succ} ({trig}) {rule[:50]}")

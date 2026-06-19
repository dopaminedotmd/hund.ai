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


# ── Sub-apps ────────────────────────────────────────────────────────────────
learning_app = typer.Typer(help="Lokal learning/gap-events. Aldrig extern upload.")
proposals_app = typer.Typer(help="Self-improvement proposals (deklarativa, human-gated).")
knowledge_app = typer.Typer(help="Kunskapsenheter (LFU/MRU).")
stats_app = typer.Typer(help="Statistik och base stats.")
privacy_app = typer.Typer(help="Privacy/redaction. Offline, ingen upload.")
policy_app = typer.Typer(help="Runtime policy (deklarativ, ej core-kod).")
skills_app = typer.Typer(help="Deklarativa skills (inte exekverbar kod).")
domains_app = typer.Typer(help="Domain detection (grovt, offline).")
eval_app = typer.Typer(help="Eval/benchmark/regression (bevisbarhet).")
memory_app = typer.Typer(help="Persistent användarminne (user.md + environment.md).")
sessions_app = typer.Typer(help="Sessionsarkiv + fulltext-sök.")
app.add_typer(learning_app, name="learning")
app.add_typer(proposals_app, name="proposals")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(stats_app, name="stats")
app.add_typer(privacy_app, name="privacy")
app.add_typer(policy_app, name="policy")
app.add_typer(skills_app, name="skills")
app.add_typer(domains_app, name="domains")
app.add_typer(eval_app, name="eval")
app.add_typer(memory_app, name="memory")
app.add_typer(sessions_app, name="sessions")


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
        console.print(app.get_help(ctx))
        raise typer.Exit()


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
    """Konfigurera provider och visa instruktioner för HUND_API_KEY."""
    from .config import HundConfig
    from .secrets import load_api_key

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
        console.print(
            "[yellow]Sätt API-nyckeln i din miljövariabel: HUND_API_KEY[/yellow]"
        )
    else:
        console.print(
            f"nuvarande nyckel i HUND_API_KEY: {'finns' if load_api_key() else '[red]saknas[/red]'}"
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
        '"risk" (low|medium|high),"tests_needed","rollback_note". '
        "change_type får ALDRIG vara core/engine/safety/updater — de är TCB. "
        "Om change_type=skill, inkludera DESSUTOM fält för att bygga en "
        "oföränderlig, deklarativ skill-fil: "
        '"skill_name" (kebab-case), "skill_domain", "skill_triggers" (lista), '
        '"skill_steps" (lista), "skill_forbidden" (lista — OBLIGATORISK, t.ex. '
        '["delete","push","modify_tcb"]), "skill_verification" (lista — '
        'OBLIGATORISK, hur man bekräftar att skillen verkligen applicerades), '
        'valfritt "skill_required_tools" och "skill_when_to_use". '
        "En skill utan forbidden_actions och verification är OGILTIG."
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


@app.command()
def migrate(
    from_version: str = typer.Option(
        "v1", "--from", help="Källversion (v1 = monolit hund.db). Idempotent."
    ),
) -> None:
    """Migrera v1 → v2: monolit hund.db → brain/ + logs/ struktur.

    Flyttar knowledge_units (SQLite→JSON), skills/, policy.json till brain/, och
    requests/tool_events till logs/. Idempotent — säker att köra flera gånger.
    """
    from .knowledge.migrate import migrate as run_migrate

    report = run_migrate()
    console.print("[bold]hund migrate[/bold] — v1 → v2")
    if not report["migrated"]:
        console.print("[dim]ingen gammal hund.db hittades — brain/-struktur säkerställd.[/dim]")
    console.print(
        f"  knowledge: {report['domains']} domäner, {report['units']} units (merge per id)"
    )
    console.print(f"  skills flyttade: {report['skills']}")
    console.print(f"  policy flyttad: {'ja' if report['policy'] else 'nej'}")
    console.print(f"  logs: {report['requests']} requests, {report['tool_events']} tool_events")
    if report["backup"]:
        console.print(f"  [dim]backup: {report['backup']}[/dim]")
    console.print("[green]migrering klar.[/green]")


# ---- memory (fas 9.5 Del A) ----
@memory_app.command("show")
def memory_show() -> None:
    """Visa allt persistent minne (user.md + environment.md)."""
    from . import memory as M

    M.ensure_seed()
    console.print(M.show(), markup=True, highlight=False)


@memory_app.command("update")
def memory_update(
    name: str = typer.Argument("user", help="vilket minne (endast 'user' stöds)."),
) -> None:
    """Interaktiv uppdatering av user.md (en bullet per rad, tom rad avslutar)."""
    from . import memory as M

    if name != "user":
        console.print(f"[red]okänt minne '{name}'[/red] (endast 'user' stöds)")
        raise typer.Exit(1)
    M.ensure_seed()
    console.print("[bold]nuvarande user.md-bullets:[/bold]")
    for b in M.user_bullets():
        console.print(f"  - {b}", markup=False)
    console.print("[dim]nya bullets, en per rad. tom rad avslutar.[/dim]")
    lines: list[str] = []
    while True:
        try:
            line = console.input("[bold]bullet>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        clean = line[2:].strip() if line.startswith("- ") else line
        if clean:
            lines.append(clean)
    text = "\n".join(f"- {l}" for l in lines)
    p = M.update_user(text)
    console.print(f"[green]sparat:[/green] {p} ({len(lines)} bullets)")


@memory_app.command("refresh-env")
def memory_refresh_env() -> None:
    """Kör doctor → skriv/overskriv environment.md (hårdvarusnapshot)."""
    from . import memory as M
    from .doctor import profile_environment

    profile = profile_environment()
    p = M.refresh_env(profile, force=True)
    console.print(f"[green]environment.md uppdaterad:[/green] {p}")


# ---- sessions (fas 9.5 Del B) ----
@sessions_app.command("list")
def sessions_list(
    limit: int = typer.Option(10, "--limit", "-n", help="antal sessioner"),
) -> None:
    """Senaste sessioner."""
    from .agent import sessions as S

    rows = S.list_sessions(limit=limit)
    if not rows:
        console.print("(inga sessioner ännu)")
        return
    for sid, created, title, count, act in rows:
        mark = "*" if act else " "
        console.print(f"{mark} #{sid[:8]} ({count} msg) {title[:40]} — {created}", markup=False)


@sessions_app.command("show")
def sessions_show(
    sid: str = typer.Argument(..., help="session-id (prefix OK)"),
) -> None:
    """Visa metadata + meddelandecount för en session."""
    from .agent import sessions as S

    info = S.info(sid)
    if not info:
        console.print(f"[yellow]ingen session '{sid}'[/yellow]")
        raise typer.Exit(1)
    console.print(f"[bold]#{info['id'][:8]}[/bold] {'(aktiv)' if info['active'] else ''}")
    console.print(f"title: {info['title'] or '(ingen)'}", markup=False)
    console.print(f"skapad: {info['created_at']}", markup=False)
    console.print(f"meddelanden: {info['message_count']}")


@sessions_app.command("search")
def sessions_search(
    q: str = typer.Argument(..., help="fulltext-sökterm"),
) -> None:
    """Fulltext-sök över alla sessionsmeddelanden (FTS5)."""
    from .agent import sessions as S

    rows = S.search(q)
    if not rows:
        console.print(f"(inga träffar för '{q}')")
        return
    for session_id, role, snip, created in rows:
        console.print(f"#{session_id[:8]} [{role}] {snip} — {created}", markup=False)


@sessions_app.command("delete")
def sessions_delete(
    sid: str = typer.Argument(..., help="session-id (prefix OK)"),
) -> None:
    """Radera en session + dess meddelanden."""
    from .agent import sessions as S

    n = S.delete(sid)
    console.print(f"[green]raderade[/green] {n} session." if n else "[yellow]ingen match[/yellow]")


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


# ---- skills ----
@skills_app.command("list")
def skills_list() -> None:
    """Lista giltiga skills (builtins + HundHome)."""
    from .skills.loader import load_skills

    skills = load_skills()
    if not skills:
        console.print("(inga skills)")
        return
    for s in skills:
        console.print(f"[bold]{s.status}[/bold] {s.name} ({s.domain}) — {s.when_to_use[:60]}")


@skills_app.command("show")
def skills_show(name: str = typer.Argument(..., help="skill-namn")) -> None:
    """Visa en skill."""
    from .skills.loader import get_skill

    s = get_skill(name)
    if not s:
        console.print(f"[yellow]ingen skill '{name}'[/yellow]")
        raise typer.Exit(1)
    console.print(f"[bold]{s.name}[/bold] ({s.domain}) [{s.status}]")
    console.print(f"safety: {s.safety_level}")
    console.print(f"when: {s.when_to_use}")
    console.print(f"triggers: {', '.join(s.triggers)}")
    console.print("steps:")
    for st in s.steps:
        console.print(f"  - {st}")
    console.print(f"forbidden: {', '.join(s.forbidden_actions)}")
    console.print(f"verification: {', '.join(s.verification)}")


@skills_app.command("validate")
def skills_validate(
    path: Path = typer.Argument(..., help="sökväg till skill-JSON"),
) -> None:
    """Validera en skill-fil innan add."""
    from .skills.loader import load_file

    skill, errors = load_file(path)
    if errors:
        console.print(f"[red]{path}: OGILTIG[/red]")
        for e in errors:
            console.print(f"  - {e}")
        raise typer.Exit(1)
    console.print(f"[green]{path}: giltig[/green] ({skill.name})")


@skills_app.command("add")
def skills_add(
    path: Path = typer.Argument(..., help="sökväg till skill-JSON att lägga till"),
) -> None:
    """Validera + kopiera en skill till brain/skills/."""
    from .skills.loader import add_skill

    skill, errors = add_skill(path)
    if errors:
        console.print(f"[red]{path}: OGILTIG[/red]")
        for e in errors:
            console.print(f"  - {e}")
        raise typer.Exit(1)
    console.print(f"[green]skill tillagd[/green] {skill.name}")


@skills_app.command("match")
def skills_match(
    text: str = typer.Argument(..., help="uppgiftstext att matcha mot"),
) -> None:
    """Matcha uppgiftstext mot aktiva skills (max top 3)."""
    from .skills.loader import load_skills
    from .skills.matcher import match

    hits = match(load_skills(), text)
    if not hits:
        console.print("(inga skill-träffar)")
        return
    for s in hits:
        console.print(f"- {s.summary()}", markup=False)


# ---- domains ----
@domains_app.command("detect")
def domains_detect(
    domain: str = typer.Option(None, "--domain", "-d", help="manuell domain-override"),
) -> None:
    """Detektera domän från current workspace (offline)."""
    from pathlib import Path

    from .domains import detector as ddet

    workspace = Path.cwd()
    det = ddet.detect(workspace, manual=domain)
    ddet.record_detection(det)
    console.print(f"[bold]primary:[/bold] {det.primary} ({det.primary_confidence})")
    for cand in det.candidates:
        console.print(f"  candidate: {cand}")


@domains_app.command("list")
def domains_list() -> None:
    """Visa kända domäner + status."""
    from .domains import detector as ddet

    rows = ddet.list_domains()
    if not rows:
        console.print("(inga domäner detekterade — kör `hund domains detect`)")
        return
    for domain, status, confidence, detected_at in rows:
        console.print(f"[bold]{status}[/bold] {domain} ({confidence}) — {detected_at}")


@domains_app.command("set-primary")
def domains_set_primary(
    domain: str = typer.Argument(..., help="domain att göra primär"),
) -> None:
    """Sätt primary domain manuellt (styr knowledge top-K)."""
    from .domains import detector as ddet

    ddet.set_primary(domain)
    console.print(f"[green]primary satt:[/green] {domain}")


# ---- eval ----
@eval_app.command("run")
def eval_run(
    gap_on_fail: bool = typer.Option(
        False, "--gap-on-fail", help="Logga lokala gap-events för misslyckade evals."
    ),
) -> None:
    """Kör alla eval-cases (deterministiska, offline)."""
    from .evals.runner import run_all
    from .learning.observer import add_gap_event

    results = run_all()
    passed = sum(1 for r in results if r.passed)
    for r in results:
        mark = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        console.print(f"  {mark} {r.name} — {r.detail}")
    console.print(f"\n[bold]{passed}/{len(results)} passed[/bold]")
    if gap_on_fail:
        for r in results:
            if not r.passed:
                add_gap_event(f"eval {r.name}: {r.detail}", domain="eval")
        console.print("[dim]misslyckade evals loggade som gap-events[/dim]")
    if passed < len(results):
        raise typer.Exit(1)


@eval_app.command("list")
def eval_list() -> None:
    """Lista tillgängliga eval-cases."""
    from .evals.runner import list_cases

    for name in list_cases():
        console.print(f"- {name}")


@eval_app.command("add-regression")
def eval_add_regression(
    name: str = typer.Argument(..., help="case-namn"),
    subject: str = typer.Option("$pyproject", "--subject", "-s",
                                help="$pyproject | $file:<path> | <text>"),
    contains: str = typer.Option("", "--contains", "-c",
                                 help="komma-separerade strängar som måste finnas"),
    not_contains: str = typer.Option("", "--not-contains", "-n",
                                     help="komma-separerade strängar som inte får finnas"),
) -> None:
    """Lägg till ett text-assert regression-case lokalt."""
    from .evals.runner import add_regression

    target = add_regression(
        name,
        subject,
        contains=[s.strip() for s in contains.split(",") if s.strip()],
        not_contains=[s.strip() for s in not_contains.split(",") if s.strip()],
    )
    console.print(f"[green]regression case skapat[/green] {target}")


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
    from .store.sqlite import connect_requests

    conn = connect_requests()
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
def proposals_approve(
    pid: str = typer.Argument(..., help="id-prefix"),
    apply: bool = typer.Option(
        False, "--apply", "-a",
        help="Applicera skill-förslag automatiskt (skapar skill-fil i brain/skills/)",
    ),
) -> None:
    """Mänsklig gate: godkänn en proposal.

    Utan --apply: markerar bara "approved" (applicerar ingenting).
    Med --apply + change_type=skill: bygger + validerar + skriver skill-fil,
    sätter status "applied". Stänger self-improvement-loopen.
    """
    import json as _json

    from .selfimprovement import proposal as P

    p = P.get(pid)
    if not p:
        console.print("[yellow]ingen proposal matchade[/yellow]")
        return

    if apply:
        if p.change_type != "skill":
            console.print(
                f"[yellow]--apply stöds endast för change_type=skill "
                f"(denna är {p.change_type}). Applicera manuellt.[/yellow]"
            )
            return
        try:
            raw = _json.loads(p.raw_summary) if p.raw_summary else {}
        except _json.JSONDecodeError:
            console.print("[red]raw_summary korrupt — kan ej bygga skill.[/red]")
            return
        ok, msg = P.apply_skill_proposal(p, raw)
        if ok:
            P.set_status(p.id[:8], "applied")
            console.print(f"[green]skill skapad + applicerad:[/green] {msg}")
            console.print("[dim]lista: `hund skills list` · visa: `hund skills show <namn>`[/dim]")
        else:
            console.print(f"[red]kunde ej applicera:[/red] {msg}")
        return

    # default: markera bara approved (ursprungligt beteende)
    n = P.set_status(pid, "approved")
    console.print(f"[green]godkänd[/green] {n} proposal." if n else "[yellow]ingen match[/yellow]")
    console.print("[dim]applicera med: hund proposals approve <id> --apply[/dim]")


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

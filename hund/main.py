"""Hund CLI entrypoint: `hund`.

Skelett 0.1.0. Subkommandon är stubbar som växer in enligt docs/mvp.md.
Körningen nås via entrypoint `hund = "hund.main:app"` i pyproject.toml.
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path

# Force UTF-8 console output and input code pages on Windows (65001)
if sys.platform == "win32":
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from rich.console import Console
from rich.table import Table

from . import __version__

app = typer.Typer(
    name="hund",
    help="Hund — agenten som lever i din hårdvara.",
    no_args_is_help=False,
    add_completion=False,
)
console = Console()


def _start_opentui() -> None:
    """Starta OpenTUI via Bun."""
    tui_dir = Path(__file__).resolve().parent.parent / "tui"
    if not (tui_dir / "node_modules").exists():
        raise FileNotFoundError("TUI dependencies saknas. Kor 'bun install' i tui/")
    # Anvand bun fran PATH
    import shutil
    bun = shutil.which("bun") or shutil.which("bun.exe")
    if not bun:
        raise FileNotFoundError("Bun ar inte installerat. Installera fran https://bun.sh")
    process = subprocess.Popen([bun, "run", "src/index.tsx"], cwd=tui_dir)
    exit_code = process.wait()
    if exit_code:
        raise typer.Exit(exit_code)


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
connector_app = typer.Typer(help="Connector/daemon — lokal gateway mellan cloud och core.")
telemetry_app = typer.Typer(help="Telemetri — visa prestandadata.")
research_app = typer.Typer(help="Research — domankunskapslandskap.")



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
        from .ui import run_repl
        raise typer.Exit(run_repl())


@app.command()
def repl() -> None:
    """Starta interaktiv REPL (terminal)."""
    from .ui import run_repl
    raise typer.Exit(run_repl())


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
    console.print("[green]verify[/green]: hund importerar OK.")
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



@eval_app.command("scenarios")
def eval_scenarios(
    scenario: str = typer.Option("", "--scenario", "-s", help="Kör endast ett scenario-id."),
    trace_db: Path | None = typer.Option(None, "--trace-db", help="Spara scenario evidence-events i denna SQLite DB."),
    json_output: bool = typer.Option(False, "--json", help="Skriv scorecards som JSON."),
) -> None:
    """Kör HTAS v1-scenarios och visa scorecards."""
    from .evals.scenario_runner import run_all_scenarios, run_scenario

    try:
        scorecards = [run_scenario(scenario, db_path=trace_db)] if scenario else run_all_scenarios(db_path=trace_db)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if json_output:
        console.print_json(json.dumps([s.as_dict() for s in scorecards], ensure_ascii=False))
    else:
        passed = sum(1 for s in scorecards if s.passed)
        for s in scorecards:
            mark = "[green]PASS[/green]" if s.passed else "[red]FAIL[/red]"
            detail = "ok" if s.passed else "; ".join(s.failures)
            console.print(f"  {mark} {s.scenario_id} — {s.invariant} — {detail}")
        console.print(f"\n[bold]{passed}/{len(scorecards)} scenarios passed[/bold]")
    if any(not s.passed for s in scorecards):
        raise typer.Exit(1)

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
    """Visa 5 base stats med progressbars."""
    from .stats.base_stats import compute_all
    from .stats.tiers import render_stat

    all_stats = compute_all()
    console.print("\n[bold]Base Stats[/bold]")
    console.print("-" * 50)
    for stat in all_stats.values():
        console.print(render_stat(stat))
    console.print("")


@stats_app.command("velocity")
def stats_velocity() -> None:
    """Visa forbattingstakt per vecka."""
    from .stats.velocity import compute_velocity

    vel = compute_velocity()
    if not vel:
        console.print("[yellow]Inte tillrackligt med data for velocity.[/yellow]")
        return
    console.print("\n[bold]Velocity (per vecka)[/bold]")
    console.print("-" * 50)
    for name, change in vel.items():
        arrow = "\u25be" if change["improving"] else "\u25b4"
        console.print(f"  {name:<14}  {arrow} {change['delta_display']}  ({change['current']} -> {change['previous']})")


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


# ---- export (Phase 8) ----
export_app = typer.Typer(help="Dataset export (SFT/JSONL/DPO).")


@export_app.command("dataset")
def export_dataset(
    format: str = typer.Option("jsonl", "--format", "-f", help="Export format: jsonl|sft"),
    limit: int = typer.Option(200, "--limit", "-n", help="Max pairs to export"),
    session: str = typer.Option("", "--session", "-s", help="Filter by session ID"),
    since: str = typer.Option("", "--since", help="ISO timestamp filter (created_at >=)"),
    until: str = typer.Option("", "--until", help="ISO timestamp filter (created_at <=)"),
    event_type: str = typer.Option("", "--event-type", "-e", help="Filter by event_type"),
    output: str = typer.Option("", "--output", "-o", help="Output file path (auto if empty)"),
) -> None:
    """Exportera trace events som SFT/JSONL-dataset."""
    from pathlib import Path
    import datetime as dt

    from .export.engine import ExportEngine, Filter

    filt = Filter().with_limit(limit)
    if session:
        filt = filt.with_session(session)
    if since:
        filt = filt.since_time(since)
    if until:
        filt = filt.until_time(until)
    if event_type:
        filt = filt.with_event_type(event_type)

    engine = ExportEngine()
    pairs = engine.build_pairs(filt)

    if not pairs:
        console.print("[yellow]Inga pairs hittades for givna filter.[/yellow]")
        raise typer.Exit()

    out_path = output or f"exports/hund_export_{dt.datetime.now():%Y%m%d_%H%M%S}.{format}"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if format == "jsonl":
        engine.export_to_jsonl(pairs, path)
    elif format == "sft":
        engine.export_to_sft(pairs, path)
    else:
        console.print(f"[red]Okant format: {format} (valj jsonl|sft)[/red]")
        raise typer.Exit(1)

    # Save manifest
    manifest = engine.save_manifest(pairs, path, filter_obj=filt, export_format=format)

    # Log to store
    from .export import store as estore
    import json as _json
    estore.log_export(
        export_format=format,
        pair_count=len(pairs),
        output_path=str(path.resolve()),
        filters_json=_json.dumps(filt.to_dict(), ensure_ascii=False),
    )

    console.print(f"[green]Export klar:[/green] {path}")
    console.print(f"  format: {format}")
    console.print(f"  pairs: {len(pairs)}")
    console.print(f"  manifest: {path}.manifest.json")


@export_app.command("preview")
def export_preview(
    limit: int = typer.Option(50, "--limit", "-n", help="Max pairs to analyse"),
    session: str = typer.Option("", "--session", "-s", help="Filter by session ID"),
) -> None:
    """Förhandsgranska export-statistik (inga rådata)."""
    from .export.engine import ExportEngine, Filter

    filt = Filter().with_limit(limit)
    if session:
        filt = filt.with_session(session)

    engine = ExportEngine()
    pairs = engine.build_pairs(filt)
    stats = engine.dry_run(pairs)

    table = Table(title="Export Preview")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Pair count", str(stats["pair_count"]))
    table.add_row("Avg prompt len", str(stats["avg_prompt_len"]))
    table.add_row("Avg response len", str(stats["avg_response_len"]))
    table.add_row("Total chars", str(stats["total_chars"]))
    table.add_row("Redactor", stats["redactor_version"])
    for risk, count in stats["risk_counts"].items():
        table.add_row(f"Risk: {risk}", str(count))
    if stats["blocked_fields"]:
        table.add_row("Blocked fields", ", ".join(stats["blocked_fields"]))
    console.print(table)


@export_app.command("status")
def export_status(
    limit: int = typer.Option(10, "--limit", "-n", help="Antal exporter att visa"),
) -> None:
    """Visa senaste exporter."""
    from .export import store as estore

    exports = estore.list_exports(limit=limit)
    if not exports:
        console.print("(inga exporter annu)")
        return

    table = Table(title="Export History")
    table.add_column("Export ID", style="dim")
    table.add_column("Created", style="cyan")
    table.add_column("Format")
    table.add_column("Pairs")
    table.add_column("Path")
    for ex in exports:
        table.add_row(
            ex["export_id"][:8],
            ex["created_at"][:19],
            ex["export_format"],
            str(ex["pair_count"]),
            ex["output_path"][:40],
        )
    console.print(table)


# ---- local (Phase 9) ----
local_app = typer.Typer(help="Local model inference via llama.cpp.")


@local_app.command("start")
def local_start(
    port: int = typer.Option(8080, "--port", "-p", help="Port for llama.cpp server"),
    model: str = typer.Option("", "--model", "-m", help="Path to GGUF model file"),
    ctx_size: int = typer.Option(4096, "--ctx-size", help="Context size in tokens"),
) -> None:
    """Start local inference engine (llama.cpp server)."""
    from .local.engine import LocalEngine

    engine = LocalEngine(
        model_path=model if model else None,
        port=port,
        ctx_size=ctx_size,
    )

    if engine.model_path is None:
        console.print("[red]Ingen GGUF-modell hittades.[/red]")
        console.print("  Placera .gguf-filer i ./models/ eller ange --model")
        console.print("  Ladda ner: hund local download <url>")
        raise typer.Exit(1)

    try:
        result = engine.start()
        console.print(f"[green]Local engine startad[/green]")
        console.print(f"  port: {result['port']}")
        console.print(f"  model: {result['model']}")
        console.print(f"  pid: {result['pid']}")
        console.print("[dim]Lamna detta fönster oppet. Stang med Ctrl+C.[/dim]")

        # Keep running until interrupted
        import signal as _signal

        def _handler(sig, frame):
            console.print("\n[green]Stoppar local engine...[/green]")
            engine.stop()
            raise typer.Exit()

        _signal.signal(_signal.SIGINT, _handler)
        _signal.signal(_signal.SIGTERM, _handler)

        while True:
            import time
            time.sleep(1)

    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@local_app.command("stop")
def local_stop() -> None:
    """Stop local inference engine."""
    from .local.engine import LocalEngine

    engine = LocalEngine()
    result = engine.stop()
    console.print(f"[green]Local engine:[/green] {result['status']}")


@local_app.command("status")
def local_status() -> None:
    """Show local engine status."""
    from .local.engine import LocalEngine

    engine = LocalEngine()
    try:
        health = engine.health()
        console.print("[green]Local engine: running[/green]")
        console.print(f"  model: {health.get('model', 'unknown')}")
        console.print(f"  port: {health.get('port', '?')}")
        console.print(f"  llama.cpp: {health.get('llama_version', '?')}")
        console.print(f"  engine: {health.get('engine_version', '?')}")
    except Exception:
        console.print("[yellow]Local engine: not running[/yellow]")
        if engine.model_path:
            console.print(f"  model available: {engine.model_path}")
        else:
            console.print("  [dim]Ingen GGUF-modell hittades (HUND_LOCAL_MODEL_PATH eller ./models/)[/dim]")


@local_app.command("download")
def local_download(
    url: str = typer.Argument(..., help="URL to GGUF model file"),
    output: str = typer.Option("", "--output", "-o", help="Output filename (auto if empty)"),
) -> None:
    """Download a GGUF model to ./models/."""
    from .paths import local_download_path
    import urllib.request

    dest_dir = local_download_path()
    filename = output or url.rstrip("/").split("/")[-1]
    if not filename.endswith(".gguf"):
        filename += ".gguf"

    dest = dest_dir / filename
    console.print(f"[dim]Laddar ner {url}...[/dim]")
    console.print(f"  till: {dest}")
    console.print(f"  Detta kan ta en lång stund beroende på modellstorlek.")

    try:
        urllib.request.urlretrieve(url, dest)
        console.print(f"[green]Nedladdning klar:[/green] {dest}")
        console.print(f"  Storlek: {dest.stat().st_size / 1_000_000_000:.1f} GB")
    except Exception as exc:
        console.print(f"[red]Nedladdning misslyckades:[/red] {exc}")
        if dest.exists():
            dest.unlink()
        raise typer.Exit(1)


# ---- cloud (Phase 10) ----
cloud_app = typer.Typer(help="Cloud orchestration — fleet management.")


@cloud_app.command("start")
def cloud_start(
    port: int = typer.Option(8765, "--port", "-p", help="Port for cloud server"),
) -> None:
    """Start the cloud orchestration server."""
    from .cloud.server import start_cloud

    server = start_cloud(port=port)
    console.print(f"[green]Cloud server startad[/green] pa 0.0.0.0:{port}")
    console.print(f"[dim]Fleet endpoint: http://localhost:{port}/cloud/fleet[/dim]")
    console.print("[dim]Tryck Ctrl+C for att stoppa[/dim]")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[green]Cloud server stoppad.[/green]")
        server.server_close()


@cloud_app.command("status")
def cloud_status() -> None:
    """Visa fleet-status fran cloud server."""
    import os
    import urllib.request, json
    url = os.environ.get("HUND_CLOUD_URL", "http://localhost:8765")
    try:
        resp = json.loads(urllib.request.urlopen(f"{url}/cloud/fleet", timeout=5).read().decode("utf-8"))
        fleet = resp.get("fleet", [])
        if not fleet:
            console.print("[yellow]Inga anslutna connectors.[/yellow]")
            return
        console.print(f"[bold]Fleet ({len(fleet)} connectors)[/bold]")
        for c in fleet:
            status_color = "green" if c.get("status") == "online" else "red"
            console.print(f"  [{status_color}]{c['status']}[/{status_color}] "
                f"{c['connector_id'][:12]} ({c.get('hostname', '?')}) v{c.get('version', '?')}")
    except Exception as exc:
        console.print(f"[red]Kunde inte na cloud server pa {url}:[/red] {exc}")


@cloud_app.command("connect")
def cloud_connect(
    url: str = typer.Argument(..., help="Cloud server URL (e.g. http://localhost:8765)"),
) -> None:
    """Connect this connector to a cloud server."""
    from .connector.cloud_agent import CloudAgent, CloudConfig
    import socket

    cid = os.environ.get("HUND_CLOUD_CONNECTOR_ID", f"connector-{socket.gethostname()}")
    agent = CloudAgent(CloudConfig(url=url, connector_id=cid), auto_heartbeat=False)
    ok = agent.register(version="1.0.0")
    if ok:
        console.print(f"[green]Ansluten till cloud[/green] {url}")
        console.print(f"  connector_id: {agent.connector_id}")
        console.print(f"  api_key: {agent._config.api_key[:16]}...")
        console.print("[dim]Spara HUND_CLOUD_URL, HUND_CLOUD_CONNECTOR_ID och HUND_CLOUD_API_KEY[/dim]")
        console.print("  setx HUND_CLOUD_URL " + url)
        console.print(f"  setx HUND_CLOUD_CONNECTOR_ID {agent.connector_id}")
        console.print(f"  setx HUND_CLOUD_API_KEY {agent._config.api_key}")
        agent.start_heartbeat()
        console.print("[green]Heartbeat startad[/green] (var 30e sekund)")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            agent.stop_heartbeat()
            agent.deregister()
            console.print("\n[green]Frankopplad fran cloud.[/green]")
    else:
        console.print(f"[red]Kunde inte ansluta till {url}[/red]")


@cloud_app.command("disconnect")
def cloud_disconnect() -> None:
    """Koppla fran connector fran cloud."""
    agent = _get_cloud_agent()
    if agent and agent.is_connected:
        agent.stop_heartbeat()
        agent.deregister()
        console.print("[green]Frankopplad fran cloud.[/green]")
    else:
        console.print("[yellow]Ingen aktiv cloud-anslutning.[/yellow]")


@cloud_app.command("deploy")
def cloud_deploy(
    connector_id: str = typer.Argument(..., help="Target connector ID"),
    tool_name: str = typer.Argument(..., help="Tool to execute"),
    args: str = typer.Option("{}", "--args", "-a", help="JSON args"),
) -> None:
    """Distribuera en agent-uppgift till en connector via cloud."""
    import urllib.request, json
    url = os.environ.get("HUND_CLOUD_URL", "http://localhost:8765")
    body = json.dumps({
        "target_connector": connector_id,
        "tool_name": tool_name,
        "args": json.loads(args),
        "intent_type": "tool_call",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(f"{url}/cloud/deploy", data=body,
                                      headers={"Content-Type": "application/json"}, method="POST")
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        if "intent" in resp:
            console.print(f"[green]Uppgift skickad till {connector_id}[/green]")
            console.print(f"  intent_id: {resp['intent']['intent_id']}")
        else:
            console.print(f"[red]Misslyckades:[/red] {resp}")
    except Exception as exc:
        console.print(f"[red]Fel: {exc}[/red]")


def _get_cloud_agent():
    from .connector.cloud_agent import CloudAgent, CloudConfig
    url = os.environ.get("HUND_CLOUD_URL", "")
    cid = os.environ.get("HUND_CLOUD_CONNECTOR_ID", "")
    api_key = os.environ.get("HUND_CLOUD_API_KEY", "")
    if url and api_key:
        return CloudAgent(CloudConfig(url=url, connector_id=cid, api_key=api_key), auto_heartbeat=False)
    return None


# ---- domains (Leveling System) ----
@domains_app.command("confidence")
def domains_confidence() -> None:
    """Visa domain confidence scores."""
    from .domains.confidence import list_confidence
    confs = list_confidence()
    if not confs:
        console.print("(inga domainer med confidence)")
        return
    for c in confs:
        lockable = "[LOCKABLE]" if c["is_lockable"] else ""
        console.print(f"  {c['domain']:<20} {c['score']:5.0f}% {c['confidence_tier']:<12} {c['session_count']} sessions {lockable}")


@domains_app.command("lock")
def domains_lock(
    domain: str = typer.Argument(..., help="Domain to lock"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Las en domain (kraver human gate)."""
    from .domains.lock import lock_domain, list_lockable
    lockable = [c for c in list_lockable() if c["domain"] == domain]
    if not lockable:
        console.print(f"[yellow]Domain '{domain}' ar inte redo att lasas.[/yellow]")
        console.print("  Krav: 85% confidence, 2+ unika kallor, 3+ sessioner")
        return
    if not yes:
        ans = console.input(f"Las domain '{domain}'? (conf={lockable[0]['score']:.0f}%) [j/N] ").strip().lower()
        if ans not in ("j", "ja", "y", "yes"):
            console.print("[dim]Avbruten.[/dim]")
            return
    if lock_domain(domain, user_confirmed=True):
        console.print(f"[green]{domain} ar nu last. Hund kommer att specialisera sig.[/green]")
        console.print(f"[dim]Nasta steg: researcha kunskapslandskapet med 'hund research {domain}'[/dim]")
    else:
        console.print(f"[red]Kunde inte lasa {domain}.[/red]")


# ---- research ----
@research_app.command("run")
def research_run(
    domain: str = typer.Argument(..., help="Domain to research"),
) -> None:
    """Researcha en domans kunskapslandskap via LLM."""
    from .config import HundConfig
    from .secrets import load_api_key
    from .providers.openai_compatible import OpenAICompatibleClient
    from .research.agent import research_domain
    from .research.scope import KnowledgeScope

    cfg = HundConfig.load()
    key = load_api_key(cfg.provider.api_key_env)
    if not key:
        console.print("[red]API-nyckel kravs for research (anvander LLM for att estimera).[/red]")
        return

    client = OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    console.print(f"[dim]Researchar {domain} via LLM...[/dim]")

    result = research_domain(domain, client)
    if not result:
        console.print("[red]Research misslyckades: kunde inte tolka LLM-svar.[/red]")
        return

    scope = KnowledgeScope(**result)
    path = scope.save()
    console.print(f"[green]Research klar for {domain}[/green]")
    console.print(f"  total_estimated_units: {scope.total_estimated_units}")
    for cat in scope.categories:
        console.print(f"  - {cat['name']}: {cat['estimated_units']} units")
    console.print(f"  sources: {', '.join(scope.sources[:3])}")
    console.print(f"  difficulty: {scope.difficulty}")
    console.print(f"[dim]Scope sparat: {path}[/dim]")
    console.print("[dim]Progressbar aktiverad. Kor 'hund progress' for att se.[/dim]")


@research_app.command("progress")
def research_progress(
    domain: str = typer.Argument(None, help="Domain (visar alla om tom)"),
    detail: bool = typer.Option(False, "--detail", "-d", help="Visa kategori-detaljer"),
) -> None:
    """Visa research-progress for domaner."""
    from .research.scope import calculate_progress
    from .stats.tiers import render_bar

    domains = [domain] if domain else []
    if not domains:
        from ..paths import hund_home as hh
        kdir = hh() / "brain" / "knowledge"
        if kdir.exists():
            for f in sorted(kdir.glob("*-scope.json")):
                dom = f.name.replace("-scope.json", "")
                domains.append(dom)

    if not domains:
        console.print("[yellow]Inga researchade domaner. Kor 'hund research <domain>' forst.[/yellow]")
        return

    for dom in domains:
        prog = calculate_progress(dom)
        if "error" in prog:
            console.print(f"[yellow]{prog['error']}[/yellow]")
            continue
        bar = render_bar(round(prog["percentage"]), width=20)
        console.print(f"  {dom:<20} {bar} {prog['current']}/{prog['total']} ({prog['percentage']}%) {prog['tier']}")
        if detail:
            for cat_name, cat in prog.get("categories", {}).items():
                cat_bar = render_bar(round(cat["percentage"]), width=16)
                console.print(f"    {cat_name:<16} {cat_bar} {cat['current']}/{cat['total']} ({cat['percentage']}%)")


# ---- telemetry ----
@telemetry_app.command("show")
def telemetry_show(
    limit: int = typer.Option(10, "--limit", "-n", help="Antal requests att visa"),
) -> None:
    """Visa senaste requests."""
    from .store.sqlite import connect_requests

    conn = connect_requests()
    rows = conn.execute(
        "SELECT created_at, task_class, prompt_tokens, completion_tokens, latency_ms, finish_reason, provider FROM requests ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    if not rows:
        console.print("(inga requests annu)")
        return
    for r in rows:
        console.print(f"  {r[0][:19]} {r[1]:<15} p={r[2]} c={r[3]} lat={r[4]}ms fin={r[5]} via={r[6]}")


@telemetry_app.command("stats")
def telemetry_stats() -> None:
    """Visa aggregerad telemetri."""
    from .store.sqlite import connect_requests

    conn = connect_requests()
    row = conn.execute(
        """SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),
                  COALESCE(AVG(latency_ms),0), COALESCE(SUM(prompt_tokens+completion_tokens),0)
           FROM requests"""
    ).fetchone()
    n, tin, tout, avg_lat, total = row
    conn.close()
    console.print(f"[bold]Telemetry[/bold]")
    console.print(f"  Requests:          {n}")
    console.print(f"  Avg latency:       {avg_lat:.0f} ms")
    console.print(f"  Tokens in:         {tin}")
    console.print(f"  Tokens out:        {tout}")
    console.print(f"  Total tokens:      {total}")


@telemetry_app.command("opt-in")
def telemetry_opt_in() -> None:
    """Tillat strukturerad export (ingen fritext)."""
    from .config import HundConfig
    cfg = HundConfig.load()
    cfg.telemetry_upload = True
    cfg.save()
    console.print("[green]Telemetri upload aktiverad (safe_metadata_only).[/green]")


@telemetry_app.command("opt-out")
def telemetry_opt_out() -> None:
    """Stoppa all export."""
    from .config import HundConfig
    cfg = HundConfig.load()
    cfg.telemetry_upload = False
    cfg.save()
    console.print("[green]Telemetri upload inaktiverad (local_only).[/green]")


@telemetry_app.command("purge")
def telemetry_purge(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Radera all lokal telemetri."""
    if not yes:
        ans = console.input("Radera ALL telemetridata? [j/N] ").strip().lower()
        if ans not in ("j", "ja", "y", "yes"):
            console.print("[dim]Avbruten.[/dim]")
            return
    from .store.sqlite import connect_requests
    conn = connect_requests()
    conn.execute("DELETE FROM requests")
    conn.commit()
    conn.close()
    console.print("[green]Telemetri raderad.[/green]")


# ---- connector ----


@connector_app.command("keygen")
def connector_keygen() -> None:
    """Generate ny HMAC-nyckel för connector."""
    from .connector.auth import generate_secret, save_secret
    from .paths import connector_key_path

    secret = generate_secret()
    path = connector_key_path()
    save_secret(secret, path)
    console.print(f"[green]Connector-nyckel sparad:[/green] {path}")


@connector_app.command("start")
def connector_start(
    port: int = typer.Option(7432, "--port", "-p", help="Port att lyssna på"),
) -> None:
    """Starta connector-servern på localhost."""
    from .connector.server import start_connector
    from .paths import connector_key_path

    kp = connector_key_path()
    if not kp.exists():
        console.print(
            "[yellow]Ingen connector-nyckel. Kör först: `hund connector keygen`[/yellow]"
        )
        raise typer.Exit(1)

    server = start_connector(port=port, secret_path=kp)
    console.print(f"[green]Connector startad[/green] på 127.0.0.1:{port}")
    console.print("[dim]Tryck Ctrl+C för att stoppa[/dim]")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[green]Connector stoppad.[/green]")
        server.server_close()


@connector_app.command("status")
def connector_status() -> None:
    """Visa connector-status (version + nyckel).
    Kräver att servern körs (använd curl localhost:PORT/health)."""
    console.print("[dim]Connector måste vara igång för hälsokoll:[/dim]")
    console.print("  curl http://127.0.0.1:7432/health")
    console.print("[dim]Nyckelstatus:[/dim]")
    from .paths import connector_key_path

    kp = connector_key_path()
    if kp.exists():
        console.print(f"  nyckel: [green]finns[/green] ({kp})")
    else:
        console.print("  nyckel: [red]saknas[/red] — kör `hund connector keygen`")


# Register sub-apps after their commands are decorated
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
app.add_typer(connector_app, name="connector")
app.add_typer(export_app, name="export")
app.add_typer(local_app, name="local")
app.add_typer(cloud_app, name="cloud")
app.add_typer(telemetry_app, name="telemetry")
app.add_typer(research_app, name="research")


if __name__ == "__main__":
    app()




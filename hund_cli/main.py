"""Hund CLI entrypoint: `hund`.

Skelett 0.1.0. Subkommandon är stubbar som växer in enligt docs/mvp.md.
Körningen nås via entrypoint `hund = "hund_cli.main:app"` i pyproject.toml.
"""
from __future__ import annotations

import sys

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
app.add_typer(learning_app, name="learning")


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
def stats() -> None:
    """Visa lokal token/latency-statistik från SQLite."""
    from .store.sqlite import connect

    conn = connect()
    row = conn.execute(
        """SELECT COUNT(*),
                  COALESCE(SUM(prompt_tokens),0),
                  COALESCE(SUM(completion_tokens),0),
                  COALESCE(SUM(latency_ms),0)
           FROM requests"""
    ).fetchone()
    conn.close()
    n, tin, tout, lat = row
    console.print(
        f"[bold]Hund stats[/bold] · requests: {n} · "
        f"tokens in/out: {tin}/{tout} · total latency: {lat}ms"
    )


@app.command()
def verify() -> None:
    """Verifiera Hund-systemet (persona laddad, permission-block aktivt)."""
    console.print("[green]verify[/green]: hund_cli importerar OK.")
    console.print(f"version: {__version__}")


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

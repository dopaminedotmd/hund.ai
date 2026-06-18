# Hund CLI

> Hund är en installerbar, local-first, self-improving CLI-agentmotor som lever i
> hårdvaran han startas på.

Hund analyserar sin miljö vid uppstart, hjälper användaren via tools, bygger
lokal mastery, mäter sin egen prestation och bidrar säkert till en global
förbättringsloop — men **Hund föreslår och debatterar; Hund publicerar aldrig
sig själv.** Varje uppdatering kräver en mänsklig gate.

Detta repo är **motorn**. Hunds själ/persona (vision, rapporter, persona-filer)
bor i ett separat `hund-system` och kopplas in som default assets senare.

## Status

`0.1.0` — skelett + byggkontrakt. Se `docs/mvp.md`.

## Snabbstart (dev)

```bash
uv sync --extra dev   # skapar .venv, installerar deps (hämtar Python vid behov)
uv run hund --version
uv run pytest
```

## Installation (Windows one-liner)

```powershell
irm https://raw.githubusercontent.com/dopaminedotmd/hund-cli/main/install.ps1 | iex
```

Sen: sätt API-nyckel och starta Hund:

```powershell
setx HUND_API_KEY "sk-..."   # ny terminal efteråt
hund
```

I REPL: `/tools`, `/stats`, `/profile`, `/exit`.

## Dokumentation

- `docs/architecture.md` — tre-skiktad arkitektur, TCB, gränssnittskontrakt, valda beslut.
- `docs/mvp.md` — MVP Definition of Done, första 10 bygguppgifterna, vad som skjuts upp.

## Licens

Apache-2.0.

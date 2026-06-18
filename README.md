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

`0.1.0` — **minimal functional core**. Se `docs/mvp.md`.

Implementerade system:

| System | Status |
|---|---|
| REPL-agentloop (BYOK, streaming, tool calling) | ✅ klart |
| Privacy/Redactor TCB | ✅ klart |
| Runtime policy (deklarativt beteendelager) | ✅ klart |
| Skill-system v1 (skills, matcher, validator) | ✅ klart |
| Domain detection v1 (SQLite, CLI) | ✅ klart |
| Context compression v1 (deterministisk) | ✅ klart |
| Eval/regression library (10 smoke-cases) | ✅ klart |
| Self-improvement proposals (human-gated) | ✅ klart |
| Installer hardening (SHA-manifest, verify) | ✅ klart |
| UI/TUI | ⏸ avsiktligt uppskjuten |

> **UI är avsiktligt borttagen / uppskjuten.** En fungerande funktionskärna
> (tests, privacy, policy, skills, domains, eval) måste vara verifierad och
> dogfoodad innan någon terminal-UI byggs. Se `docs/plans/HUND_NEXT_BUILD_PLAN.md §4.1`.

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
- `docs/plans/HUND_NEXT_BUILD_PLAN.md` — fas-plan för funktionskärnan, UI-gate och dogfooding.

## Licens

Apache-2.0.

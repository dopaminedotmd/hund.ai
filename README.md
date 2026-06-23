# Hund

> Hund är ett installerbar, self-improving CLI-agent-skal som ger illusionen av att vara en del av din maskin.

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
| UI/TUI (OpenTUI) | ✅ klart |

## TUI (OpenTUI)

Krav: Bun (https://bun.sh)

1. Installera Bun: curl -fsSL https://bun.sh/install | bash
2. cd tui && bun install
3. uv run hund   (startar TUI automatiskt)
4. uv run hund repl   (terminal-REPL som fallback)

## Snabbstart (dev)

```bash
uv sync --extra dev   # skapar .venv, installerar deps (hämtar Python vid behov)
uv run hund --version
uv run pytest
```

## Installation (Windows one-liner)

```powershell
irm https://raw.githubusercontent.com/dopaminedotmd/hund.ai/main/install.ps1 | iex
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

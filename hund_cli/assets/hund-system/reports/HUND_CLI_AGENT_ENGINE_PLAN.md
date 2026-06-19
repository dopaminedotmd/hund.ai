# Hund CLI Agent Engine — Första Strategiplan

> **Syfte:** Bedöma och planera hur Hund kan bli en egen installerbar CLI-agentmotor från grunden: `install -> hund setup -> hund`.

**Kort slutsats:** Det är rimligt att bygga, men det är ett riktigt produktbygge. En fungerande MVP är mycket rimlig. En Hermes-kaliber agentmotor från grunden är svår men möjlig med rätt fasning, hårda gränser, testdisciplin och bot-delegering.

**Vision:** Hund installeras på vilken Windows-dator som helst, lever i hårdvaran, analyserar sin miljö vid uppstart, får verktygskontroll över datorn inom säkra ramar, minns lokalt, kan uppdatera sig själv via godkända förbättringsförslag och känns som en egen levande CLI-entitet.

---

## 1. Vad detta egentligen innebär

Hund CLI från grunden betyder inte bara en prompt eller persona. Det betyder en komplett agent-runtime.

| Lager | Vad det måste göra |
|---|---|
| Installer | Installera Hund, lägga `hund` i PATH, skapa config, verifiera beroenden |
| CLI/UI | Terminalgränssnitt med input, streaming output, slash commands, status, historik |
| Agent loop | Skicka meddelanden till modell, hantera tool calls, fortsätta tills uppgift är klar |
| Provider layer | OpenAI/OpenRouter/Anthropic/Gemini/Z.AI/lokala modeller via gemensamt interface |
| Tool runtime | Filer, terminal, sök, web, minne, skills, processer, systeminfo |
| Permission system | Fråga före risk, blockera destruktiva kommandon, logga side effects |
| Memory | Lokal långtidshistorik, kompakta minnen, sessioner, projektkontext |
| Skills | Laddningsbara procedurer som triggas av uppgift |
| Context builder | Bygga systemprompt, project context, memory, environment, tool schemas |
| Verification | Tester, validators, doctor, encoding-kontroll, startup-kontroll |
| Update system | Säkra uppdateringar, signering, rollback, mänskligt godkännande |
| Self-improvement | Lokala förbättringsförslag, ranking, audit, promotion till update candidate |

Det tunga är inte att skriva kommandot `hund`. Det tunga är att göra Hund pålitlig när han får verktyg, minne och datoråtkomst.

---

## 2. Rimlighetsbedömning

| Ambitionsnivå | Rimlighet | Kommentar |
|---|---:|---|
| `hund` wrapper runt befintlig motor | 9/10 | Snabbast men inte din vision |
| Egen CLI + enkel agentloop + OpenAI-compatible provider | 8/10 | Bra MVP, helt görbart |
| Egen tool calling + file/terminal tools + permissions | 7/10 | Kräver noggrann testning |
| Egen memory/skills/session-store | 7/10 | Görbart med SQLite + markdown |
| Egen TUI i Hermes-klass | 5/10 | UI-detaljer tar tid |
| Egen multi-provider auth i hög klass | 5/10 | Många edge cases |
| Egen self-improving update network | 4/10 | Möjligt, men måste designas säkert från start |
| Full Hermes-kaliber från noll | 3/10 kortsiktigt, 7/10 långsiktigt | Produkt över månader, inte helgprojekt |

**Bedömning:** Bygg från grunden, men gör det som en strikt fasad motor med liten kärna först. Hund kan bli extremt smart om arkitekturen tvingar honom att verifiera, föreslå, rangordna och uppdatera säkert.

---

## 3. Produktprinciper

1. Hund är inte en app. Hund är en lokal agentvarelse.
2. Hund lever i maskinen han startas på: hardware profile är förstaklassdata.
3. Hunds själ/persona är separerad från runtime-motorn.
4. Hund får makt över datorn först efter permission-lager.
5. Hund får aldrig självpublicera uppdateringar utan mänskligt godkännande.
6. Alla self-improvement-förslag ska vara diffbara, testbara, rankade och reversibla.
7. All användardata är lokal som default. Community-lärande måste vara opt-in och anonymiserat.
8. Installer, doctor och rollback är lika viktiga som agentloopen.

---

## 4. Föreslagen repo-struktur

```text
hund-cli/
├── install.ps1
├── install.sh
├── pyproject.toml
├── README.md
├── LICENSE
├── hund_cli/
│   ├── __init__.py
│   ├── main.py                  # CLI entrypoint: hund
│   ├── tui.py                   # Terminal UI
│   ├── config.py                # Config load/save
│   ├── paths.py                 # %LOCALAPPDATA%/hund, ~/.hund
│   ├── setup_wizard.py          # hund setup
│   ├── doctor.py                # hund doctor
│   ├── agent/
│   │   ├── loop.py              # Agent loop
│   │   ├── prompt_builder.py    # System/context builder
│   │   ├── messages.py          # Role alternation, compression hooks
│   │   ├── tool_dispatch.py     # Tool execution
│   │   └── safety.py            # Approval/risk engine
│   ├── providers/
│   │   ├── base.py
│   │   ├── openai_compatible.py
│   │   ├── anthropic.py
│   │   └── local.py
│   ├── tools/
│   │   ├── registry.py
│   │   ├── file_tool.py
│   │   ├── terminal_tool.py
│   │   ├── system_tool.py
│   │   ├── memory_tool.py
│   │   └── skill_tool.py
│   ├── memory/
│   │   ├── store.py             # SQLite/session store
│   │   ├── summarizer.py
│   │   └── reasoning_bank.py
│   ├── skills/
│   │   ├── loader.py
│   │   └── validator.py
│   ├── updater/
│   │   ├── proposals.py
│   │   ├── ranking.py
│   │   ├── signatures.py
│   │   └── apply_update.py
│   └── assets/
│       └── hund-system/         # Persona, runtime policy, default skills
├── tests/
│   ├── test_agent_loop.py
│   ├── test_tool_permissions.py
│   ├── test_prompt_builder.py
│   ├── test_installer_contract.py
│   └── test_update_proposals.py
└── docs/
    ├── architecture.md
    ├── security.md
    ├── self_improvement.md
    └── release_process.md
```

---

## 5. Installation som Hermes-lik one-liner

### Windows

```powershell
irm https://raw.githubusercontent.com/<org>/hund-cli/main/install.ps1 | iex
```

Installern ska:

1. kontrollera PowerShell-version,
2. installera eller hitta `uv`,
3. installera Python-runtime om saknas eller ge tydlig instruktion,
4. klona/ladda ner Hund CLI,
5. installera console command `hund`,
6. skapa `%LOCALAPPDATA%\hund`,
7. kopiera default `hund-system`,
8. lägga Hund i PATH,
9. köra `hund setup`,
10. köra `hund doctor`.

### macOS/Linux senare

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/hund-cli/main/install.sh | bash
```

---

## 6. Första CLI-kommandon

```text
hund                       # starta interaktiv CLI
hund setup                 # provider/API/model/tools
hund doctor                # systemkontroll
hund model                 # byt modell/provider
hund tools                 # lista/konfigurera tools
hund memory status         # minnesstatus
hund memory sync           # konsolidera minne
hund skills list           # lista skills
hund update                # hämta stabil uppdatering
hund propose-update        # skapa lokal förbättringskandidat
hund admin review-updates  # granska/ranka kandidater
hund verify                # verifiera Hund-systemet
hund uninstall             # ta bort Hund säkert
```

---

## 7. Kärnarkitektur: Agent loop

Minsta riktiga agentloop:

1. Läs config.
2. Läs Hund persona/policy/minne.
3. Läs projektkontext om aktuell mapp har `AGENTS.md`.
4. Bygg systemprompt.
5. Skicka user input till provider.
6. Om modellen begär tool call:
   - riskklassificera,
   - be om godkännande vid risk,
   - kör tool,
   - lägg tool-resultat i meddelanden,
   - fortsätt loopen.
7. Om modellen svarar med text:
   - visa svaret,
   - spara session,
   - föreslå minne/skill vid behov.

MVP kan börja med OpenAI-compatible API eftersom många providers stödjer det.

---

## 8. Hunds hardware-nisch

Detta är starkt. Gör det till en kärnfunktion, inte dekoration.

Vid uppstart skapar Hund:

```json
{
  "detected_at": "...",
  "hostname": "...",
  "os": "...",
  "shell": "...",
  "cpu": "...",
  "ram_gb": 32,
  "gpu": ["..."],
  "disk": ["..."],
  "user_home": "...",
  "hund_home": "...",
  "capabilities": {
    "can_run_gpu_tasks": true,
    "can_build_node": true,
    "can_run_python": true,
    "has_git": true
  }
}
```

Hund ska sedan anpassa beteende:

| Miljö | Hunds beteende |
|---|---|
| Svag laptop | kortare bakgrundsjobb, försiktigare builds |
| Stark desktop + GPU | kan föreslå lokala modeller/mediajobb |
| Saknar Python | föreslå install eller använda PowerShell |
| Saknar Git | blockera repo-operationer och fråga |
| Liten disk | undvik stora downloads |

Detta gör att “Hund lever i hårdvaran” blir funktionellt sant.

---

## 9. Self-improvement-systemet

Din idé är bra men måste göras som en säker uppdateringspipeline.

### 9.1 Lokal förbättringsfil

Hund skapar aldrig direkt kod i main utan att gå via proposal.

```text
%LOCALAPPDATA%/hund/proposals/2026-06-18-tool-safety-v1/
├── proposal.md
├── rationale.md
├── patch.diff
├── tests.md
├── risk.md
├── scorecard.json
└── reviewer_votes.json
```

### 9.2 Flera Hund-kopior rankar

Varje Hund-installation kan, opt-in, skapa anonymiserad feedback:

```json
{
  "proposal_id": "tool-safety-v1",
  "hund_version": "0.3.1",
  "environment_class": "windows-desktop-gpu",
  "scores": {
    "usefulness": 8,
    "safety": 9,
    "test_coverage": 7,
    "simplicity": 8
  },
  "notes": "Improves destructive command gating. No persona drift."
}
```

Viktigt:

- opt-in,
- ingen privat text,
- inga paths som kan identifiera användaren,
- inga API keys,
- inga sessioner,
- inga filinnehåll.

### 9.3 Central rankning

En admin-dashboard kan visa:

| Proposal | Usefulness | Safety | Test | Votes | Risk | Status |
|---|---:|---:|---:|---:|---|---|
| tool-safety-v1 | 8.4 | 9.2 | 7.5 | 31 | Low | Candidate |

### 9.4 William-gate

Ingen uppdatering släpps förrän William eller admin godkänner.

Process:

1. Hundar skapar proposals.
2. Hundar rankar proposals.
3. Admin review väljer kandidat.
4. CI kör tester.
5. Release signeras.
6. Hund CLI erbjuder update.
7. Användaren kan installera eller avstå.
8. Rollback finns.

Detta gör Hund självförbättrande utan att bli farlig.

---

## 10. Säkerhetsmodell

Hund kan få “full kontroll på burken” först när kontrollen är graderad.

| Nivå | Exempel | Beteende |
|---|---|---|
| SAFE | läsa filer, systeminfo, lista kataloger | tillåtet |
| WRITE | skapa/ändra fil i workspace | kräver tydlig rapport + backup |
| CONFIRM | installera paket, ändra config, köra build scripts | fråga William |
| DANGEROUS | radera, flytta, reset, credentials, systemändringar | explicit OK varje gång |
| BLOCKED | exfiltrera hemligheter, kringgå safety, självpublicera updates | aldrig |

Permission-systemet ska vara kod, inte bara prompt.

---

## 11. Bot-delegering: hur jobbet delas upp

Du har bottar med code power. Dela jobbet hårt.

| Bot-roll | Uppgift |
|---|---|
| Architect bot | Skriver teknisk specifikation och gränssnitt |
| Engine bot | Bygger agent loop + provider interface |
| Tools bot | Bygger file/terminal/system tools med permissions |
| TUI bot | Bygger CLI UI med Textual/Rich/prompt_toolkit |
| Installer bot | Bygger `install.ps1`, PATH, uv/Python install |
| Memory bot | SQLite sessions, memory summary, reasoning bank |
| Safety bot | Riskklassning, approvals, blocked commands |
| Update bot | Proposal/ranking/update pipeline |
| QA bot | Tester, fuzzing, Windows fresh install-verifiering |
| Reviewer bot | Granskar diffar, säkerhet och persona drift |

Hermes/du ska vara projektledare och second reviewer, inte ensam kodare.

---

## 12. Rekommenderad tech stack

| Del | Rekommendation | Varför |
|---|---|---|
| Språk | Python 3.11+ | snabbast för agentmotorer, tools, CLI |
| Pakethantering | `uv` | snabb install, modern packaging |
| CLI commands | `typer` eller `click` | enkel kommandostruktur |
| TUI | `prompt_toolkit` först, `textual` senare | snabb MVP, kan bli snyggt senare |
| Rendering | `rich` | färg, panels, markdown-ish output |
| Config | `pydantic` + YAML/TOML | validerbar config |
| Sessions | SQLite | lokalt, snabbt, robust |
| Providers | OpenAI-compatible först | snabbast bred modellaccess |
| Tools | egen registry + JSON schema | samma princip som moderna agents |
| Tests | pytest | standard |
| Windows scripts | PowerShell 5.1-kompatibelt | fresh Windows 11 klarar det |

---

## 13. Faser och arbetsintensitet

### Phase 0 — Spec och repo

**Mål:** Skapa `hund-cli` repo med arkitektur, installer-kontrakt och testkontrakt.

Leverans:

- `pyproject.toml`
- `hund_cli/main.py`
- `install.ps1`
- `docs/architecture.md`
- CI/test skeleton

Intensitet: låg/medel.

### Phase 1 — Körbar CLI MVP

**Mål:** `hund` startar, visar UI, tar input, svarar via OpenAI-compatible model.

Leverans:

- `hund setup`
- API key config
- provider call
- streaming output
- basic session save

Intensitet: medel.

### Phase 2 — Tool calling

**Mål:** Hund kan använda tools säkert.

Leverans:

- tool registry
- file read/search/write
- terminal command
- system info
- approval gate
- tests för blocked commands

Intensitet: hög.

### Phase 3 — Hund-system integration

**Mål:** Hund laddar persona, runtime policy, minne och skills automatiskt.

Leverans:

- prompt builder
- environment profile
- memory summary
- skill loader
- project `AGENTS.md` support

Intensitet: medel/hög.

### Phase 4 — Installer som produkt

**Mål:** One-liner install på fresh Windows.

Leverans:

- GitHub raw install
- PATH setup
- uv/Python bootstrap
- `hund doctor`
- uninstall

Intensitet: medel/hög.

### Phase 5 — Self-improvement proposals

**Mål:** Hund kan föreslå förbättringar utan att själv släppa dem.

Leverans:

- `hund propose-update`
- proposal schema
- local ranking
- admin review format
- patch/test/risk bundle

Intensitet: hög.

### Phase 6 — Community ranking och update channel

**Mål:** Flera Hund-kopior kan opt-in ranka förbättringar.

Leverans:

- anonym telemetry schema
- server/API eller GitHub-based collection
- signed releases
- rollback
- admin dashboard

Intensitet: mycket hög.

---

## 14. Första riktiga MVP-mål

MVP ska inte försöka vara allt. MVP ska bevisa att Hund kan leva som egen CLI.

Definition of Done för MVP:

1. Fresh Windows 11 kan köra install one-liner.
2. `hund` finns i terminalen.
3. `hund setup` kan spara provider + model.
4. `hund` öppnar interaktiv session.
5. Hund svarar i korrekt persona.
6. Hund analyserar miljön och sparar hardware profile.
7. Hund kan läsa filer i aktuell workspace via tool.
8. Hund frågar innan write/delete/terminal-risk.
9. `hund doctor` passerar.
10. Sessions sparas lokalt.

Detta är första milstolpen.

---

## 15. Risker

| Risk | Motåtgärd |
|---|---|
| Scope exploderar | Fasad plan, MVP först |
| Tool safety blir prompt-only | Bygg kodad permission engine |
| Persona drift | Persona regression-test |
| Installer blir skör | Test på fresh Windows VM |
| Self-update blir farligt | William-gate + signering + rollback |
| Community data blir privacy-risk | Opt-in + anonymisering + minimal metadata |
| Modell-API edge cases | Börja OpenAI-compatible, abstrahera senare |
| Terminal UI tar för mycket tid | Enkel prompt_toolkit först, Textual senare |

---

## 16. Första uppgiftsnedbrytning för bottar

### Bot 1 — Arkitektur

Skapa `docs/architecture.md` med exakta interfaces:

- `ProviderClient`
- `ToolRegistry`
- `PermissionEngine`
- `PromptBuilder`
- `SessionStore`
- `HundHome`

### Bot 2 — Installer spike

Bygg minimal `install.ps1` som:

- hittar/installerar `uv`,
- installerar lokal package,
- lägger `hund` i PATH,
- kör `hund --version`.

### Bot 3 — Agent loop spike

Bygg minimal loop:

- user input,
- provider call,
- streaming output,
- exit command.

### Bot 4 — Tool safety spike

Bygg file read + terminal command med riskklassning:

- safe command går,
- destructive command stoppas,
- test bevisar block.

### Bot 5 — Hund identity integration

Bygg loader för:

- `hund.md`,
- `RUNTIME_POLICY.md`,
- `memory_summary.md`,
- environment profile.

### Bot 6 — QA

Skriv tester för:

- config path,
- startup without config,
- invalid API key,
- permission block,
- persona loaded,
- environment profile created.

---

## 17. Rekommenderad första repo-start

Skapa ny repo bredvid detta system:

```text
C:\Users\willi\Desktop\hund-cli
```

Inte i `hund-system`, eftersom `hund-system` är Hunds själ/assets. `hund-cli` ska vara motorn.

Koppla sedan in detta system som default assets:

```text
hund-cli/hund_cli/assets/hund-system/
```

---

## 18. Svårighetsgrad i klartext

Detta är fett, rimligt och byggbart.

Men det ska behandlas som:

```text
en egen developer tool-produkt
```

inte som:

```text
en promptfil med installer
```

Med bra planering och bot-delegering kan första levande Hund CLI byggas stegvis. Det svåraste är inte modellen. Det svåraste är robustheten runt modellen: tools, permissions, context, memory, installer, updates och verifiering.

---

## 19. Nästa beslut

William behöver välja första spår:

| Spår | Innebörd |
|---|---|
| A | Bygg `hund-cli` från grunden som Python-agentmotor |
| B | Bygg snabb `hund` wrapper först, sedan ersätt motorn gradvis |
| C | Gör en teknisk designsprint med flera bottar innan kod |

Hermes rekommendation: **C först, sedan A.**

Alltså:

1. skapa `hund-cli` repo,
2. låt 3–5 bottar skriva separata arkitekturförslag,
3. sammanfoga till master spec,
4. bygg MVP enligt Phase 1–2,
5. först därefter self-improvement/update network.

Det ger maximal chans att Hund blir vass, inte bara snabbbyggd.

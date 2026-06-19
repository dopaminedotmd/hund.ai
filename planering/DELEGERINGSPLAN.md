# Hund TUI — Delegeringsplan

> Skapad: 2026-06-19
> Auktor: Hermes (DeepSeek V4 Pro)
> Plan: `TUI_OPENTUI_PLAN.md`
> Status: Planen är spikad. Bygget startar enligt denna delegering.

---

## 0. Vem gör vad

```
┌─────────────────────────────────────────────────────────┐
│                     HERMES (DeepSeek)                    │
│                  Projektledare · Delegator               │
│                                                         │
│  - Skrev planen (TUI_OPENTUI_PLAN.md)                   │
│  - Delegerar ALLT byggarbete                            │
│  - Kodar ENDAST via Codex vid behov                     │
│  - Tar emot analysresultat, fattar go/no-go-beslut      │
│  - Aldrig primär kodare                                 │
└──────────┬────────────────────────┬─────────────────────┘
           │                        │
           ▼                        ▼
┌──────────────────────┐  ┌──────────────────────────────┐
│   CLAUDE CODE         │  │   ANTI-GRAVITY              │
│   (GLM 5.2)           │  │   (alla modeller)            │
│                       │  │                              │
│   Primär kodare       │  │   Analys- & auditbottar       │
│                       │  │                              │
│   - Bygger TUI:n      │  │   - Läser planen             │
│   - Skriver all kod   │  │   - Granskar kod             │
│   - Kör tester        │  │   - Bekräftar att fas är     │
│   - Fixar buggar      │  │     korrekt implementerad    │
│                       │  │   - Flaggar avvikelser       │
│   Max ~6 filer per    │  │   - Ger GO/NO-GO per fas     │
│   session (GLM 5.2    │  │                              │
│   begränsning)        │  │                              │
└──────────────────────┘  └──────────────────────────────┘
           │                        │
           └────────┬───────────────┘
                    ▼
┌─────────────────────────────────────────────────────────┐
│                     HERMES (igen)                        │
│                                                         │
│  - Tar emot byggresultat från Claude Code               │
│  - Tar emot audit från Anti-Gravity                     │
│  - Bockar av fasen om GO från Anti-Gravity              │
│  - Delegaterar nästa fas                                │
│  - Vid problem: skriver korrigerings-prompt till        │
│    SAMMA bot som byggde/analyserade                     │
└─────────────────────────────────────────────────────────┘
```

---

## 1. Hermes — Regler

| Regel | Förklaring |
|---|---|
| **Aldrig primär kodare** | Hermes skriver inte koden. Det är Claude Codes jobb. |
| **Delegerar allt** | Varje bygguppgift → Claude Code. Varje granskning → Anti-Gravity. |
| **Kodar ENDAST via Codex** | Om Hermes MÅSTE koda (t.ex. en enkel script-fix), används Codex som motor. Aldrig direkt. |
| **Skriver prompts** | Hermes översätter planen till konkreta byggprompts för Claude Code. |
| **Tar emot, förstår, delegerar vidare** | När en bot levererar → Hermes förstår resultatet → skickar nästa steg. |
| **Gör aldrig samma jobb som en bot redan gjort** | Om Anti-Gravity hittar fel → Hermes skriver en prompt till CLAUDE CODE för att fixa. Inte fixa själv. |

---

## 2. Claude Code — Primär kodare

### 2.1 Setup

| Parameter | Värde |
|---|---|
| Motor | Claude Code CLI |
| Modell | GLM 5.2 |
| Arbetssätt | Session per fas. Ny session per delegering. |
| Begränsning | Max ~6 filer per session |
| Promptkälla | Hermes skriver byggprompts, placeras i `hund-cli/prompts/` |
| Workspace | `C:\Users\willi\Desktop\hund-cli` |

### 2.2 Regler för Claude Code

- Läs `CLAUDE.md` först — alltid
- Caveman-läge: ultra-komprimerad output
- Ratio reads:edits minst 4:1
- Max 2 försök på samma fix
- 10+ min utan edit → stoppa
- Inga emojis i kod
- Kör `uv run pytest` efter varje ändring
- Ändra ALDRIG `agent/loop.py` eller `persona.md` utan Hermes OK
- Rapportera: vad byggdes, vilka filer ändrades, testresultat

### 2.3 Promptformat

Varje delegering från Hermes till Claude Code följer detta format:

```markdown
# [Fas X]: [Namn]

## Kontext
[Vad som redan finns, vad som ska byggas, relevanta filer]

## Uppgift
[Konkret, mätbar leverabel]

## Filer att skapa/ändra
- [path] — [vad]

## Validering
- [exakt testkommando eller verifikation]

## Designspec (om relevant)
[Färger, layout, komponentbeteende från TUI_OPENTUI_PLAN.md]

## Begränsningar
- Max ~6 filer
- [Andra specifika begränsningar]
```

---

## 3. Anti-Gravity — Analys & Audit

### 3.1 Roll

Anti-Gravity agerar med **alla sina modeller** som en analyspanel. De:

1. Läser den aktuella planen (`TUI_OPENTUI_PLAN.md`)
2. Läser koden Claude Code har producerat
3. Bekräftar att implementationen matchar designspecen
4. Flaggar: avvikelser, buggar, stilbrott, saknade tester
5. Ger GO/NO-GO per fas

### 3.2 Audit per fas

Efter varje fas levererar Claude Code → Hermes skickar koden till Anti-Gravity med denna prompt:

```markdown
# Audit: Fas X — [Namn]

## Vad skulle byggas
[Kort sammanfattning från planen]

## Vad byggdes
[Claude Codes rapport]

## Filer att granska
- [lista med absoluta paths]

## Valideringspunkter
- [ ] Matchar designspecen (färger, layout, ikoner)?
- [ ] Tester gröna?
- [ ] Inga emojis i output?
- [ ] IPC-protokollet följt?
- [ ] Inga avvikelser från planen?

## Output
Ge GO eller NO-GO. Vid NO-GO: exakt vad som är fel, vilken fil, vilken rad.
```

### 3.3 Anti-Gravity-modeller

Alla tillgängliga modeller i Anti-Gravity används. Varje modell granskar oberoende. Hermes läser alla svar och väger samman.

---

## 4. Codex — Hermes reservmotor

Används ENDAST när:

| Scenario | Exempel |
|---|---|
| Hermes måste göra en enkel script-ändring | Uppdatera versionsnummer, fixa en path |
| Snabbare att göra själv än att delegera | En rads fix i en config-fil |
| Claude Code är upptagen/otillgänglig | — |

**Regel:** Hermes använder Codex sparsamt. Primär kodning är ALLTID Claude Codes jobb.

---

## 5. Arbetsflöde per fas

```
1. HERMES
   ├── Läser TUI_OPENTUI_PLAN.md för aktuell fas
   ├── Skriver byggprompt → sparar i prompts/fas-X.md
   └── Delegerar till Claude Code

2. CLAUDE CODE (GLM 5.2)
   ├── Läser CLAUDE.md
   ├── Bygger enligt prompt
   ├── Kör tester
   └── Rapporterar tillbaka: filer, resultat, problem

3. HERMES
   ├── Tar emot rapport
   ├── Skriver audit-prompt
   └── Delegerar till Anti-Gravity

4. ANTI-GRAVITY (alla modeller)
   ├── Läser plan + kod
   ├── Oberoende granskning
   └── GO / NO-GO per modell

5. HERMES
   ├── Väger samman audit-resultat
   ├── GO → bocka av fas, gå till nästa
   └── NO-GO → skriv korrigerings-prompt → tillbaka till steg 2
```

---

## 6. Fas-checklista

| Fas | Namn | Byggd | Audited | Status |
|---|---|---|---|---|
| 0 | Scaffolding & IPC-verifiering | ⬜ | ⬜ | — |
| 1 | Chat History + InputBox | ⬜ | ⬜ | — |
| 2 | StateIndicator + TaskList + FileHeader | ⬜ | ⬜ | — |
| 3 | Tool approval-flow | ⬜ | ⬜ | — |
| 4 | Syntax highlighting + Markdown | ⬜ | ⬜ | — |
| 5 | Progress bars + Polish | ⬜ | ⬜ | — |

---

## 7. Prompt-mapp

Alla delegeringsprompts sparas i:

```
hund-cli/prompts/
├── fas-0_scaffolding.md
├── fas-1_chat-input.md
├── fas-2_states-tasks.md
├── fas-3_tool-approval.md
├── fas-4_syntax-markdown.md
└── fas-5_progress-polish.md
```

Hermes skapar dessa löpande. Claude Code läser dem vid varje delegering.

---

## 8. Kommunikationsregler

| Regel | Varför |
|---|---|
| Hermes skriver ALLTID prompten | Claude Code får ingen lös kontext |
| Ny session per fas | GLM 5.2 har begränsat kontextfönster |
| Anti-Gravity får HELA koden | Ska kunna se allt, inte bara diff |
| All output till William i tabellform | Inga textväggar |
| Vid blockering → Hermes rapporterar direkt till William | Inte loopa |

---

*Denna fil är operativ. Uppdateras när faser bockas av.*
*Hermes är ytterst ansvarig för att delegeringen följs.*

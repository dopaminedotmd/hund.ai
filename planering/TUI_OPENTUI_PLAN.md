# Hund CLI — TUI med OpenTUI

> Skapad: 2026-06-19
> Status: Planeringsfas. Python TUI död (7 fail). OpenTUI spikad.
> Baserad på: `hund_consolidated_superprompt.md` (Obsidian), `TUI_ALTERNATIV_PLAN.md`

---

## 0. Beslutet

**OpenTUI** är valt. Varför:

- Native Zig-kärna + TypeScript/React-bindings — prestanda + utvecklingshastighet
- Yoga flexbox (Facebooks layoutmotor, samma som React Native)
- tree-sitter inbyggd (syntax highlighting)
- Driver OpenCode i produktion — battle-tested
- C ABI — kan binda direkt till Python vid behov
- `bun create tui` — scaffolding inbyggd

## 1. Designspex (från `hund_consolidated_superprompt.md`)

### 1.1 Färgpalett

| Roll | Färg | Hex |
|---|---|---|
| Bakgrund | Deep dark grey | `#0d0d0d` (eller terminal-transparent) |
| Primär text | Cream/warm off-white | `#E8E0D5` |
| Accenter & ikoner | Warm brown | `#a09080` |
| Status-indikatorer | Muted green | (aktiv/cooking) |
| Metadata & dimmad text | Dark grey/dimmed | |
| Syntax highlight | tree-sitter (auto) | |

### 1.2 Ikoner — INGA emojis

| Symbol | Unicode | Användning |
|---|---|---|
| ⬢ | U+2B22 | Hexagon — aktiv state, task-header |
| ☒ | U+2612 | Task completed |
| ▣ | U+25A3 | Task in-progress |
| ☐ | U+2610 | Task pending |
| → | U+2192 | Input-prompt |
| ┌─┐│└─┘ | Box-drawing | Ramar, rutor |

### 1.3 Skärmlayout (top → botten)

```
┌──────────────────────────────────────────────────────┐
│ 1. FILE/PROCESS HEADER                               │
│    ┌──────────────────────────────────────────────┐  │
│    │ path/to/active/file.py                       │  │
│    └──────────────────────────────────────────────┘  │
│                                                      │
│ 2. TASK CHECKLIST                                    │
│    ⬢ Working on [N] to-dos                          │
│    ☒ Completed task (dimmad)                         │
│    ▣ In-progress task (bright white)                 │
│    ☐ Pending task (dimmad)                           │
│                                                      │
│ 3. ACTIVE STATE INDICATOR                            │
│    ⬢ Cooking... / ⬢ Thinking... / ⬢ Running tests... │
│                                                      │
│ 4. CHAT HISTORY (scrollbart)                         │
│    → User input                                      │
│    Hund response (markdown-renderad)                  │
│    Tool call/output inlined                          │
│                                                      │
│ 5. BOTTOM INPUT BOX                                  │
│    ┌──────────────────────────────────────────────┐  │
│    │ → Add a follow-up                            │  │
│    └──────────────────────────────────────────────┘  │
│                                                      │
│ 6. FOOTER METADATA                                   │
│    Hund · X% context used · Y files edited            │
│    / for commands · shortcut keys help                │
└──────────────────────────────────────────────────────┘
```

### 1.4 Task-states — exakt rendering

```
⬢ Working on 3 to-dos

☒ Läs pyproject.toml                          ← dimmed
▣ Kör pytest --lf                             ← bright white
☐ Granska testresultat                        ← dimmed

⬢ Cooking...
```

### 1.5 ASCII Progress Bars

Ingen glitter, inga emojis, inga dopamine-popups. Rena ASCII-staplar:

```
CLR [████░░░░] 50%
PRC [==========....] 75%
```

Används i chat-historiken, inte som overlay.

### 1.6 States som måste renderas

| State | Visuellt | Varaktighet |
|---|---|---|
| idle | Footer: `Hund · X% context` | konstant |
| thinking | `⬢ Thinking...` i state-sektionen | tills första token |
| streaming | Tokens renderas inkrementellt i chat | under hela stream |
| tool_waiting | Tool call inline: `⚙ terminal: pytest --lf` | tills tool_result |
| tool_result | Resultat inline, dimmad | konstant efter |
| error | `⬢ Error: meddelande` i rött | tills nästa action |
| confirming | `[Godkänn? (y/n)]` vid CONFIRM/DANGEROUS | tills användaren svarar |

## 2. Teknisk arkitektur

### 2.1 Processmodell

```
┌─────────────────────────────────────────┐
│           OpenTUI-process (Bun)          │
│                                          │
│  React-komponenter                       │
│  ├── App.tsx          (root layout)      │
│  ├── Header.tsx       (file/info)        │
│  ├── TaskList.tsx     (checklista)       │
│  ├── StateIndicator.tsx (⬢ Cooking...)   │
│  ├── ChatHistory.tsx  (scrollbar chat)   │
│  ├── InputBox.tsx     (→ prompt)         │
│  └── Footer.tsx       (metadata)         │
│                                          │
│  IPC Bridge (JSON-lines)                 │
│      ↕ stdin/stdout                      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│       Python Agent Process (uv)          │
│                                          │
│  IPC Bridge (JSON-lines)                 │
│  Agent Loop (agent/loop.py)              │
│  Provider (LLM API)                      │
│  Tools (file, terminal, search)          │
└─────────────────────────────────────────┘
```

### 2.2 IPC-protokoll — JSON-lines

Varje meddelande är en JSON-rad med `\n`.

#### TUI → Agent

```json
{"type":"user_input","text":"kör testerna","session_id":"s1"}
{"type":"tool_approval","tool_call_id":"call_1","approved":true}
{"type":"command","command":"exit"}
{"type":"command","command":"interrupt"}
{"type":"command","command":"name_change","value":"william"}
```

**TUI-interna kommandon** (hanteras av TUI:n själv, skickas inte till agenten):

| Kommando | Effekt |
|---|---|
| `/name <namn>` | Ändrar prompt-prefix till `C:\Users\<namn>>` |
| `/name reset` | Återställer till OS-username |
| `/exit` | Stänger TUI + agent |
| `/stats` | Skickas till agenten |

#### Agent → TUI

```json
{"type":"hello","username":"willi","version":"0.1.0","cwd":"C:\\Users\\willi\\Desktop\\hund-cli"}
{"type":"status","state":"thinking"}
{"type":"token","text":"Kör","message_id":"msg_1"}
{"type":"token","text":" tester","message_id":"msg_1"}
{"type":"token_done","message_id":"msg_1","full_text":"Kör tester nu."}
{"type":"tool_call","tool":"terminal","args":{"command":"uv run pytest"},"id":"call_1","risk":"SAFE"}
{"type":"tool_result","tool_call_id":"call_1","result":"35 passed","exit_code":0}
{"type":"error","message":"API-nyckel saknas"}
{"type":"task_list","tasks":[{"id":"t1","text":"Läs config","status":"completed"},{"id":"t2","text":"Kör tester","status":"in_progress"}]}
{"type":"file_header","path":"hund_cli/agent/loop.py"}
{"type":"stats","context_pct":42,"files_edited":3}
```

### 2.3 Typad State (TypeScript)

```typescript
type AgentState = "idle" | "thinking" | "streaming" | "tool_waiting" | "error" | "confirming";

type TaskStatus = "completed" | "in_progress" | "pending";

interface Task {
  id: string;
  text: string;
  status: TaskStatus;
}

interface TuiState {
  agentState: AgentState;
  tasks: Task[];
  activeFile: string | null;
  contextPct: number;
  filesEdited: number;
  streamingMessageId: string | null;
  streamingBuffer: string;
  pendingApproval: { toolCallId: string; tool: string; args: Record<string, unknown> } | null;
  /** Användarnamnet i prompten — auto-detekteras från OS, kan ändras med /name */
  promptUser: string;
  /** OS-username som auto-detekterades — används för /name reset */
  osUsername: string;
  /** Prompt-prefixet som renderas: C:\\Users\\<promptUser>> */
}
```

## 3. Komponent-för-komponent

### 3.1 Header — FileIndicator

```
┌──────────────────────────────────────────────┐
│ hund_cli/agent/loop.py                       │
└──────────────────────────────────────────────┘
```

- Box med `borderStyle: "round"`
- Visas ENDAST när agenten arbetar med en specifik fil
- Döljs när `activeFile === null`
- Text i cream `#E8E0D5`

### 3.2 TaskList

```
⬢ Working on 3 to-dos

☒ Läs pyproject.toml
▣ Kör pytest
☐ Granska resultat
```

- Hexagon-prefix `⬢` i warm brown `#a09080`
- `☒` completed = dimmad text + eventuell genomstrykning
- `▣` in_progress = bright white, fetstil
- `☐` pending = dimmad
- Endast synlig när `tasks.length > 0`

### 3.3 StateIndicator

```
⬢ Cooking...
```

Roterande text beroende på state:

| State | Text |
|---|---|
| thinking | `⬢ Thinking...` |
| streaming | `⬢ Writing...` (eller dölj, tokens räcker) |
| tool_waiting | `⬢ Running: <tool> <args>` |
| error | `⬢ Error: <msg>` (röd text) |
| idle | Dölj helt |

### 3.4 ChatHistory

Huvudytan. Scrollbar. Renderar:

- **User-meddelanden:** `→ text` i cream
- **Agent-svar:** Markdown-renderad via tree-sitter/plugin
- **Tool calls:** Infogas inline med dimmad bakgrund:
  ```
  ⚙ terminal: uv run pytest
  ```
- **Tool results:** Under tool call, i kodblock:
  ```
  35 passed in 2.34s
  ```
- **Progress bars:** ASCII-staplar i chat-flödet
- **Errors:** Röd text

Token-streaming: när `type: "token"` kommer, appenda till `streamingBuffer` och rendera om. Vid `type: "token_done"`, frys meddelandet.

### 3.5 InputBox

```
┌──────────────────────────────────────────────────┐
│ C:\Users\willi>                                  │
└──────────────────────────────────────────────────┘
```

- Full bredd, `borderStyle: "round"` i warm brown
- **Prompt-prefix:** `C:\Users\<namn>>` i cream — exakt som PowerShell
  - Namnet auto-detekteras från OS vid uppstart (`os.userInfo().username` / `USERNAME`)
  - Skickas till TUI:n via första `hello`-meddelandet från agenten
- **Namnbyte:** `/name <nytt-namn>` i input byter prompt till `C:\Users\<nytt-namn>>`
  - Sparas i session state, ej persistent mellan sessioner
  - `/name reset` återställer till OS-username
- Placeholder: `Add a follow-up` (dimmad, visas till höger efter prompt)
- Enter = skicka `user_input` (utan prompt-prefixet)
- `/` = command mode (visa `/exit /stats /profile /tools /name`)
- History: upp/ned-pil genom tidigare inputs
- Multiline: Shift+Enter

**Prompt-exempel efter `/name william`:**
```
C:\Users\william> kör testerna
```

**Prompt-variant — inte WSL/Linux-stil.** Håll `C:\Users\...>` oavsett OS. Det är Hunds identitet.

### 3.6 Footer

```
Hund · 42% context used · 3 files edited
/ for commands · Esc to interrupt · Ctrl+C to exit
```

- Två rader, dimmad text
- Uppdateras kontinuerligt via `stats`-meddelanden

## 4. Byggplan — faser

### Fas 0: Scaffolding & IPC-verifiering

**Mål:** OpenTUI startar → spawnar Python → skickar/ tar emot JSON-lines

**Leverabler:**
- `tui/` mapp i hund-cli med `bun create tui`-output
- `tui/src/App.tsx` — minimal layout
- `tui/src/ipc.ts` — JSON-lines bridge
- `hund_cli/agent/tui_bridge.py` — Python-sidan av IPC
- Test: starta `bun run tui`, skicka `{"type":"user_input","text":"hej"}`, få tillbaka `{"type":"token","text":"Hej!"}`

**Validering:**
- `bun run tui` startar utan fel
- Python-agenten spawnas som child process
- Ett komplett meddelande går tur/retur

### Fas 1: Chat History + InputBox

**Mål:** Skriv text → enter → syns i chat → agent svarar (Rich-REPL som backend initialt)

**Leverabler:**
- ChatHistory.tsx — scrollbar meddelandelista
- InputBox.tsx — tangentbordsinput, history
- Streaming token-rendering

### Fas 2: StateIndicator + TaskList + FileHeader

**Mål:** Alla UI-element syns, reagerar på IPC-meddelanden

**Leverabler:**
- StateIndicator.tsx — ⬢ Cooking...
- TaskList.tsx — ☒/▣/☐
- FileHeader.tsx — aktiv fil-ruta
- Footer.tsx — metadata
- Task-tracking i Python-agenten (skickar `task_list`-events)

### Fas 3: Tool approval-flow

**Mål:** CONFIRM/DANGEROUS tools → TUI visar approval-dialog → användaren godkänner/nekar

**Leverabler:**
- ConfirmDialog.tsx (inline, inte popup)
- `y`/`n` tangentbordsbindningar
- Auto-approve för SAFE tools (visas bara inline)

### Fas 4: Syntax highlighting + Markdown

**Mål:** Kodblock får syntax highlighting via tree-sitter. Markdown renderas.

**Leverabler:**
- OpenTUI:s inbyggda tree-sitter för kodblock
- Markdown-parser (kan vara enkel — bold, italic, lists, code, headers)
- `ScrollBox` för långa svar

### Fas 5: Progress bars + Polish

**Mål:** ASCII-progress bars, animationer, tangentbordsgenvägar

**Leverabler:**
- ProgressBar-komponent
- `/` command-palette
- Esc = interrupt
- Ctrl+C = exit
- Resize-hantering

## 5. Mappstruktur — tillägg till Hund CLI

```
hund-cli/
├── tui/                          ← NYTT: OpenTUI-frontend
│   ├── package.json
│   ├── tsconfig.json
│   ├── bun.lockb
│   ├── src/
│   │   ├── index.tsx             ← entry point
│   │   ├── App.tsx               ← root layout (flexbox)
│   │   ├── ipc.ts                ← JSON-lines bridge
│   │   ├── state.ts              ← TuiState + reducer
│   │   ├── components/
│   │   │   ├── Header.tsx
│   │   │   ├── TaskList.tsx
│   │   │   ├── StateIndicator.tsx
│   │   │   ├── ChatHistory.tsx
│   │   │   ├── InputBox.tsx
│   │   │   ├── Footer.tsx
│   │   │   └── ConfirmDialog.tsx
│   │   └── types.ts
│   └── ...
├── hund_cli/
│   └── agent/
│       └── tui_bridge.py         ← NYTT: Python IPC-sida
├── pyproject.toml                ← oförändrat
└── TUI_OPENTUI_PLAN.md           ← denna fil
```

## 6. Risker & mitigering

| Risk | Sannolikhet | Mitigering |
|---|---|---|
| OpenTUI är ungt — breaking changes | Medium | Pinna version i package.json |
| Zig-kompilering på Windows | Låg | OpenTUI levereras som prebuilt, Bun hanterar |
| Bun krävs (inte Node) | — | `bun` är en dependency, inte valfritt |
| IPC latency vid streaming | Låg | JSON-lines är minimal overhead |
| Python-agenten kraschar | Medium | TUI:n detekterar exit code, visar fel, kan restarta |
| Encoding (åäö) | Låg | UTF-8 tvingas i Python (redan gjort) + Bun är UTF-8 native |

## 7. Varför INTE:

| Alternativ | Orsak till avslag |
|---|---|
| Python (Textual/prompt-toolkit/Rich) | 7 fail. Windows är sekundär plattform. |
| Ink (React) | Bra men ren JS — Zig-kärnan i OpenTUI ger native prestanda |
| Ratatui (Rust) | Bra men inlärningskurva + ingen flexbox/tree-sitter out-of-box |
| Go Bubble Tea | Bra men OpenTUI har bättre komponent-modell (React) |
| Webbaserad (Tauri) | Överkurs för CLI-agent |
| Ingen TUI alls | Rich-REPL är en fallback, inte en produkt |

---

*Denna plan är levande. Uppdateras under byggets gång.*
*Designspecen från `hund_consolidated_superprompt.md` (Obsidian) är auktoritativ för utseendet.*

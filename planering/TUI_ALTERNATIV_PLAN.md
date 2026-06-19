# Hund CLI — TUI: Alternativ till Python

> Skapad: 2026-06-19
> Status: Planeringsfas. Python TUI har getts upp (7 fail). Denna fil utforskar ALLA alternativ.

---

## 1. Nuläge

- Core engine: Python 3.11, Typer + Rich, `uv run hund` → REPL utan TUI
- Tidigare försök: `prompt-toolkit` (7 fail, feature branch `feat/prompt-toolkit-ui` övergiven)
- Tidigare försök: hybrid Node.js neo-blessed + Python agent_bridge.py IPC
- Python på Windows: `python` finns EJ direkt — endast `uv run python`
- Maskin: Windows 11, 16GB RAM, GTX 980 Ti (4GB VRAM), 8 CPU-kärnor
- Python TUI på Windows är markerat som "ALDRIG" i memory

## 2. Krav för TUI

| Krav | Prioritet |
|---|---|
| Fungerar på Windows 11 (native, inte WSL) | KRITISKT |
| Kan kommunicera med Python-agenten (core engine) | KRITISKT |
| Responsiv input (ingen latency, direkt feedback) | HÖG |
| Syntax highlighting + markdown-rendering | HÖG |
| Streaming output (tokens syns i realtid) | HÖG |
| Scrollbar historik | MEDEL |
| Tangentbordsnavigering (vim/emacs) | MEDEL |
| Färger/teman (mörkt ljust) | MEDEL |
| Cross-platform (Windows + macOS + Linux) | LÅG (just nu endast Windows) |

## 3. Alla alternativ — översikt

### 3.1 Rust-baserad TUI → Python IPC

**Bibliotek:** [Ratatui](https://ratatui.rs/) (tidigare tui-rs)

| Egenskap | Värde |
|---|---|
| Språk | Rust |
| Mognad | Mycket hög — används av välkända projekt |
| Widgets | Block, List, Table, Paragraph, Tabs, Gauge, Sparkline, Chart, Scrollbar, Calendar |
| Input | Tangentbord, mus |
| Färger | Fullt RGB + ANSI |
| Rendering | Omedelbar diff-rendering (endast ändrade celler ritas om) |
| Cross-platform | Windows, macOS, Linux (crossterm backend) |
| Dokumentation | Utmärkt + tutorials + exempel |
| Community | Stor, aktiv |

**Arkitektur:**
```
┌──────────────┐   JSON-lines     ┌──────────────────┐
│  Rust TUI    │ ◄──────────────► │  Python agent    │
│  (ratatui)   │   stdin/stdout   │  (core engine)   │
└──────────────┘                  └──────────────────┘
```

**Fördelar:**
- Kompileras till en enda `.exe` (ingen runtime)
- Snabbt — sub-ms rendering
- Windows-first med crossterm
- Kan buntas med `uv`-baserad Python-launcher
- Inga Node.js-beroenden

**Nackdelar:**
- William måste lära sig Rust (eller delegera all Rust-kod)
- Kompileringstid
- Två separata kodbaser att underhålla

**Build-kedja:**
```bash
cargo build --release          # → target/release/hund-tui.exe
# Buntas med Python-agenten
```

---

### 3.2 Node.js TUI → Python IPC

**Bibliotekalternativ:**

#### A. neo-blessed (redan testat)

| Egenskap | Värde |
|---|---|
| Språk | JavaScript/Node.js |
| Status | Testat i tidigare iteration |
| Widgets | Box, Text, List, Form, Table, Progress, Layout |
| Rendering | Canvas-baserad, terminal-celler |
| Problem | `{dim}` är ej giltig tag → måste använda `{#666-fg}text{/}` |

#### B. Ink (React för terminal)

| Egenskap | Värde |
|---|---|
| Språk | TypeScript/JSX |
| Status | Mycket aktiv, 27k+ stjärnor |
| Widgets | Box, Text, Newline, Spinner, SelectInput, TextInput, Table, Transform |
| Paradigm | React-komponenter → terminal |
| Flexbox | Ja — layout som CSS flexbox |
| Färger | Fullt ANSI + hex |
| Input | useInput-hook |
| Streaming | Ja, via state-uppdateringar |

**Arkitektur (Ink):**
```
┌──────────────┐   JSON-lines     ┌──────────────────┐
│  Node.js TUI │ ◄──────────────► │  Python agent    │
│  (Ink)       │   stdin/stdout   │  (core engine)   │
└──────────────┘                  └──────────────────┘
```

**Fördelar (Ink):**
- React-paradigm — komponent-baserad
- Flexbox layout — lätt att bygga komplex UI
- Stort ekosystem (npm)
- TypeScript för typsäkerhet
- Fungerar på Windows via node

**Nackdelar:**
- Node.js måste vara installerat
- React + terminal = udda koncept för vissa
- npm-beroenden
- JavaScript — fortfarande två språk

---

### 3.3 Go TUI → Python IPC

**Bibliotek:** [Bubble Tea](https://github.com/charmbracelet/bubbletea) (Elm Architecture for terminal)

| Egenskap | Värde |
|---|---|
| Språk | Go |
| Mognad | Mycket hög — Charmbracelet-ekosystemet |
| Widgets | Lip Gloss (styling), Bubbles (komponenter) |
| Paradigm | Elm Architecture (Model, Update, View) |
| Rendering | Full terminal control |
| Cross-platform | Windows, macOS, Linux |
| Kompilering | Statisk binär (ingen runtime) |

**Komponenter i ekosystemet:**
- `bubbletea` — TUI-framework
- `lipgloss` — styling/colors
- `bubbles` — färdiga widgets (textinput, viewport, spinner, paginator, table, filepicker)
- `glamour` — markdown-rendering i terminal
- `huh` — formulär/input byggare

**Arkitektur:**
```
┌──────────────┐   JSON-lines     ┌──────────────────┐
│  Go TUI      │ ◄──────────────► │  Python agent    │
│  (bubbletea) │   stdin/stdout   │  (core engine)   │
└──────────────┘                  └──────────────────┘
```

**Fördelar:**
- Enkel binär, ingen runtime
- `glamour` renderar markdown direkt i terminal (perfekt för agent-svar)
- Elm Architecture är enkel och förutsägbar
- Lip Gloss styling är deklarativ och kraftfull
- Windows-stöd förbättras stadigt
- Mycket aktiv community

**Nackdelar:**
- Go-syntax kan vara verbose
- Windows-stödet är nyare (men fungerande)
- Tre språk i projektet (Python + Go + ?)

---

### 3.4 Zig/C TUI — direkt FFI till Python

**Bibliotek:** [Notcurses](https://github.com/dankamongmen/notcurses) eller [libvaxis](https://github.com/rockorager/libvaxis) (Zig)

Detta är den mest extrema vägen: skriv TUI i C/Zig och anropa Python direkt via FFI.

| Egenskap | Värde |
|---|---|
| Språk | C eller Zig |
| Prestanda | Maximal — direkt terminal I/O |
| Komplexitet | Mycket hög |
| Widgets | Inga färdiga — allt måste byggas |

**Bedömning:** EJ REKOMMENDERAT. För mycket arbete, för lite vinst. Endast relevant om prestanda är absolut kritiskt (vilket det inte är för en CLI-agent).

---

### 3.5 Nytt Python-försök — med annan approach

**Bibliotek:** [Textual](https://textual.textualize.io/) (byggt av Rich-skaparna)

| Egenskap | Värde |
|---|---|
| Språk | Python |
| Widgets | Button, Checkbox, DataTable, DirectoryTree, Footer, Header, Input, Label, ListView, Markdown, Placeholder, ProgressBar, RadioSet, Select, Sparkline, Switch, Tabs, TextArea, Tree |
| CSS-layout | Ja — terminal-CSS |
| DOM | Ja — widget-träd |
| Keybindings | Ja, deklarativt |
| Windows-stöd | Förbättras men är fortfarande sekundärt |
| Async | Full asyncio-integration |

**Varför det misslyckades förut:**
- Windows är secondary target för Textual
- Prompt-toolkit + asyncio + Windows-terminal = problem
- Rich fungerar, men Rich är output-only, inte interaktiv TUI

**Bedömning:** INTE REKOMMENDERAT. Python TUI på Windows har bevisats opålitligt i detta projekt (7 fail). Om Textual ska testas igen krävs:
- Textual >= 1.0 med explicit Windows-garanti
- Dedikerad Windows-testmiljö
- Max 1 försök — failar det → permanent död för Python TUI

---

### 3.6 Webbaserad UI (electron-liknande)

**Bibliotek:** [Tauri](https://tauri.app/) (Rust + web frontend)

| Egenskap | Värde |
|---|---|
| Frontend | HTML/CSS/JS (valfritt ramverk) |
| Backend | Rust |
| Storlek | ~3MB (vs Electron ~120MB) |
| Cross-platform | Windows, macOS, Linux |
| IPC | Inbyggd Rust ↔ JS bridge |

**Arkitektur:**
```
┌──────────────────────┐
│  Tauri-fönster        │
│  ┌────────────────┐  │   JSON-lines     ┌──────────────────┐
│  │  Web UI        │  │ ◄──────────────► │  Python agent    │
│  │  (JS/HTML/CSS) │  │   Rust bridge    │  (core engine)   │
│  └────────────────┘  │                  └──────────────────┘
└──────────────────────┘
```

**Fördelar:**
- Full kontroll över utseende (CSS)
- Markdown-rendering trivialt (valfri JS-bibliotek)
- Syntax highlighting enkelt (highlight.js/Prism)
- Kan återanvända webbkomponenter
- Tauri är lättviktigt

**Nackdelar:**
- Inte en "ren" terminal-UI
- Kräver fönsterhantering (inte inline i terminal)
- Tre språk (Rust + JS + Python)
- Överkurs för en CLI-agent

**Bedömning:** BARA om William explicit vill ha ett GUI-fönster istället för terminal. Inte default.

---

### 3.7 Ingen TUI — förbättrad Rich-REPL

Istället för en full TUI: förbättra den befintliga Rich-baserade REPL:en med bättre formattering.

| Komponent | Möjlig förbättring |
|---|---|
| Input | `rich.prompt.Prompt` med history |
| Output | `rich.markdown.Markdown` för agent-svar |
| Streaming | `rich.live.Live` för token-ström |
| Layout | `rich.layout.Layout` för split-view |
| Progress | `rich.progress.Progress` för tool-anrop |
| Syntax | `rich.syntax.Syntax` för kodblock |
| Paneler | `rich.panel.Panel` för meddelande-bubblor |

**Fördelar:**
- Ingen ny kodbas
- Fungerar redan på Windows
- Rich är redan en dependency
- Minimal risk

**Nackdelar:**
- Inte en "riktig" TUI — ingen fullskärm, inga widgets
- Ingen tangentbordsnavigering utöver readline
- Begränsad layout

---

## 4. Rekommendation — rankad

| Rank | Alternativ | Varför |
|---|---|---|
| **1** | **Rust Ratatui + Python IPC** | Snabbast, pålitligast på Windows, singel .exe, inga runtime-beroenden. Mognaste TUI-biblioteket. |
| **2** | **Go Bubble Tea + Python IPC** | Perfekt markdown via Glamour, Elm Architecture enkel att resonera kring, statisk binär. |
| **3** | **Node.js Ink + Python IPC** | React-komponenter i terminal, flexbox-layout, William har redan Node.js installerat. Störst widget-utbud. |
| **4** | **Förbättrad Rich-REPL** | Ingen ny tech stack, lägst risk, men också minst kapabel. Kan vara en språngbräda. |
| **5** | **Webbaserad (Tauri)** | Maximal kontroll över utseende, men överkurs. |

### Detaljerad jämförelse: topp 3

| Kriterium | Ratatui (Rust) | Bubble Tea (Go) | Ink (Node.js) |
|---|---|---|---|
| Windows-stöd | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Markdown-rendering | Manuell/plugin | 🔥 Glamour (inbyggd) | Bibliotek |
| Syntax highlighting | Manuell/syntect | Chroma (inbyggd) | highlight.js |
| Prestanda | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Kompilat/bundle | 1 .exe (~3MB) | 1 .exe (~8MB) | node + node_modules |
| Inlärningskurva | Brant (Rust) | Medium (Go) | Låg (JS/React) |
| IPC till Python | Manuell stdin/stdout | Manuell stdin/stdout | child_process |
| Widget-utbud | 15+ widgets | 10+ widgets | 20+ widgets (React) |
| Community/exempel | Mycket stort | Stort | Stort |
| Debugging | Svårt (Rust) | Medium | Lätt (Node) |

## 5. Arkitektur — oavsett val

Oavsett vilket språk TUI:n byggs i, är arkitekturen densamma:

```
┌─────────────────────────────────────────┐
│              TUI-process                 │
│  ┌──────────┐      ┌───────────────┐    │
│  │  UI-lagret│ ───► │ IPC-brygga    │    │
│  │ (rendering│ ◄─── │ (JSON-lines)  │    │
│  │  input)   │      │               │    │
│  └──────────┘      └───────┬───────┘    │
└─────────────────────────────┼───────────┘
                              │ stdin/stdout
                              │ eller socket
                              │
┌─────────────────────────────┼───────────┐
│         Python-agentprocess             │
│                      ┌──────▼───────┐   │
│                      │ IPC-brygga    │   │
│                      │ (JSON-lines)  │   │
│                      └──────┬───────┘   │
│  ┌──────────┐      ┌───────▼──────┐    │
│  │ Tools    │◄─────┤ Agent Loop   │    │
│  │ (file,   │      │ (core engine)│    │
│  │  term)   │─────►│              │    │
│  └──────────┘      └──────┬───────┘    │
│                      ┌────▼──────┐     │
│                      │ Provider   │     │
│                      │ (LLM API)  │     │
│                      └────────────┘     │
└─────────────────────────────────────────┘
```

### IPC-protokoll — JSON-lines

Varje meddelande är en JSON-rad, avslutad med `\n`:

**TUI → Agent:**
```json
{"type": "user_input", "text": "vad är klockan?", "session_id": "abc123"}
{"type": "tool_approval", "tool_call_id": "call_1", "approved": true}
{"type": "command", "command": "exit"}
```

**Agent → TUI:**
```json
{"type": "token", "text": "Klockan", "message_id": "msg_1"}
{"type": "token_done", "message_id": "msg_1", "full_text": "Klockan är 14:30."}
{"type": "tool_call", "tool": "terminal", "args": {"command": "date"}, "id": "call_1", "risk": "SAFE"}
{"type": "tool_result", "tool_call_id": "call_1", "result": "Fre 19 jun 2026 14:30:00 CEST"}
{"type": "error", "message": "API-nyckel saknas"}
{"type": "status", "state": "idle" | "thinking" | "streaming" | "tool_waiting" | "error"}
```

## 6. Nästa steg

1. **Beslut från William** — välj en av rank 1–4
2. **Prototyp** — bygg minimal "hello world" TUI i valt språk + IPC till Python
3. **Testa på Windows** — verifiera att TUI:n startar och kan skicka/ta emot meddelanden
4. **Första feature** — streaming token-rendering
5. **Iterativ utbyggnad** — tool approval, syntax highlighting, markdown, scrollbar

## 7. Risker

| Risk | Mitigering |
|---|---|
| IPC blir flaskhals | Använd shared memory eller socket om stdin/stdout är för långsamt |
| Python-process hantering | TUI:n spawnar Python som child process; restart vid krasch |
| Windows-terminal quirks | Testa tidigt med Windows Terminal, cmd, och PowerShell |
| Två kodbaser divergerar | Dela IPC-schemat som enda interface; testa mot det |
| Encoding-problem (åäö) | Tvinga UTF-8 i båda processer (görs redan i Python via main.py) |

---

*Planen är levande. Uppdateras efter beslut och under byggets gång.*

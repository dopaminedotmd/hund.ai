# hund.ai

▄▄                   ▄▄         ████    ████      
██                   ██           ████████        
████▄ ██ ██ ████▄ ▄████         ██████████        
██ ██ ██ ██ ██ ██ ██ ██       ████████████        
██ ██ ▀██▀█ ██ ██ ▀████ ██      ██████████        
                                  ████████        
                                  ██████████    ██
                                  ████████████  ██
                                  ████████████████
                                  ████████████████
                                  ██  ██  ██████  



> **A self-learning, local-first terminal companion.**
> Hund reads your machine and workspace, develops specialized skills from your real workflow, and helps you build without generic boilerplate or hallucinated assumptions.

---

## What makes Hund unique

Most AI assistants reset every turn or rely on generic web prompts. Hund is built differently:

1. **System & Workspace Awareness**: Upon startup, Hund profiles your real machine environment (OS, architecture, shell, installed runtimes, and git state). Hund never gives generic Linux commands on a Windows terminal or guesses what packages you have installed.
2. **Specific, Evidence-Based Advice**: Hund observes before assuming. When you ask about a project, Hund checks actual repository files, lockfiles, and configs rather than guessing library versions.
3. **Adaptive Skill Synthesis**: As you work, Hund identifies recurring patterns and procedures. When proven knowledge repeats across tasks and sessions, Hund's skill factory compiles declarative, sandbox-tested skills tailored specifically to your projects.
4. **The Six-Slot Skill Vault**: Six specialized domain skills work together in active hot-slots, while motor skills remain permanently pinned in the background. You can equip, park, and inspect skills directly in the TUI.
5. **Real XP & Progression**: Hund earns experience points from verified knowledge discoveries and cross-session reuses. No XP is awarded for trivial tool calls—only for validated, empirical learning.
6. **Base Stats & Character Sheet**: Base attributes (**Clarity**, **Precision**, **Efficiency**, **Endurance**) and level tiers evolve based on real telemetry, verified tasks, and session velocity.

---

## Quick Start

### 1. Installation

The fastest way to install Hund globally is via [`uv`](https://github.com/astral-sh/uv):

```bash
uv tool install git+https://github.com/dopaminedotmd/hund.ai.git
```

To run from a local source clone:

```bash
git clone https://github.com/dopaminedotmd/hund.ai.git
cd hund.ai
uv sync
uv run hund
```

### 2. Configure Your API Key

You can configure your provider and API key interactively using the built-in setup wizard:

```bash
hund setup
```

Or configure via environment variable:

```powershell
# Windows PowerShell
$env:HUND_API_KEY = "sk-..."

# Linux / macOS
export HUND_API_KEY="sk-..."
```

Hund natively supports OpenRouter, DeepSeek, and custom OpenAI-compatible endpoints. In the fullscreen interface, you can also press `/model` and `k` to store keys securely in your operating system's native credential vault (Windows Credential Manager / macOS Keychain / Linux Secret Service).

### 3. Launch Hund

```bash
hund
```

---

## Fullscreen TUI & Controls

Hund features a full-screen terminal interface with keyboard-first navigation:

| Command | Action |
|---|---|
| `/stats` | Open character sheet, base stats, XP bars, and 7-day velocity |
| `/skills` | Browse, equip, and park active and vaulted domain skills |
| `/tools` | Inspect registered tools and constitutional motor safety rules |
| `/usage` | View token consumption heatmap and session telemetry |
| `/theme` | Change visual theme (defaults to Marshmallow) |
| `/model` | Switch model presets or configure custom endpoints |
| `/copy` | Copy last assistant response to system clipboard |
| `/retry` | Regenerate last turn |
| `/clear` | Clear output history from screen |
| `/exit` | Exit Hund (`/quit` or `Ctrl+D`) |

**Navigation Keys:**
- `↑` / `↓` : Move focus in lists and menus.
- `Enter` : Select item or confirm input.
- `Esc` : Instant back navigation (nested modal → modal → destination view → chat).
- `Mouse Wheel` : Scroll output and panels smoothly.

---

## Security & Epistemic Integrity

Hund is built with strict privacy and trust boundaries:

- **Local Storage**: All learning events, knowledge units, XP ledgers, and session histories stay on your local disk under `~/.hund/`.
- **Credential Protection**: API keys and secrets are never committed to disk in plaintext, never logged in chat history, and never passed to subagents.
- **Safety Levels**: File writes, deletions, and arbitrary terminal commands are gated with interactive approval modals (`[y] Approve`, `[e] Edit`, `[n] Deny`).
- **Web Safety**: Web requests enforce strict SSRF guards, private IP blocking, domain pinning, resource size caps, and automatic secret redaction.

---

## Repository

- **GitHub Remote**: [https://github.com/dopaminedotmd/hund.ai.git](https://github.com/dopaminedotmd/hund.ai.git)
- **License**: MIT

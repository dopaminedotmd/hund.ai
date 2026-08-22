# hund

> A local-first, hardware-aware terminal agent that learns, remembers, and levels up with you.

hund is software executing inside your machine. It connects to any model provider via BYOK (Bring Your Own Key) and works directly in your terminal as an operative companion.

Unlike generic chatbots, hund is built to feel like an extension of your own system: sensing your hardware, managing memory locally, tracking measurable growth, synthesizing new skills from your workflow, and executing tools within strict security boundaries.

---

## What Makes hund Different

### 1. Hardware & System Telemetry
hund reads the machine upon startup (`hund doctor`). It inspects CPU cores, RAM, GPU VRAM, shell environment, and installed developer toolchains (git, python, uv, node). Regardless of what task or question you bring, hund adapts its advice and execution strategies to your machine's exact hardware specifications and available toolchains.

### 2. Autonomous Skill Synthesis & Refinement
hund actively observes the domains and workflows you spend time in. When a specific domain or task type is used frequently enough, hund identifies the pattern and creates a brand-new, dedicated skill for it. As you keep working, hund continuously sharpens and updates these skills to become an increasingly effective specialist for your exact needs.

At higher experience levels, hund goes further: conducting targeted web research to scan external patterns, libraries, and best practices, integrating valuable techniques directly into its own skills to accelerate its growth and precision.

### 3. Base Stats & Measurable Growth
Every session contributes to hund's capabilities. Performance and experience are tracked across five core attributes with live ASCII progress bars calculated directly from telemetry stored in your local SQLite database:

```
Clarity [████████░░]
```
- **Clarity**: Measures communication efficiency and Turns Per Task (TPT).  
  *How it improves:* Getting tasks solved on the first attempt with minimal back-and-forth ambiguity or prompt clarification.

```
Precision [██████░░░░]
```
- **Precision**: Measures tool execution accuracy and verification success rate.  
  *How it improves:* Writing syntactically valid edits, executing commands with zero runtime errors, and passing unit tests on the first try.

```
Efficiency [█████████░]
```
- **Efficiency**: Measures token economy and context window optimization.  
  *How it improves:* Formulating high-signal responses, avoiding redundant iterations, and keeping token consumption lean.

```
Endurance [████░░░░░░]
```
- **Endurance**: Measures sustained multi-turn workflow depth before context degradation.  
  *How it improves:* Navigating long, complex engineering sessions, heavy refactorings, and multi-file debugging tasks without losing coherence.

```
Mastery [███████░░░]
```
- **Mastery**: Measures total breadth and depth of verified domain expertise and synthesized skills.  
  *How it improves:* Successfully synthesizing, verifying, and promoting new skills and domain knowledge through actual task completion.


#### Learned Domain Skill Example

When you work heavily in a specialized framework or tech stack, hund synthesizes a domain skill with its own XP progression:

```
FastAPI & Async SQLite   [███████░░░]
```

- **Discovery:** After repeatedly assisting with async endpoints, Pydantic validations, and database session lifecycles, hund recognizes the pattern and synthesizes `fastapi-async-sqlite.json`.
- **Specialization:** Each time you write endpoints, run schema migrations, or optimize async connection pools, hund tracks successful tool executions and sharpens the skill's procedural steps.
- **Web-Augmented Leveling:** As the skill progresses into higher tiers, hund autonomously scans web documentation for new release features (e.g. SQLAlchemy 2.0 async paradigms, Pydantic v2 migrations) and incorporates verified patterns directly into its local skill definition.

Every time hund improves its skillset, acquires new domain knowledge, or self-updates its procedural instructions, this progression is visualized directly in the terminal through the filling progress bars. You can watch hund grow into a sharper specialist with every task completed.


### 4. Skill Vault
hund equips up to 6 active capability packs at a time, keeping system prompts focused and token-efficient. Skills can be swapped in and out of the vault on the fly:

- **Security & Safety**: shell command guards, git push verification, external data isolation.
- **Engineering Workflows**: Python project inspection, systematic debugging, context condensation.
- **Vault Management**: `/skills vault`, `/skills equip <name>`, `/skills park <name>`, `/skills swap <old> <new>`.

### 5. Self-Improvement with Human Gate
hund tracks knowledge gaps during difficult tasks. When repeated friction occurs, it drafts structured skill proposals to expand its abilities. Every update requires explicit user review: hund proposes, you decide.

### 6. Trusted Computing Base (TCB)
Security is enforced by code, not polite prompt instructions. A hardened PermissionEngine classifies all operations into `SAFE`, `WRITE`, `CONFIRM`, `DANGEROUS`, and `BLOCKED`. High-risk commands always pause for interactive confirmation.

---

## Installation

### Prerequisites
- Python 3.11+
- Windows, macOS, or Linux
- [uv](https://github.com/astral-sh/uv) (recommended)

### Windows (Quickstart)

```powershell
git clone https://github.com/dopaminedotmd/hund.ai
cd hund.ai
uv sync --extra dev
setx HUND_API_KEY "sk-..."      # your API key (DeepSeek, OpenAI, etc.)
.venv\Scripts\hund.exe          # starts the REPL
```

### macOS / Linux

```bash
git clone https://github.com/dopaminedotmd/hund.ai
cd hund.ai
uv sync --extra dev
export HUND_API_KEY="sk-..."
.venv/bin/hund
```

---

## CLI & REPL Commands

```bash
hund             # launch interactive streaming REPL
hund doctor      # inspect hardware telemetry and developer toolchains
hund stats       # view base stats and weekly velocity
hund skills      # view equipped skills and active slots
hund memory show # view persistent user and environment profiles
```

### Slash Commands in REPL

| Command | Action |
|---|---|
| `/help` | Open command palette |
| `/stats` | View character card and stat progression |
| `/skills` | List equipped skills (max 6 active slots) |
| `/skills vault` | View available skills in the vault |
| `/skills equip <name>` | Equip a skill from vault |
| `/skills park <name>` | Move an active skill to vault |
| `/skills swap <old> <new>` | Atomically swap equipped skills |
| `/tools` | List registered tools and risk levels |
| `/doctor` | Run live hardware diagnostics |
| `/usage` | View token consumption across sessions |
| `/compress` | Manually compress active context window |
| `/theme` | Switch visual terminal palette |
| `/export` | Export session history to Markdown or JSON |
| `/exit` | Exit the REPL |

---

## Architecture Overview

- **`hund/main.py`**: Typer CLI entry point; invoking with no arguments starts `hund/ui/repl.py`.
- **`hund/agent/loop.py`**: Agent loop (TCB): turn sequencing, context compression, tool dispatch.
- **`hund/agent/safety.py`**: PermissionEngine (TCB): risk classification and terminal blocklist enforcement.
- **`hund/agent/tool_dispatch.py`**: Central dispatch gate (TCB) with per-session allowlist isolation.
- **`hund/learning/redactor.py`**: Secret and PII redactor (TCB).
- **`hund/skills/`**: 11 declarative JSON skills, SkillVault manager, trigger matcher, and invariant validator.
- **`hund/ui/`**: Pure Python terminal interface (`theme.py`, `render.py`, `output.py`, `commands.py`, `repl.py`).
- **`hund/assets/hund-system/hund.md`**: Canonical persona injected into system prompts.

All session history, memory, and stats remain strictly local in `%LOCALAPPDATA%/hund/` (or `~/.local/share/hund/`).

---

## Providers

hund uses standard OpenAI-compatible API schemas. Bring your own key from:
- DeepSeek (`deepseek-v4-pro`, `deepseek-chat`)
- OpenAI (`gpt-4o`, `o3-mini`)
- Anthropic, Gemini, OpenRouter, or local engines (Ollama, vLLM).

Configure via `%LOCALAPPDATA%/hund/config.json` or environment variables:

```bash
HUND_API_KEY="sk-..."
HUND_BASE_URL="https://api.deepseek.com"
HUND_MODEL="deepseek-v4-pro"
```

---

## License

Apache-2.0.

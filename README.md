# hund.ai

> An installable, local-first, self-improving CLI agent engine living in the hardware.

hund is software executing inside physical hardware.
hund is designed as an operative extension of the user's intellect.
hund stands alongside the user at the terminal: observing the environment, inspecting telemetry, executing commands within safe boundaries, and retaining persistent memory across sessions.

Documentation:
- [MASTER_PLAN.md](file:///docs/plans/MASTER_PLAN.md): Roadmap and master architecture.
- [architecture.md](file:///docs/reference/architecture.md): Layered architecture and TCB boundaries.
- [HUND_COMPLETE_BIBLE.md](file:///HUND_COMPLETE_BIBLE.md): Canonical constitution and persona.
- [AGENTS.md](file:///AGENTS.md): Guide for AI agents and contributors.

---

## What hund Is

hund is not a generic chatbot.
hund is a local CLI companion.
hund scans the host machine upon startup, maps available tools, respects strict security rules, and maintains a local knowledge base.
hund suggests, assists, and proposes improvements.
hund never self-publishes modifications: all self-improvements pass through an explicit human gate.

---

## Features

- **Streaming Agent REPL**: Pure Python terminal interface built with prompt_toolkit, real-time token streaming, and clean boxed output.
- **Boxed CLI GUI**: Compact, single-line and multiline cards for tool calls, results, confirmations, and slash commands without emojis or full-screen disruption.
- **11 Builtin JSON Skills & Skill Vault**: Declarative JSON skills with a 6-slot active capacity limit, trigger matching, and slot swapping (`/skills vault`, `/skills equip`, `/skills park`, `/skills swap`).
- **Trusted Computing Base (TCB)**: Inviolable permission engine categorizing tool operations into SAFE, WRITE, CONFIRM, DANGEROUS, and BLOCKED.
- **Hardware-Aware Doctor**: Direct environment sensing (CPU, RAM, GPU, OS, developer toolchains) that grounds model behavior.
- **RPG Progression & Base Stats**: Five core attributes (Clarity, Precision, Efficiency, Endurance, Mastery), weekly velocity tracking, and tier advancement.
- **Persistent Local Memory**: Memory saved to user.md and environment.md in HundHome (%LOCALAPPDATA%/hund/).
- **Self-Improvement with Human Gate**: Structured gap event tracking, study proposals, and skill synthesis requiring interactive human approval.

---

## Installation (Dev, Windows)

```powershell
git clone https://github.com/dopaminedotmd/hund.ai
cd hund.ai
uv sync --extra dev
setx HUND_API_KEY "sk-..."      # open a new terminal afterwards
.venv\Scripts\hund.exe --version   # prints: hund 0.1.0
.venv\Scripts\hund.exe             # starts the REPL
```

Note: uv run hund can encounter "uv trampoline failed" on Windows due to file locking. Use `.venv\Scripts\hund.exe` or `.venv\Scripts\python.exe -m hund.main`.

---

## Verification & Tests

```powershell
.venv\Scripts\python.exe -m pytest -q --tb=no   # 616 passed, 1 skipped, 0 failed
```

---

## Quickstart & Commands

```powershell
hund             # starts the interactive streaming REPL
hund repl        # same as above
hund --version   # prints version 0.1.0
hund doctor      # hardware and environment diagnosis
hund stats       # base stats and RPG character card
hund skills      # list equipped active skills
hund memory show # inspect user.md and environment.md
```

### REPL Slash Commands

Within the interactive REPL:
- `/help` : display command palette
- `/stats` : render full character sheet and velocity
- `/skills` : list active equipped skills (max 6 active slots)
- `/skills vault` : inspect available skills in the vault
- `/skills equip <name>` : equip a skill from the vault
- `/skills park <name>` : park an active skill into the vault
- `/skills swap <old> <new>` : swap an active skill for a vaulted skill
- `/tools` : view registered tools and base risk ratings
- `/doctor` : run hardware diagnostics
- `/usage` : inspect token consumption
- `/compress` : compress active context window
- `/theme` : switch visual color themes
- `/export` : export current conversation session
- `/exit` : quit the REPL

---

## How It Works

- **hund/main.py**: Typer CLI entry point; launching with no arguments opens `hund/ui/repl.py`.
- **hund/agent/loop.py**: Agent execution loop (TCB): turn sequencing, context compression, tool dispatch.
- **hund/agent/safety.py**: PermissionEngine (TCB): risk classification and terminal blocklist enforcement.
- **hund/agent/tool_dispatch.py**: Central dispatch gate (TCB) with per-session allowlist isolation.
- **hund/learning/redactor.py**: Secret and PII redactor (TCB).
- **hund/skills/**: 11 declarative JSON skills, SkillVault manager, trigger matcher, and invariant validator.
- **hund/ui/**: Terminal interface (`theme.py`, `render.py`, `output.py`, `commands.py`, `repl.py`).
- **Persona**: `hund/assets/hund-system/hund.md` injected directly into system prompts.
- **State**: `HundHome = %LOCALAPPDATA%/hund/` (`memory/`, `brain/`, `sessions/`, `logs/`).

---

## License

Apache-2.0.

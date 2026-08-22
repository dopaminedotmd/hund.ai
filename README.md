# Hund.ai

> **IMPORTANT:** Read [PRODUCT_BOUNDARY.md](file:///PRODUCT_BOUNDARY.md) first. This repository contains two products sharing the name Hund.ai:
>
> **Product A** — Styde SaaS Dashboard (Next.js) in `apps/dashboard/`
> **Product B** — Hund Core CLI (Python 3.11+) in `hund/` + `dashboard/`

Hund.ai is an autonomous AI companion and self-improving CLI agent engine. As a CLI, Hund lives directly inside the host machine's hardware, analyzes its environment upon launch, executes commands within strict security boundaries, retains persistent memory, and features a rich boxed CLI GUI.

Documentation:
- [MASTER_PLAN.md](file:///docs/plans/MASTER_PLAN.md) — Master roadmap, cloud orchestration, security model.
- [architecture.md](file:///docs/reference/architecture.md) — Layered architecture, TCB contracts, state isolation.
- [HUND_COMPLETE_BIBLE.md](file:///HUND_COMPLETE_BIBLE.md) — Canonical persona, constitution, dynamic response matrix.
- [AGENTS.md](file:///AGENTS.md) — Developer guidelines for AI agents & contributors.

---

## Current Status: v0.1.0

Features in Hund Core:
- **Streaming Agent REPL:** Pure Python terminal UI with `prompt_toolkit`, real-time token streaming, and boxed command HUDs.
- **Trusted Computing Base (TCB):** Hardened PermissionEngine classifying all operations (`SAFE`, `WRITE`, `CONFIRM`, `DANGEROUS`, `BLOCKED`).
- **11 Built-in JSON Skills:** Declarative capability packs with executable verification and positive `BANNED_ACTIONS` validation.
- **Hardware-Aware Doctor:** Live hardware inspection (CPU, RAM, GPU, OS, developer toolchains) grounding agent behavior.
- **RPG Progression & Stats:** 5 base attributes (`Clarity`, `Precision`, `Efficiency`, `Endurance`, `Mastery`), velocity metrics, and tier elevations.
- **Self-Improvement Loop:** Proposal generation, gap event detection, and human-gated skill synthesis.
- **Telemetry & Traceability:** Append-only JSONL event stream and FTS5 session search.

---

## Installation (Dev, Windows)

```powershell
git clone https://github.com/dopaminedotmd/hund.ai
cd hund.ai
uv sync --extra dev
setx HUND_API_KEY "sk-..."      # Open a new terminal afterwards
.venv\Scripts\hund.exe --version   # Prints: hund 0.1.0
.venv\Scripts\hund.exe             # Starts the REPL
```

> [!NOTE]
> `uv run hund` can encounter `"uv trampoline failed"` on Windows due to file locking. Use `.venv\Scripts\hund.exe` or `.venv\Scripts\python.exe -m hund.main`.

---

## Testing

Run the full pytest suite:

```powershell
.venv\Scripts\python.exe -m pytest -q --tb=no   # 610 passed, 1 skipped, 0 failed
```

---

## Running the CLI

```powershell
hund             # Starts the streaming REPL (prompt_toolkit)
hund repl        # Same as above
hund --version   # 0.1.0
hund doctor      # Hardware + environment diagnosis
hund stats       # Base stats & RPG character card
hund skills      # List equipped & available skills
hund memory show # Inspect user.md + environment.md
```

### REPL Slash Commands

Within the interactive shell, use:
- `/help` — Display command palette
- `/stats` — Render full character sheet & weekly velocity
- `/skills` — List active skills and safety levels
- `/tools` — View available tools & base risk ratings
- `/doctor` — Run full hardware diagnostics
- `/usage` — Show session & global token consumption
- `/compress` — Force context compression
- `/theme` — Switch UI color themes
- `/export` — Export active session history
- `/exit` — Quit the session

---

## Updates (Two Tracks)

- **Development:** `git pull && uv sync`, followed by `.venv\Scripts\python.exe -m pytest`.
- **Signed Release:** `hund/updater/` (`manifest.py` + `verify.py`) verifies cryptographic SHA manifests. Self-update is strictly blocked in `PermissionEngine` (`BANNED_ACTIONS`); updates occur via `install.ps1` / signed release packages, never by autonomous agent mutation.

---

## How It Works

- **`hund/main.py`:** Typer CLI entry point; invoking with no arguments starts `hund/ui/repl.py`.
- **`hund/agent/loop.py`:** Agent loop (TCB): `_agent_turn`, token compression, tool dispatch lifecycle.
- **`hund/agent/safety.py`:** `PermissionEngine` (TCB): enforces risk tiers (`SAFE`, `WRITE`, `CONFIRM`, `DANGEROUS`, `BLOCKED`).
- **`hund/agent/tool_dispatch.py`:** Central dispatch gate (TCB) with per-session allowlist isolation.
- **`hund/learning/redactor.py`:** Secret & PII redactor (TCB).
- **`hund/skills/`:** 11 declarative JSON skills, trigger matcher, and positive invariant validator.
- **`hund/ui/`:** Pure Python CLI interface (`theme.py`, `render.py`, `output.py`, `commands.py`, `repl.py`).
- **Persona:** `hund/assets/hund-system/hund.md` → canonical identity injected into system prompts.
- **State:** `HundHome = %LOCALAPPDATA%/hund/` (`memory/user.md`, `brain/`, `sessions/`, `logs/`).

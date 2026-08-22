# hund

> An installable, local-first, self-improving CLI agent that lives inside your hardware.

hund is software executing in physical hardware. Not a cloud chatbot. An operative extension of the user's intellect, standing alongside the user at the terminal.

hund scans the host machine at startup, maps its tools and constraints, executes commands inside a code-hardened safety boundary, and remembers across sessions. hund suggests, assists, and proposes improvements. It never publishes a change without the human's explicit approval.

---

## What hund is specialized in

- **Local machine intelligence.** hund reads the actual host (CPU, RAM, GPU, OS, shell, toolchains) and grounds every answer in real telemetry, not assumptions.
- **Safe command execution.** A code-hardened permission engine classifies every tool call (SAFE / WRITE / CONFIRM / DANGEROUS / BLOCKED) before it runs.
- **Self-improvement under a human gate.** hund studies its own gaps, drafts proposals, and waits for the user to approve. It never self-publishes.

## What makes hund unique

- **Hardware-bound presence.** hund lives in your machine, senses the actual silicon, and adapts to it.
- **RPG progression that is real.** Five base stats (Clarity, Precision, Efficiency, Endurance, Mastery) level up from actual work. A feedback loop, not a skin.
- **Safety in code, not in prompts.** The Trusted Computing Base is inviolable source, not a jailbreakable system prompt.
- **A skill vault, not a skill dump.** Six active slots, trigger-matched and swappable. The rest park in a vault to keep the context sharp.
- **A voice, not a bot.** Third person, terse, warm, zero emojis.

---

## Features

- Streaming agent REPL (prompt_toolkit, real-time token streaming).
- Boxed CLI GUI (compact tool cards, RPG character sheet, on-demand HUDs).
- 11 declarative JSON skills with a 6-slot skill vault.
- Trusted Computing Base with per-session allowlist and RPC risk gating.
- Hardware-aware doctor (CPU, RAM, GPU, OS, toolchains).
- RPG base stats and weekly velocity tracking.
- Persistent local memory.
- Human-gated self-improvement.

---

## Installation (dev, Windows)

```powershell
git clone https://github.com/dopaminedotmd/hund.ai
cd hund.ai
uv sync --extra dev
setx HUND_API_KEY "sk-..."      # open a new terminal afterwards
.venv\Scripts\hund.exe --version   # prints: hund 0.1.0
.venv\Scripts\hund.exe             # starts the REPL
```

Note: `uv run hund` can hit "uv trampoline failed" on Windows. Use `.venv\Scripts\hund.exe` or `.venv\Scripts\python.exe -m hund.main`.

---

## Verify

```powershell
.venv\Scripts\python.exe -m pytest -q --tb=no   # 616 passed, 1 skipped, 0 failed
```

---

## Usage

```powershell
hund             # interactive streaming REPL
hund doctor      # hardware and environment diagnosis
hund stats       # RPG character card and base stats
hund skills      # list equipped skills
```

Inside the REPL: `/help`, `/stats`, `/skills`, `/skills vault`, `/skills equip <name>`, `/skills park <name>`, `/skills swap <old> <new>`, `/tools`, `/doctor`, `/usage`, `/compress`, `/theme`, `/export`, `/exit`.

---

## License

Apache-2.0.

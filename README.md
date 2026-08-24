# Hund.ai

```text
 / \__
(    @\___
 /         O
/   (_____/
/_____/   U
```

Hund is a local-first terminal AI companion with persistent memory, a calm canine personality, and a full-screen TUI for working with models, tools, skills, and usage data.

It is designed to be useful from the first prompt while keeping approvals, tool execution, credentials, and learned context visible and controlled.

## Highlights

- Interactive terminal chat with Prompt Toolkit.
- Full-screen views for stats, skills, tools, and token usage.
- Domain skills with equip/park lifecycle management.
- Built-in and registered tools with safety levels and approval gates.
- DeepSeek, OpenRouter, and local model configuration.
- Windows Credential Manager/keyring support for API keys.
- Persistent memory, XP, skill progression, and activity telemetry.
- Responsive layouts for narrow terminals, ASCII fallback, reduced motion, and screen-reader mode.
- Plain CLI commands remain available for scripting and automation.

## Requirements

- Windows, macOS, or Linux.
- Python 3.11 or newer.
- An API key for the provider/model you want to use, unless you run a local model.

## Install

The recommended installer is `uv`:

```bash
uv tool install git+https://github.com/<OWNER>/<REPO>.git
hund --help
```

For a local checkout:

```bash
git clone https://github.com/<OWNER>/<REPO>.git
cd hund.ai
uv sync
uv run hund
```

Replace `<OWNER>/<REPO>` with the repository URL once published.

## Configure a provider

Start Hund and use the model menu, or set a key through the environment for automation:

```powershell
$env:HUND_API_KEY = "your-api-key"
hund
```

Environment variables take precedence over the OS credential store. In the interactive TUI, `/model` can select a supported preset and `[k]` can store a key in the platform credential manager. Keys are never written to `config.json`, chat history, traces, or the request database.

## Run Hund

```bash
hund
```

Useful commands:

```text
/help       Show available commands
/stats      Open the character sheet and activity view
/skills     Manage domain skills
/tools      Browse tools and built-in capabilities
/usage      Open the token usage heatmap
/theme      Choose a visual theme
/model      Choose or configure a model
/clear      Clear the current chat view
/exit       Leave Hund
```

Inside a full-screen view:

- `↑` / `↓` moves the selection.
- `Enter` selects or opens the focused item.
- `Esc` backs out one layer at a time.
- Mouse wheel scrolls long views.

## Safety and privacy

Hund treats tool execution as an explicit capability. Risky actions can require confirmation, and tool metadata is kept separate from handlers and secrets. Provider credentials are loaded from the environment or the operating system's credential manager and are not included in model prompts or persisted telemetry.

Review approval prompts carefully before allowing filesystem, network, process, or code-execution tools.

## Development

```bash
git clone https://github.com/<OWNER>/<REPO>.git
cd hund.ai
uv sync --extra dev
uv run pytest
uv run hund
```

Build the distributable wheel with:

```bash
uv build
```

## Project layout

```text
hund/
  agent/       Agent loop, prompts, safety, and tool dispatch
  memory/      Persistent memory and retrieval
  providers/   Model presets and provider clients
  skills/      Skill definitions and lifecycle/vault management
  stats/       Progress and telemetry calculations
  tools/       Built-in tools and registry
  ui/          Prompt Toolkit TUI, screens, themes, and snapshots
tests/         Unit, integration, security, and TUI regression tests
```

## Status

Hund is actively being developed. The TUI, provider switching, usage telemetry, skills, tool registry, and credential handling are covered by automated tests, but APIs and UI details may continue to evolve.

Issues, reproduction steps, screenshots, and terminal dimensions are especially helpful when reporting a problem.

## License

See the repository license file for the current license and distribution terms.

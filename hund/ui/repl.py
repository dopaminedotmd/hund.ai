"""REPL main entry point (full-screen TUI).

Sets up the runtime, runs the workspace trust check, then hands off to the
full-screen prompt_toolkit Application in hund.ui.fullscreen.
"""
from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path

from rich.console import Console

from ..agent.loop import _init_runtime
from . import theme
from .fullscreen import run_fullscreen
from .input import PromptState
from .render import refresh_stats, render_startup
from .safety_check import prompt_workspace_trust


def _render_startup_plain(rt) -> str:
    """Render the startup banner to plain text (for the output log)."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None, force_terminal=False, width=100)
    render_startup(console, rt)
    return buf.getvalue()


async def _amain() -> int:
    console = Console()
    rt = _init_runtime()
    if not rt.key:
        console.print(
            "[red]API key missing.[/red] Configure with `hund setup` or "
            f"`setx {rt.cfg.provider.api_key_env} \"sk-...\"`."
        )
        return 1

    state = PromptState()
    model_name = getattr(getattr(rt.cfg, "provider", None), "model", "deepseek-v4-pro")
    state.extra["model"] = model_name
    state.extra["workspace"] = Path(str(rt.workspace)).name or "workspace"

    init_stats = refresh_stats(state)
    if init_stats:
        for k, s in init_stats.items():
            state.prev_tiers[k] = s.get("tier", theme.EMDASH)

    # Workspace folder trust check (prompted once per workspace).
    trusted = await prompt_workspace_trust(console, None, rt.workspace)
    if not trusted:
        console.print("[dim]workspace not trusted. exiting.[/dim]")
        return 0

    banner = _render_startup_plain(rt)
    session_id = getattr(rt, "session_id", None) or uuid.uuid4().hex
    state.session_id = session_id

    return await run_fullscreen(rt, state, banner=banner, session_id=session_id)


def run_repl() -> int:
    """Entrypoint. Called by hund.main."""
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 0

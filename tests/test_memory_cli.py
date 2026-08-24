"""Unit tests for /memory TUI and CLI commands."""
from pathlib import Path
from unittest.mock import MagicMock

from hund.memory.engine import record_contradiction, record_memory
from hund.ui.commands import CommandContext, cmd_memory


import pytest


@pytest.fixture(autouse=True)
def _isolated_hund_home(tmp_path: Path, monkeypatch):
    """Memory CLI tests must never read or mutate the real user profile."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def _make_ctx() -> CommandContext:
    console = MagicMock()
    rt = MagicMock()
    state = MagicMock()
    return CommandContext(console=console, rt=rt, state=state)


def test_cmd_memory_add_and_list() -> None:
    ctx = _make_ctx()

    # 1. Add preference
    cmd_memory(ctx, ["add", "prefers python 3.11"])
    ctx.console.print.assert_called()

    # 2. Add core
    cmd_memory(ctx, ["core", "always verify tests"])
    ctx.console.print.assert_called()

    # 3. List
    cmd_memory(ctx, [])
    ctx.console.print.assert_called()


def test_cmd_memory_why_and_forget() -> None:
    item = record_memory("temporary habit", is_core=False)
    ctx = _make_ctx()

    # Why
    cmd_memory(ctx, ["why", item.memory_id])
    ctx.console.print.assert_called()

    # Forget
    cmd_memory(ctx, ["forget", item.memory_id])
    ctx.console.print.assert_called()


def test_cmd_memory_conflicts() -> None:
    item = record_memory("flaky preference", is_core=False)
    record_contradiction(item.memory_id, reason="mismatch 1")
    record_contradiction(item.memory_id, reason="mismatch 2")

    ctx = _make_ctx()
    cmd_memory(ctx, ["conflicts"])
    ctx.console.print.assert_called()

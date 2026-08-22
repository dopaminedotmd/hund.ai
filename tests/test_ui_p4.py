"""Tester for hund.ui P4: /mascot /memory /notifications."""
from __future__ import annotations

import types
from io import StringIO

from rich.console import Console

from hund.ui.commands import CommandContext, dispatch_command


def _ctx(theme_name="default", notif=True) -> CommandContext:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = types.SimpleNamespace(skills=[], profile=None, session_id=None,
                               domain_hint="?", workspace="?", cfg=None)
    state = types.SimpleNamespace(
        prev_tiers={}, stats_text=None, session_id=None,
        theme_name=theme_name, notifications_enabled=notif,
    )
    return CommandContext(console=console, rt=rt, state=state)  # type: ignore[arg-type]


# -- /mascot ---------------------------------------------------------------

def test_mascot_prints_art() -> None:
    ctx = _ctx()
    dispatch_command("/mascot", ctx)
    out = ctx.console.file.getvalue()
    # block-drawing chars fran pixel-hund
    assert ("▐" in out) or ("▀" in out) or ("█" in out)


# -- /memory ---------------------------------------------------------------

def test_memory_show(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr("hund.ui.commands.memory.show", lambda: "[bold]user.md[/bold]\n- gillar korta svar")
    dispatch_command("/memory", ctx)
    out = ctx.console.file.getvalue()
    assert "user.md" in out
    assert "gillar korta svar" in out


def test_memory_add_appends_bullet(monkeypatch) -> None:
    ctx = _ctx()
    captured = {}
    monkeypatch.setattr("hund.ui.commands.memory.user_bullets", lambda: ["eksisterande"])
    monkeypatch.setattr(
        "hund.ui.commands.memory.update_user",
        lambda text: captured.setdefault("text", text),
    )
    dispatch_command("/memory add foredrar morgnar", ctx)
    assert "- eksisterande" in captured["text"]
    assert "- foredrar morgnar" in captured["text"]
    assert "memory updated" in ctx.console.file.getvalue()


def test_memory_add_no_text(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr("hund.ui.commands.memory.show", lambda: "show")
    # "add" utan text → faller igenom till show
    dispatch_command("/memory add", ctx)
    assert "show" in ctx.console.file.getvalue()


# -- /notifications --------------------------------------------------------

def test_notifications_status_default_on() -> None:
    ctx = _ctx(notif=True)
    dispatch_command("/notifications", ctx)
    assert "on" in ctx.console.file.getvalue()


def test_notifications_off() -> None:
    ctx = _ctx(notif=True)
    dispatch_command("/notifications off", ctx)
    assert ctx.state.notifications_enabled is False
    assert "off" in ctx.console.file.getvalue()


def test_notifications_on() -> None:
    ctx = _ctx(notif=False)
    dispatch_command("/notifications on", ctx)
    assert ctx.state.notifications_enabled is True
    assert "on" in ctx.console.file.getvalue()


# -- help ------------------------------------------------------------------

def test_help_lists_p4_commands() -> None:
    ctx = _ctx()
    dispatch_command("/help", ctx)
    out = ctx.console.file.getvalue()
    for c in ("/mascot", "/memory", "/notifications"):
        assert c in out

"""Tester for hund.ui P2: session (resume/export), /history, /export, render_markdown."""
from __future__ import annotations

import asyncio
import types
from io import StringIO
from unittest.mock import AsyncMock

from rich.console import Console

from hund.ui import session as sess
from hund.ui.commands import CommandContext, dispatch_command
from hund.ui.output import render_markdown


def _ctx(session_id=None, **kw) -> CommandContext:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = types.SimpleNamespace(skills=[], profile=None, session_id="new12345", **kw)
    state = types.SimpleNamespace(prev_tiers={}, stats_text=None, session_id=session_id)
    return CommandContext(console=console, rt=rt, state=state)  # type: ignore[arg-type]


# -- export_session --------------------------------------------------------

def test_export_session_writes_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        sess.S, "list_messages",
        lambda sid: [("user", "hej"), ("assistant", "hund hör"), ("system", "SYS")],
    )
    out = tmp_path / "exp.md"
    path = sess.export_session("abcdef0123", str(out))
    text = out.read_text(encoding="utf-8")
    assert "## du" in text
    assert "hej" in text
    assert "## hund" in text
    assert "hund hör" in text
    # system hoppar over
    assert "SYS" not in text
    assert path == str(out)


def test_export_session_default_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sess.S, "list_messages", lambda sid: [])
    monkeypatch.chdir(tmp_path)
    path = sess.export_session("abcdef0123")
    assert "hund-session-abcdef01" in path
    assert path.endswith(".md")


# -- offer_resume ----------------------------------------------------------

def _fake_rt(session_id="newabc1234") -> types.SimpleNamespace:
    return types.SimpleNamespace(session_id=session_id, messages=[
        types.SimpleNamespace(content="system", role="system"),
        types.SimpleNamespace(content="old", role="user"),
    ])


def test_offer_resume_no_previous_returns_new() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = _fake_rt()
    prompt = AsyncMock()
    result = asyncio.run(sess.offer_resume(console, prompt, rt, None))
    assert result == "newabc1234"
    prompt.prompt_async.assert_not_called()


def test_offer_resume_decline_returns_new() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = _fake_rt()
    prompt = AsyncMock()
    prompt.prompt_async = AsyncMock(return_value="n")
    prev = {"id": "prev12345", "message_count": 5}
    result = asyncio.run(sess.offer_resume(console, prompt, rt, prev))
    assert result == "newabc1234"


def test_offer_resume_accept_reloads_history(monkeypatch) -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = _fake_rt()
    prompt = AsyncMock()
    prompt.prompt_async = AsyncMock(return_value="")
    monkeypatch.setattr(sess.S, "set_active", lambda sid: 1)
    monkeypatch.setattr(sess.S, "history", lambda sid: [("user", " gammalt"), ("assistant", "svar")])
    prev = {"id": "prev12345", "message_count": 2}
    result = asyncio.run(sess.offer_resume(console, prompt, rt, prev))
    assert result == "prev12345"
    # system-prompt (messages[0]) bevarad, resten ersatt
    assert rt.messages[0].content == "system"
    assert len(rt.messages) == 3  # system + 2 historik
    assert rt.messages[1].content == " gammalt"


# -- /history + /export commands ------------------------------------------

def test_history_no_session_message() -> None:
    ctx = _ctx(session_id=None)
    dispatch_command("/history", ctx)
    assert "no active session" in ctx.console.file.getvalue()


def test_history_empty_session(monkeypatch) -> None:
    ctx = _ctx(session_id="abc12345")
    monkeypatch.setattr("hund.ui.commands.S.list_messages", lambda sid: [])
    dispatch_command("/history", ctx)
    assert "empty session" in ctx.console.file.getvalue()


def test_history_shows_messages(monkeypatch) -> None:
    ctx = _ctx(session_id="abc12345")
    monkeypatch.setattr(
        "hund.ui.commands.S.list_messages",
        lambda sid: [("user", "hej"), ("assistant", "svar")],
    )
    dispatch_command("/history", ctx)
    out = ctx.console.file.getvalue()
    assert "hej" in out
    assert "svar" in out


def test_history_search_no_hits(monkeypatch) -> None:
    ctx = _ctx(session_id="abc12345")
    monkeypatch.setattr("hund.ui.commands.S.search", lambda q, **k: [])
    dispatch_command("/history search nbsp", ctx)
    assert "no matches" in ctx.console.file.getvalue().lower()


def test_export_command_prints_path(monkeypatch, tmp_path) -> None:
    ctx = _ctx(session_id="abc12345")
    monkeypatch.setattr(
        "hund.ui.commands.S.list_messages", lambda sid: [("user", "x")]
    )
    monkeypatch.chdir(tmp_path)
    dispatch_command("/export", ctx)
    out = ctx.console.file.getvalue()
    assert "exported" in out.lower()
    assert ".md" in out


# -- render_markdown -------------------------------------------------------

def test_render_markdown_strips_bold_markup() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    render_markdown(console, "Detta ar **viktigt**")
    out = console.file.getvalue()
    assert "viktigt" in out
    # markdown ** ska inte leva kvar som litterala asterisker
    assert "**" not in out


def test_render_markdown_renders_text() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    render_markdown(console, "# rubrik med `kod` och _kursiv_")
    out = console.file.getvalue()
    assert "rubrik med kod och kursiv" in out
    assert "# " not in out
    assert "`" not in out
    assert "_" not in out

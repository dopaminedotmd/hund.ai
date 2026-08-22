"""Tester for hund.ui P3: /session /config /theme /domains /progress + retry-prompt."""
from __future__ import annotations

import types
import asyncio
from io import StringIO

from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console

from hund.config import HundConfig
from hund.ui import theme
from hund.ui.commands import CommandContext, dispatch_command
from hund.ui.repl import _after_turn, _prompt_for


def _ctx(session_id=None, cfg=None, theme_name="default") -> CommandContext:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = types.SimpleNamespace(
        skills=[], profile=None, session_id="x",
        domain_hint="python", workspace="/tmp/ws", cfg=cfg or HundConfig(),
    )
    state = types.SimpleNamespace(
        prev_tiers={}, stats_text=None, session_id=session_id, theme_name=theme_name,
    )
    return CommandContext(console=console, rt=rt, state=state)  # type: ignore[arg-type]


# -- /session --------------------------------------------------------------

def test_session_no_session_message() -> None:
    ctx = _ctx(session_id=None)
    dispatch_command("/session", ctx)
    assert "no active session" in ctx.console.file.getvalue()


def test_session_shows_fields(monkeypatch) -> None:
    ctx = _ctx(session_id="abc12345")
    monkeypatch.setattr(
        "hund.ui.commands.S.info",
        lambda sid: {"id": "abc12345", "created_at": "2026-06-01T00:00:00+00:00",
                     "title": "test", "active": True, "message_count": 7},
    )
    monkeypatch.setattr("hund.ui.commands._global_tokens", lambda: 1234)
    dispatch_command("/session", ctx)
    out = ctx.console.file.getvalue()
    assert "abc12345" in out
    assert "messages" in out and "7" in out
    assert "1234" in out
    assert "python" in out  # domain


# -- /config ---------------------------------------------------------------

def test_config_show_prints_fields() -> None:
    ctx = _ctx()
    dispatch_command("/config", ctx)
    out = ctx.console.file.getvalue()
    assert "model" in out
    assert "base_url" in out


def test_config_set_updates_and_saves(monkeypatch) -> None:
    cfg = HundConfig()
    saved = []
    monkeypatch.setattr("hund.ui.commands.HundConfig.save",
                        lambda self, *a, **k: saved.append(True))
    ctx = _ctx(cfg=cfg)
    dispatch_command("/config set model gpt-4o-mini", ctx)
    assert cfg.provider.model == "gpt-4o-mini"
    assert saved  # save anropades
    assert "gpt-4o-mini" in ctx.console.file.getvalue()


def test_config_set_unknown_key(monkeypatch) -> None:
    cfg = HundConfig()
    monkeypatch.setattr("hund.ui.commands.HundConfig.save", lambda self, *a, **k: None)
    ctx = _ctx(cfg=cfg)
    dispatch_command("/config set bogus x", ctx)
    assert "unknown key" in ctx.console.file.getvalue().lower()


def test_config_set_bool_parses(monkeypatch) -> None:
    cfg = HundConfig()
    monkeypatch.setattr("hund.ui.commands.HundConfig.save", lambda self, *a, **k: None)
    ctx = _ctx(cfg=cfg)
    dispatch_command("/config set telemetry_upload true", ctx)
    assert cfg.telemetry_upload is True


# -- /theme ----------------------------------------------------------------

def test_theme_list_shows_options() -> None:
    ctx = _ctx()
    dispatch_command("/theme", ctx)
    out = ctx.console.file.getvalue()
    assert "default" in out
    assert "minimal" in out


def test_theme_set_known() -> None:
    ctx = _ctx()
    dispatch_command("/theme dark", ctx)
    assert ctx.state.theme_name == "dark"
    assert "dark" in ctx.console.file.getvalue()


def test_theme_set_unknown_errors() -> None:
    ctx = _ctx()
    dispatch_command("/theme neon", ctx)
    assert ctx.state.theme_name == "default"
    assert "unknown theme" in ctx.console.file.getvalue().lower()


def test_prompt_for_uses_theme_color() -> None:
    state = types.SimpleNamespace(theme_name="dark")
    prompt = _prompt_for(state)  # type: ignore[arg-type]
    assert isinstance(prompt, FormattedText)
    style = prompt[0][0]
    assert "ansicyan" in style  # dark tema


def test_after_turn_refreshes_stats_bar_each_time(monkeypatch) -> None:
    calls = []

    def fake_refresh(state):
        calls.append(True)
        state.stats_text = [("fg:ansigreen", f"stats-{len(calls)}")]
        return {"clarity": {"tier": "Novice", "value": 1, "progress": 1}}

    monkeypatch.setattr("hund.ui.repl.refresh_stats", fake_refresh)
    console = Console(force_terminal=False, width=120, file=StringIO())
    state = types.SimpleNamespace(prev_tiers={"clarity": "Novice"}, stats_text=None)
    asyncio.run(_after_turn(console, state))
    asyncio.run(_after_turn(console, state))
    assert len(calls) == 2
    assert state.stats_text == [("fg:ansigreen", "stats-2")]


# -- /domains --------------------------------------------------------------

def test_domains_shows_list(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr(
        "hund.ui.commands.detector.list_domains",
        lambda: [("python", "primary", "high", "t"), ("rust", "active", "medium", "t")],
    )
    monkeypatch.setattr("hund.ui.commands.detector.get_primary", lambda: "python")
    dispatch_command("/domains", ctx)
    out = ctx.console.file.getvalue()
    assert "python" in out
    assert "rust" in out
    assert "primary" in out or "high" in out


def test_domains_empty(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr("hund.ui.commands.detector.list_domains", lambda: [])
    dispatch_command("/domains", ctx)
    assert "no domains" in ctx.console.file.getvalue().lower()


# -- /progress -------------------------------------------------------------

def test_progress_shows_bars(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr(
        "hund.ui.commands.confidence.list_confidence",
        lambda: [{"domain": "python", "score": 80, "confidence_tier": "strong"},
                 {"domain": "rust", "score": 30, "confidence_tier": "candidate"}],
    )
    dispatch_command("/progress", ctx)
    out = ctx.console.file.getvalue()
    assert "python" in out
    assert "█" in out  # bar fill
    assert "strong" in out


def test_progress_empty(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr("hund.ui.commands.confidence.list_confidence", lambda: [])
    dispatch_command("/progress", ctx)
    assert "no domain progress" in ctx.console.file.getvalue().lower()


# -- help includes new cmds ------------------------------------------------

def test_help_lists_p3_commands() -> None:
    ctx = _ctx()
    dispatch_command("/help", ctx)
    out = ctx.console.file.getvalue()
    for c in ("/session", "/config", "/theme", "/domains", "/progress", "/retry"):
        assert c in out

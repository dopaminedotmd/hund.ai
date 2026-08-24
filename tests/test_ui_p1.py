"""Tester for hund.ui P1: commands + animations."""
from __future__ import annotations

import asyncio
import types
from io import StringIO

from rich.console import Console

from hund.ui.animations import level_up, notify
from hund.ui.commands import CommandContext, dispatch_command, is_slash


def _ctx(**kw) -> CommandContext:
    console = Console(force_terminal=False, width=120, file=StringIO())
    rt = types.SimpleNamespace(skills=[], profile=None, **kw)
    state = types.SimpleNamespace(prev_tiers={}, stats_text=None)
    return CommandContext(console=console, rt=rt, state=state)  # type: ignore[arg-type]


# -- dispatcher ------------------------------------------------------------

def test_is_slash_detects_commands() -> None:
    assert is_slash("/stats")
    assert is_slash("  /help")
    assert not is_slash("hej")
    assert not is_slash("")


def test_dispatch_returns_false_for_non_slash() -> None:
    ctx = _ctx()
    assert dispatch_command("hej hund", ctx) is False


def test_dispatch_unknown_command_prints_error() -> None:
    ctx = _ctx()
    assert dispatch_command("/nagonting", ctx) is True
    out = ctx.console.file.getvalue()
    assert "okant" in out or "okänt" in out or "/" in out


def test_dispatch_known_does_not_error() -> None:
    ctx = _ctx()
    assert dispatch_command("/help", ctx) is True
    assert dispatch_command("/skills", ctx) is True
    assert dispatch_command("/tools", ctx) is True
    assert dispatch_command("/clear", ctx) is True


# -- /help -----------------------------------------------------------------

def test_help_lists_commands() -> None:
    ctx = _ctx()
    dispatch_command("/help", ctx)
    out = ctx.console.file.getvalue()
    assert "/stats" in out
    assert "/skills" in out
    assert "/exit" in out
    assert "/trace last" in out


def test_trace_last_shows_only_latest_run(monkeypatch) -> None:
    older = types.SimpleNamespace(
        run_id="old-run", event_type="tool_call_completed", tool_name="read_file", payload_redacted={}
    )
    latest = types.SimpleNamespace(
        run_id="latest-run-123456",
        event_type="tool_call_completed",
        tool_name="web_search",
        payload_redacted={"query": "safe"},
    )
    monkeypatch.setattr(
        "hund.trace.events.list_events_by_session", lambda _session_id: [older, latest]
    )
    ctx = _ctx(session_id="session-1")
    dispatch_command("/trace last", ctx)
    out = ctx.console.file.getvalue()
    assert "latest-run-1" in out
    assert "web_search" in out
    assert "old-run" not in out


def test_help_has_no_emojis() -> None:
    ctx = _ctx()
    dispatch_command("/help", ctx)
    out = ctx.console.file.getvalue()
    assert all(ord(c) < 0x1F000 for c in out)


# -- /skills empty ---------------------------------------------------------

def test_skills_empty_message() -> None:
    ctx = _ctx()
    dispatch_command("/skills", ctx)
    out = ctx.console.file.getvalue()
    assert "no skills" in out


# -- /profile no profile ---------------------------------------------------

def test_profile_missing_message() -> None:
    ctx = _ctx()
    dispatch_command("/profile", ctx)
    out = ctx.console.file.getvalue()
    assert "profile" in out.lower()


# -- animations ------------------------------------------------------------

def test_level_up_prints_three_lines_with_stat() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    asyncio.run(level_up(console, "Precision", "Expert", "Master", 91.0))
    out = console.file.getvalue()
    assert "Precision" in out
    assert "Expert" in out
    assert "Master" in out
    # ASCII only (no emojis)
    assert all(ord(c) < 0x1F000 for c in out)
    # 3 content lines
    assert out.count("\n") >= 3


def test_level_up_value_none_omits_paren() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    asyncio.run(level_up(console, "Clarity", "Adept", "Expert", None))
    out = console.file.getvalue()
    assert "Clarity" in out
    assert "()" not in out


def test_notify_prints_label_and_detail() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    notify(console, "skill_created", "+5 XP")
    out = console.file.getvalue()
    assert "skill" in out.lower()
    assert "+5 XP" in out
    assert all(ord(c) < 0x1F000 for c in out)


def test_notify_unknown_event_falls_back_to_key() -> None:
    console = Console(force_terminal=False, width=120, file=StringIO())
    notify(console, "custom_event")
    out = console.file.getvalue()
    assert "custom_event" in out


# -- New slash commands tests ----------------------------------------------

def test_stats_character_sheet() -> None:
    ctx = _ctx()
    dispatch_command("/stats", ctx)
    out = ctx.console.file.getvalue()
    assert "CHARACTER SHEET" in out
    assert "BASE ATTRIBUTES" in out or "CLR" in out


def test_stats_compact() -> None:
    ctx = _ctx()
    dispatch_command("/stats compact", ctx)
    out = ctx.console.file.getvalue()
    assert "clarity" in out or "precision" in out


def test_model_command() -> None:
    ctx = _ctx()
    dispatch_command("/model", ctx)
    out = ctx.console.file.getvalue()
    assert "model:" in out

    dispatch_command("/model gpt-4o", ctx)
    out2 = ctx.console.file.getvalue()
    assert "active model: gpt-4o" in out2


def test_usage_command() -> None:
    ctx = _ctx()
    dispatch_command("/usage", ctx)
    out = ctx.console.file.getvalue()
    assert "Usage" in out
    assert "tokens" in out


def test_doctor_command() -> None:
    ctx = _ctx()
    dispatch_command("/doctor", ctx)
    out = ctx.console.file.getvalue()
    assert "Doctor" in out
    assert "analyzing" in out


def test_compress_command() -> None:
    ctx = _ctx()
    # No context
    dispatch_command("/compress", ctx)
    out = ctx.console.file.getvalue()
    assert "too little context" in out or "context" in out


def test_diff_command() -> None:
    ctx = _ctx()
    dispatch_command("/diff", ctx)
    out = ctx.console.file.getvalue()
    assert "git" in out or "Diff" in out


def test_undo_command() -> None:
    ctx = _ctx()
    dispatch_command("/undo", ctx)
    out = ctx.console.file.getvalue()
    assert "Undo" in out
    assert "backups" in out or "git restore" in out

"""Terminal-UI: rena renderare och formatteringshelpers."""
from __future__ import annotations

from rich.text import Text

from hund_cli import __version__
from hund_cli.ui.animations import level_up_glitter
from hund_cli.ui.notifications import thinking, tool_line, write_confirm
from hund_cli.ui.render import render_baserad, render_status


def test_render_status_produces_compact_format():
    rendered = render_status(Text("🐕"), "a3f987", 24, "shopify", locked=False)

    assert rendered.plain == (
        f"🐕 Hund {__version__} · 🧭 shopify · session #a3f987 · 24 msg"
    )


def test_render_baserad_handles_three_honest_stats():
    stats = {
        "token_efficiency": {"tokens_per_turn": 420, "level": "strong"},
        "speed": {"avg_latency_ms": 2100, "level": "ok"},
        "tool_judgment": {"success_rate_pct": 62, "level": "weak"},
    }

    rendered = render_baserad(stats).plain

    assert rendered.startswith("TEF strong │ SPD ok │ JDG weak 62% ")
    assert "████░░░░" in rendered
    assert rendered.endswith("/exit · /stats · /profile · /tools")


def test_level_up_glitter_returns_three_rotating_frames():
    frames = level_up_glitter("JDG", "ok", "strong")

    assert len(frames) == 3
    assert len(set(frames)) == 3
    assert all("JDG: ok → strong!" in frame for frame in frames)


def test_notification_formatters():
    assert thinking("hund undersöker...") == "[dim]hund undersöker...[/dim]"
    assert tool_line("read_file", "theme.liquid") == (
        "[dim]● läser theme.liquid[/dim]"
    )
    assert write_confirm("theme.liquid") == (
        "[yellow]WRITE[/yellow] [dim]tillåt? [j/N][/dim]"
    )

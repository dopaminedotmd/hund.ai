"""Tester for hund.ui (P0: theme, render, output/sink).

REPL-loopen (input.py/repl.py) ar integrationstestad manuellt - enhetstester
tacker ren logik: tier-farger, stats-rad, sink-protokoll, separering.
"""
from __future__ import annotations

from io import StringIO

from rich.console import Console

from hund.ui import theme
from hund.ui.output import StreamingSink, strip_markdown
from hund.ui.render import (
    separator,
    stats_bar_segments,
    stats_bar_text,
    user_prefix_markup,
)

FAKE_STATS = {
    "clarity": {"tier": "Master", "progress": 90},
    "precision": {"tier": "Expert", "progress": 70},
    "efficiency": {"tier": "Adept", "progress": 50},
    "endurance": {"tier": "Apprentice", "progress": 30},
    "mastery": {"tier": "Novice", "progress": 10},
}


# -- theme -----------------------------------------------------------------

def test_tier_styles_are_16_ansi_safe() -> None:
    allowed = {"dim", "white", "green", "cyan", "bright_yellow", "red", "yellow"}
    for tier, style in theme.TIER_RICH.items():
        assert style in allowed, f"{tier}: {style} ej 16-ANSI-safe"


def test_master_is_bright_yellow() -> None:
    assert theme.TIER_RICH["Master"] == "bright_yellow"
    assert theme.TIER_PT["Master"] == "ansibrightyellow"


def test_no_emojis_in_tokens() -> None:
    blob = repr(theme.TIER_RICH) + repr(theme.TIER_PT) + theme.USER_PREFIX
    assert all(ord(c) < 0x1F000 for c in blob)


# -- render: stats bar -----------------------------------------------------

def test_stats_bar_text_has_all_abbrevs() -> None:
    line = stats_bar_text(FAKE_STATS)
    for abbr in ("CLR", "PRC", "EFF", "END", "MAS"):
        assert abbr in line, f"saknar {abbr}: {line}"


def test_stats_bar_uses_only_safe_chars() -> None:
    line = stats_bar_text(FAKE_STATS)
    for ch in line:
        # bokstaver/siffror, mellanslag, bar/pipe-tecken endast
        assert ch.isalnum() or ch.isspace() or ch in "│░█", repr(ch)


def test_stats_bar_segments_carry_tier_styles() -> None:
    segs = stats_bar_segments(FAKE_STATS)
    styles = "".join(s or "" for s, _ in segs)
    assert "ansibrightyellow" in styles  # Master
    assert "ansicyan" in styles          # Adept


# -- render: separering ----------------------------------------------------

def test_user_prefix_is_bold_green_du() -> None:
    assert theme.USER_PREFIX == "❯"
    assert theme.USER_PREFIX_RICH == "bold green"


def test_separator_uses_rule_char() -> None:
    console = Console(force_terminal=False, width=60, file=StringIO())
    separator(console)
    out = console.file.getvalue()
    assert "─" in out


def test_user_prefix_markup_helper() -> None:
    assert "❯" in user_prefix_markup()
    assert "green" in user_prefix_markup()




# -- output: sink ----------------------------------------------------------

def test_sink_chunk_streams_concat() -> None:
    console = Console(force_terminal=False, width=120)
    sink = StreamingSink(console, stream_delay_s=0)
    with console.capture() as cap:
        sink.chunk("hel")
        sink.chunk("lo")
        sink.end_assistant()
    assert "hello" in cap.get()


def test_strip_markdown_removes_bold_italic_and_code() -> None:
    text = strip_markdown("**fet** _kursiv_ `kod` [lank](https://x.test)")
    assert text == "fet kursiv kod lank (https://x.test)"


def test_sink_chunk_outputs_plain_bone_white_text() -> None:
    out_file = StringIO()
    console = Console(
        force_terminal=True,
        color_system="truecolor",
        width=120,
        file=out_file,
    )
    sink = StreamingSink(console, stream_delay_s=0)
    sink.chunk("**hund** `kod`")
    out = out_file.getvalue()
    assert "**" not in out
    assert "`" not in out
    for ch in "hund kod":
        assert ch in out
    assert "\x1b[38;2;227;227;228m" in out


def test_sink_streams_character_by_character() -> None:
    class File:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, text: str) -> int:
            self.writes.append(text)
            return len(text)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    file = File()
    console = Console(force_terminal=False, width=120, file=file)
    sink = StreamingSink(console, stream_delay_s=0)
    sink.chunk("abc")
    joined = "".join(file.writes)
    assert "abc" in joined
    assert len([w for w in file.writes if w in {"a", "b", "c"}]) == 3


def test_sink_thinking_then_clear_erases_line() -> None:
    console = Console(force_terminal=False, width=80, file=StringIO())
    sink = StreamingSink(console)
    sink.thinking()
    assert sink._thinking_active is True
    sink.clear_thinking()
    assert sink._thinking_active is False
    assert "\r" in console.file.getvalue()


def test_sink_error_renders_markup() -> None:
    console = Console(force_terminal=False, width=120)
    sink = StreamingSink(console)
    with console.capture() as cap:
        sink.error("[red]boom[/red]")
    assert "boom" in cap.get()


def test_sink_confirm_yes(monkeypatch) -> None:
    from hund.agent.types import ConfirmRequest, ConfirmVerdict
    monkeypatch.setattr("builtins.input", lambda *a, **k: "j")
    sink = StreamingSink(Console(force_terminal=False, width=120, file=StringIO()))
    req = ConfirmRequest(tool_name="terminal", args={"command": "ls"})
    assert sink.confirm(req) == ConfirmVerdict.APPROVE_ONCE


def test_sink_confirm_no(monkeypatch) -> None:
    from hund.agent.types import ConfirmRequest, ConfirmVerdict
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    sink = StreamingSink(Console(force_terminal=False, width=120, file=StringIO()))
    req = ConfirmRequest(tool_name="terminal", args={"command": "ls"})
    assert sink.confirm(req) == ConfirmVerdict.DENY


def test_sink_confirm_allow_all(monkeypatch) -> None:
    from hund.agent.types import ConfirmRequest, ConfirmVerdict
    monkeypatch.setattr("builtins.input", lambda *a, **k: "a")
    sink = StreamingSink(Console(force_terminal=False, width=120, file=StringIO()))
    req = ConfirmRequest(tool_name="terminal", args={"command": "ls"})
    assert sink.confirm(req) == ConfirmVerdict.ALLOW_SESSION


def test_sink_tool_hooks_exist() -> None:
    sink = StreamingSink(Console(force_terminal=False, width=120, file=StringIO()))
    sink.tool_start("terminal", {"command": "ls"})
    sink.tool_result("terminal", "file.txt")
    sink.blocked("terminal", "risk")
    sink.declined("terminal", "user")


# -- repl entrypoint -------------------------------------------------------

def test_run_repl_is_callable() -> None:
    from hund.ui import run_repl

    assert callable(run_repl)

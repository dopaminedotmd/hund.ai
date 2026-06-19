"""Terminal-UI: rena renderare, autocomplete, tänketexter och animering."""
from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent, FuzzyCompleter, NestedCompleter
from prompt_toolkit.document import Document

from hund_cli import __version__
from hund_cli.ui.animations import level_up_glitter
from hund_cli.ui.autocomplete import build_completer
from hund_cli.ui.notifications import (
    pick_thinking_text,
    thinking,
    tool_line,
    write_confirm,
)
from hund_cli.ui.render import (
    blocked_tool_message,
    format_session_rows,
    format_session_search_rows,
    plain_error_message,
    render_assistant_turn,
    render_startup,
    render_status_plain,
    render_user_prompt,
)
from hund_cli.ui.thinking import ThinkingAnimator


def test_render_startup_is_full_height_without_status_noise():
    height = 32
    rendered = render_startup(
        100,
        height,
        workspace="hund-cli",
        version=__version__,
        model="deepseek-chat",
    ).plain
    lines = rendered.split("\n")

    assert len(lines) >= height - 1
    assert f"◇ Hund CLI v{__version__}" in rendered
    assert "─" * 20 in rendered
    assert "·" * 12 in rendered
    assert "local-first agentmotor" in rendered
    assert "workspace  hund-cli" in rendered
    assert "model      deepseek-chat" in rendered
    assert "/sessions · /exit · /stats · /profile · /tools" in rendered
    assert lines[0] == ""
    assert lines[1] == ""
    assert lines[-1] == ""
    assert "/sessions · /exit" in lines[-2]
    assert lines[-2].startswith(" " * 20)
    assert "du>" not in rendered
    assert "tef" not in rendered.lower()
    assert "spd" not in rendered.lower()
    assert "jdg" not in rendered.lower()


def test_turn_markers_use_symbol_hierarchy_without_labels_or_stats():
    prompt = render_user_prompt().plain
    assistant = render_assistant_turn("Hej.\nVad vill du göra?").plain
    combined = render_startup(80, 24, "hund-cli").plain + prompt + assistant

    assert prompt == "◇ "
    assert assistant == "\n◆ Hej.\n   Vad vill du göra?\n\n" + "─" * 40 + "\n"
    assert render_assistant_turn("").plain == ""
    assert "du>" not in combined
    assert "du<" not in combined
    assert "tef" not in combined.lower()
    assert "spd" not in combined.lower()
    assert "jdg" not in combined.lower()


def test_startup_supports_common_terminal_widths():
    for width in (80, 100, 120):
        rendered = render_startup(width, 24, workspace="hund-cli").plain
        assert "Hund CLI" in rendered
        assert "workspace  hund-cli" in rendered


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


def test_error_and_blocked_messages_are_markup_free():
    assert plain_error_message("[red]provider dog[/red]") == "fel: provider dog"
    assert plain_error_message("\n[yellow]max tool-rundor nådda[/yellow]") == (
        "fel: max tool-rundor nådda"
    )
    assert blocked_tool_message("write_file", "locked") == "blocked: write_file — locked"


def test_session_formatters_match_repl_sessions_output():
    rows = [
        ("abcdef123456", "2026-06-19T12:00:00Z", "en väldigt lång sessionstitel", 4, 1),
        ("1234567890ab", "2026-06-19T11:00:00Z", "kort", 2, 0),
    ]
    assert format_session_rows([]) == "(inga sessioner)"
    assert format_session_rows(rows).splitlines() == [
        "* #abcdef12 (4) en väldigt lång sessionstitel — 2026-06-19T12:00:00Z",
        "  #12345678 (2) kort — 2026-06-19T11:00:00Z",
    ]

    hits = [("abcdef123456", "user", "hej [term]", "2026-06-19T12:01:00Z")]
    assert format_session_search_rows("term", []) == "(inga träffar för 'term')"
    assert format_session_search_rows("term", hits) == (
        "#abcdef12 [user] hej [term] — 2026-06-19T12:01:00Z"
    )


# --- nytt: kontextuella tänketexter (spec §4) ---


def test_pick_thinking_text_is_contextual():
    assert pick_thinking_text("vad är klockan") == "hund undersöker"
    assert pick_thinking_text("hur funkar det?") == "hund undersöker"
    assert pick_thinking_text("läs theme.liquid") == "hund läser"
    assert pick_thinking_text("kolla färgfelet") == "hund läser"
    assert pick_thinking_text("hitta felet") == "hund söker"
    assert pick_thinking_text("leta efter rad 45") == "hund söker"
    assert pick_thinking_text("ändra theme.liquid") == "hund förbereder"
    assert pick_thinking_text("skriv test") == "hund förbereder"
    assert pick_thinking_text("kör pytest") == "hund kör"
    assert pick_thinking_text("bygg om") == "hund kör"


def test_pick_thinking_text_default():
    assert pick_thinking_text("hej") == "hund tänker"
    assert pick_thinking_text("") == "hund tänker"
    assert pick_thinking_text("   ") == "hund tänker"


# --- nytt: slash-autocomplete ---


def test_build_completer_is_nested_with_slash_commands():
    completer = build_completer()
    assert isinstance(completer, NestedCompleter)
    wrapped = FuzzyCompleter(completer)
    doc = Document("/", 1)
    texts = {c.text for c in wrapped.get_completions(doc, CompleteEvent())}
    assert "/stats" in texts
    assert "/exit" in texts
    assert "/sessions" in texts


def test_build_completer_sessions_subcommands():
    completer = build_completer()
    wrapped = FuzzyCompleter(completer)
    doc = Document("/sessions ", len("/sessions "))
    texts = {c.text for c in wrapped.get_completions(doc, CompleteEvent())}
    assert "list" in texts
    assert "search" in texts
    assert "resume" in texts
    assert "new" in texts


# --- nytt: render_status_plain för toolbar ---


def test_render_status_plain_is_plain_string_with_fields():
    rendered = render_status_plain("abcdef123456", 12, "shopify", version="0.2.0")
    assert isinstance(rendered, str)
    assert "Hund 0.2.0" in rendered
    assert "shopify" in rendered
    assert "#abcdef12" in rendered
    assert "12 msg" in rendered
    assert "/sessions" in rendered


def test_render_status_plain_defaults_domain():
    assert "general" in render_status_plain("x", 0, None)


# --- nytt: ThinkingAnimator ---


def test_thinking_animator_start_stop_is_safe_in_non_tty(monkeypatch):
    monkeypatch.setenv("HUND_NO_ANIMATE", "1")
    animator = ThinkingAnimator(interval=0.01)
    animator.start("hund test")
    assert animator._thread is None  # statisk path → ingen tråd
    animator.stop()  # får ej krascha; stop utan start är no-op-safe
    animator.stop()


def test_thinking_animator_threaded_start_stops_cleanly(monkeypatch):
    # Tvinga animerad path och låtsas att stdout är en TTY.
    monkeypatch.delenv("HUND_NO_ANIMATE", raising=False)
    monkeypatch.setattr("hund_cli.ui.thinking.ThinkingAnimator._animated", staticmethod(lambda: True))
    animator = ThinkingAnimator(interval=0.01)
    animator.start("hund kör")
    assert animator._thread is not None and animator._thread.is_alive()
    animator.stop()
    assert animator._thread is None


# --- integration: misslyckad init (key saknas) ---


def test_run_repl_ui_initialization_failure(monkeypatch):
    import hund_cli.ui.repl as repl
    import hund_cli.agent.loop as loop
    import types

    def mock_init():
        return types.SimpleNamespace(key=None)

    monkeypatch.setattr(loop, "_init_runtime", mock_init)
    res = repl.run_repl_ui()
    assert res == 1


def test_prompt_session_config_runs_against_dummy_io():
    """Skyddar regression: PromptSession-config (toolbar + FuzzyCompleter +
    style + HTML-prompt + patch_stdout på prompt()) är giltig och prompt()
    returnerar utan TTY."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import FuzzyCompleter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from prompt_toolkit.styles import Style

    from hund_cli.ui.repl import _PROMPT_MSG, _STYLE

    def toolbar():
        return [("class:bottom-toolbar", "hund 0.2.0 · shopify · session #abc · 0 msg")]

    with create_pipe_input() as inp:
        inp.send_text("\n")
        session = PromptSession(
            bottom_toolbar=toolbar,
            completer=FuzzyCompleter(build_completer()),
            complete_while_typing=True,
            style=_STYLE,
            input=inp,
            output=DummyOutput(),
        )
        result = session.prompt(_PROMPT_MSG)
    assert result == ""

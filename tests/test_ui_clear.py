"""Tests for clearing only the visible transcript."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from prompt_toolkit.output import DummyOutput
from rich.console import Console

from hund.ui.commands import CommandContext, dispatch_command
from hund.ui.fullscreen import create_fullscreen_app


def _runtime():
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = [SimpleNamespace(role="user", content="durable")]
    return rt


def test_clear_and_cls_use_presentation_callback():
    calls = []
    ctx = CommandContext(
        console=Console(force_terminal=False),
        rt=SimpleNamespace(),
        state=SimpleNamespace(),
        clear_screen=lambda: calls.append("clear") or None,
    )
    assert dispatch_command("/clear", ctx) is True
    assert dispatch_command("/cls", ctx) is True
    assert calls == ["clear", "clear"]


def test_plain_clear_falls_back_to_console_clear():
    console = MagicMock()
    ctx = CommandContext(console=console, rt=SimpleNamespace(), state=SimpleNamespace())
    dispatch_command("/clear", ctx)
    console.clear.assert_called_once_with()


def test_fullscreen_clear_resets_visible_state_but_keeps_messages():
    rt = _runtime()
    state = MagicMock()
    state.extra = {}
    _app, context = create_fullscreen_app(rt, state, output=DummyOutput())
    sink = context["sink_cls"]()
    sink.set_user_input("visible prompt")
    sink.chunk("visible response")
    sink.end_assistant()
    original_messages = list(rt.messages)
    assert context["output_buffer"].text
    assert context["block_registry"].records()
    assert context["response_payloads"]

    assert context["clear_screen"]() is None

    assert context["output_buffer"].text == ""
    assert context["block_registry"].records() == ()
    assert context["payload_by_id"] == {}
    assert context["response_payloads"] == []
    assert rt.messages == original_messages
    context["_reflow_borders"]()
    assert context["output_buffer"].text == ""


def test_fullscreen_clear_rejects_active_turn_without_mutation():
    rt = _runtime()
    state = MagicMock()
    state.extra = {}
    _app, context = create_fullscreen_app(rt, state, output=DummyOutput())
    before = context["output_buffer"].text
    context["turn_running"][0] = True

    notice = context["clear_screen"]()

    assert notice == "Wait for the active turn to finish before clearing."
    assert context["output_buffer"].text == before

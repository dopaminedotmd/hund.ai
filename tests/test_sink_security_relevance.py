"""Tests for _Sink tool confirmation correlation and security relevance gating."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from prompt_toolkit.output import DummyOutput

from hund.agent.types import ConfirmRequest, ConfirmVerdict
from hund.ui.activity import ActivityStatus, ActivityTimeline
from hund.ui.fullscreen import create_fullscreen_app


def test_sink_runtime_default_security_none_does_not_collapse() -> None:
    """Test that runtime _Sink events default to security_relevant=None and do not collapse."""
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []

    state = MagicMock()
    state.extra = {}

    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink_cls = ctx["sink_cls"]
    sink = sink_cls()

    sink.set_user_input("read some code")
    sink.tool_start("read_file", {"path": "main.py"})
    time.sleep(0.05)
    sink.tool_result("read_file", "def main(): pass")

    # In live turns, security_relevant is None, so fast-turn collapse is disabled
    ev = sink._activity.events[0]
    assert ev.security_relevant is None
    lines = sink._activity.render_lines()
    # It must render the expanded rail (with ┊ and ✓), not the collapsed single-line
    assert any("┊" in l and "✓" in l for l in lines)
    assert not any(l.startswith("  hund ") and l.endswith("s") for l in lines)


def test_untrusted_tool_args_never_set_security_relevant_false() -> None:
    """Test that model-supplied tool args claiming false security relevance are ignored."""
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []

    state = MagicMock()
    state.extra = {}

    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink_cls = ctx["sink_cls"]
    sink = sink_cls()

    sink.set_user_input("untrusted tool args")
    # Adversarial model payload trying to force collapse
    sink.tool_start("read_file", {"path": "secret.txt", "security_relevant": False})
    sink.tool_result("read_file", "secret content")

    ev = sink._activity.events[0]
    assert ev.security_relevant is None  # Still None, never trusted
    assert any("┊" in l for l in sink._activity.render_lines())


def test_timeline_explicit_false_security_allows_fast_collapse() -> None:
    """Test that ActivityTimeline collapses only when security_relevant is explicitly False."""
    timeline = ActivityTimeline()
    eid = timeline.start(
        "read_file",
        "read main.py",
        required_confirmation=False,
        security_relevant=False,
    )
    timeline.finish(eid, ActivityStatus.COMPLETE, duration_s=0.2)

    lines = timeline.render_lines()
    assert len(lines) == 1
    assert lines[0] == "  hund read main.py.            0.2s"


def test_confirmation_correlation_before_and_after_tool_start() -> None:
    """Test that confirmation before or during tool_start correctly marks only that tool."""
    rt = MagicMock()
    rt.cfg = MagicMock(reduced_motion=True, screen_reader=False)
    rt.profile = None
    rt.messages = []

    state = MagicMock()
    state.extra = {}

    app, ctx = create_fullscreen_app(rt, state, output=DummyOutput())
    sink_cls = ctx["sink_cls"]
    sink = sink_cls()

    # Case A: Confirmation arrives before tool_start
    sink.set_user_input("turn 1")
    req1 = ConfirmRequest(tool_name="terminal", args={"command": "npm install"}, risk="confirm")

    _confirm = ctx["_confirm"]
    import threading
    def _auto_approve():
        time.sleep(0.02)
        _confirm["answer"] = ConfirmVerdict.APPROVE_ONCE
        _confirm["event"].set()
    threading.Thread(target=_auto_approve, daemon=True).start()

    verdict = sink.confirm(req1)
    assert verdict == ConfirmVerdict.APPROVE_ONCE

    sink.tool_start("terminal", {"command": "npm install"})
    sink.tool_result("terminal", "ok")

    assert len(sink._activity.events) == 1
    assert sink._activity.events[0].required_confirmation is True

    # Case B: Subsequent unconfirmed tool in next turn does not inherit confirmation
    sink.set_user_input("turn 2")
    sink.tool_start("read_file", {"path": "package.json"})
    sink.tool_result("read_file", "{}")

    assert len(sink._activity.events) == 1
    assert sink._activity.events[0].required_confirmation is False

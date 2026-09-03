"""Tests for policy-scoped, per-session approval fatigue mitigation."""
import json
from unittest.mock import MagicMock, patch

import pytest

from hund.agent.safety import PermissionEngine
from hund.agent.tool_dispatch import (
    _PREFLIGHT_ALLOWLIST,
    _SESSION_ALLOWLIST,
    _TURN_TERMINAL_ALLOWLIST,
    dispatch_tool_call,
    preflight_check_tool_calls,
)
from hund.agent.types import ConfirmRequest, ConfirmVerdict
from hund.ui.confirmation import confirmation_options
from hund.ui.fullscreen import _confirm_options
from hund.ui.output import _confirm_detail, _confirm_reason
from hund.tools.default_tools import register_defaults
from hund.tools.types import ToolKind, create_success_result


@pytest.fixture(autouse=True)
def clear_allowlist():
    _SESSION_ALLOWLIST.clear()
    _TURN_TERMINAL_ALLOWLIST.clear()
    _PREFLIGHT_ALLOWLIST.clear()
    yield
    _SESSION_ALLOWLIST.clear()
    _TURN_TERMINAL_ALLOWLIST.clear()
    _PREFLIGHT_ALLOWLIST.clear()


def _terminal_call(command: str) -> dict:
    return {
        "id": "1",
        "function": {
            "name": "terminal",
            "arguments": json.dumps({"command": command}),
        },
    }


def _dispatch(tc, engine, console, hooks, session_id, turn_id=None):
    with patch(
        "hund.agent.tool_dispatch.registry.call_typed",
        return_value=create_success_result(ToolKind.EXECUTION, "ok"),
    ):
        return dispatch_tool_call(
            tc, engine, console, hooks=hooks, session_id=session_id, turn_id=turn_id
        )


def test_confirm_policy_gets_session_allowlisted(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    tc = _terminal_call("git push origin feature")

    assert _dispatch(tc, engine, console, hooks, "sess-1") == "ok"
    request = hooks.confirm.call_args.args[0]
    assert request.policy_id == "terminal.git_push"
    assert request.session_allowable is True
    assert _SESSION_ALLOWLIST.is_allowed(
        "sess-1", "terminal", "terminal.git_push", args={"command": "git push origin feature"}
    )

    hooks.confirm.reset_mock()
    hooks.confirm.side_effect = AssertionError("Should not prompt user")
    assert _dispatch(tc, engine, console, hooks, "sess-1") == "ok"
    hooks.confirm.assert_not_called()


def test_allowlist_is_policy_and_session_scoped(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.side_effect = [ConfirmVerdict.ALLOW_SESSION, ConfirmVerdict.DENY]

    assert _dispatch(_terminal_call("git push origin feature"), engine, console, hooks, "sess-1") == "ok"
    assert _dispatch(_terminal_call("pip install sample-package"), engine, console, hooks, "sess-1") == "[declined by user]"

    hooks.confirm.reset_mock()
    hooks.confirm.side_effect = None
    hooks.confirm.return_value = ConfirmVerdict.DENY
    assert _dispatch(_terminal_call("git push origin feature"), engine, console, hooks, "sess-2") == "[declined by user]"
    hooks.confirm.assert_called_once()


def test_unknown_terminal_commands_share_a_session_grant(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    tc = _terminal_call("custom-release-script --ship")

    assert _dispatch(tc, engine, console, hooks, "sess-1") == "ok"
    request = hooks.confirm.call_args.args[0]
    assert request.policy_id == "terminal.unknown"
    assert request.session_allowable is True
    assert _SESSION_ALLOWLIST.is_allowed("sess-1", "terminal", "terminal.unknown")

    hooks.confirm.reset_mock()
    hooks.confirm.side_effect = AssertionError("Should not prompt user")
    assert _dispatch(_terminal_call("another-release-script --ship"), engine, console, hooks, "sess-1") == "ok"
    hooks.confirm.assert_not_called()


def test_confirm_edit_without_editor_cancels_safely(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.EDIT

    result = _dispatch(_terminal_call("git push origin feature"), engine, console, hooks, "sess-1")
    assert result == "[declined: edit cancelled]"
    hooks.declined.assert_called_once_with("terminal", "edit cancelled")


def test_missing_session_id_cannot_create_allowlist_entry(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION

    assert _dispatch(_terminal_call("git push origin feature"), engine, console, hooks, None) == "ok"
    assert not _SESSION_ALLOWLIST.is_allowed(None, "terminal", "terminal.git_push")


def test_confirmation_request_contains_policy_reason(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.DENY

    _dispatch(_terminal_call("git push"), engine, console, hooks, "sess-test")

    request = hooks.confirm.call_args.args[0]
    assert isinstance(request, ConfirmRequest)
    assert request.tool_name == "terminal"
    assert request.risk == "confirm"
    assert request.reason
    assert request.policy_id == "terminal.git_push"
    assert request.session_allowable is True


def test_non_allowable_request_hides_session_option():
    options = confirmation_options("terminal", session_allowable=False)
    assert ConfirmVerdict.ALLOW_SESSION not in {verdict for verdict, _ in options}


def test_turn_terminal_grant_does_not_cross_turns(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_TURN

    assert _dispatch(_terminal_call("powershell -NoProfile -Command \"$x = 1\""), engine, console, hooks, "sess-1", "turn-1") == "ok"
    hooks.confirm.reset_mock()
    assert _dispatch(_terminal_call("powershell -NoProfile -Command \"$y = 2\""), engine, console, hooks, "sess-1", "turn-1") == "ok"
    hooks.confirm.assert_not_called()

    hooks.confirm.return_value = ConfirmVerdict.DENY
    assert _dispatch(_terminal_call("powershell -NoProfile -Command \"$z = 3\""), engine, console, hooks, "sess-1", "turn-2") == "[declined by user]"


def test_fullscreen_confirmation_exposes_turn_option() -> None:
    assert ConfirmVerdict.ALLOW_TURN in {
        verdict for verdict, _label, _color in _confirm_options("terminal", turn_allowable=True)
    }


def test_confirmation_display_redacts_and_bounds_untrusted_text():
    request = ConfirmRequest(
        tool_name="terminal",
        args={"command": "deploy --token=super-secret-value\nsecond line" + "x" * 300},
        reason="Policy check\nwith untrusted input",
    )

    detail = _confirm_detail(request)
    reason = _confirm_reason(request)
    assert "super-secret-value" not in detail
    assert "\n" not in detail
    assert len(detail) <= 160
    assert "\n" not in reason


def test_preflight_check_cancels_turn_when_denied(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.DENY

    tool_calls = [
        {
            "id": "tc-1",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "halsning.html", "content": "<h1>Hej</h1>"}),
            },
        },
        _terminal_call("start halsning.html"),
    ]

    # Pre-flight check detects the terminal CONFIRM call and prompts
    ok = preflight_check_tool_calls(
        tool_calls, engine, console, hooks=hooks, session_id="sess-1", turn_id="turn-1"
    )
    assert ok is False
    hooks.confirm.assert_called_once()
    assert hooks.confirm.call_args.args[0].tool_name == "terminal"


def test_preflight_check_allows_turn_and_avoids_duplicate_prompt(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.APPROVE_ONCE

    tool_calls = [
        {
            "id": "tc-1",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "halsning.html", "content": "<h1>Hej</h1>"}),
            },
        },
        _terminal_call("powershell -NoProfile -Command Write-Output 1"),
    ]

    ok = preflight_check_tool_calls(
        tool_calls, engine, console, hooks=hooks, session_id="sess-1", turn_id="turn-1"
    )
    assert ok is True
    hooks.confirm.assert_called_once()

    # When tools are subsequently dispatched, terminal does not prompt a second time
    hooks.confirm.reset_mock()
    hooks.confirm.side_effect = AssertionError("Should not prompt twice")
    with patch("hund.agent.tool_dispatch.registry.call_typed", return_value=create_success_result(ToolKind.EXECUTION, "ok")):
        out1 = dispatch_tool_call(tool_calls[0], engine, console, hooks=hooks, session_id="sess-1", turn_id="turn-1")
        out2 = dispatch_tool_call(tool_calls[1], engine, console, hooks=hooks, session_id="sess-1", turn_id="turn-1")
    assert out1 == "ok"
    assert out2 == "ok"
    hooks.confirm.assert_not_called()


def test_preflight_check_safe_only_turn_does_not_prompt(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.side_effect = AssertionError("Safe turn should never prompt confirm")

    tool_calls = [
        {
            "id": "tc-1",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "halsning.html", "content": "<h1>Hej</h1>"}),
            },
        },
        _terminal_call("ls"),
    ]

    ok = preflight_check_tool_calls(
        tool_calls, engine, console, hooks=hooks, session_id="sess-1", turn_id="turn-1"
    )
    assert ok is True
    hooks.confirm.assert_not_called()


"""Tests for policy-scoped, per-session approval fatigue mitigation."""
import json
from unittest.mock import MagicMock, patch

import pytest

from hund.agent.safety import PermissionEngine
from hund.agent.tool_dispatch import _SESSION_ALLOWLIST, dispatch_tool_call
from hund.agent.types import ConfirmRequest, ConfirmVerdict
from hund.ui.confirmation import confirmation_options
from hund.ui.output import _confirm_detail, _confirm_reason
from hund.tools.default_tools import register_defaults
from hund.tools.types import ToolKind, create_success_result


@pytest.fixture(autouse=True)
def clear_allowlist():
    _SESSION_ALLOWLIST.clear()
    yield
    _SESSION_ALLOWLIST.clear()


def _terminal_call(command: str) -> dict:
    return {
        "id": "1",
        "function": {
            "name": "terminal",
            "arguments": json.dumps({"command": command}),
        },
    }


def _dispatch(tc, engine, console, hooks, session_id):
    with patch(
        "hund.agent.tool_dispatch.registry.call_typed",
        return_value=create_success_result(ToolKind.EXECUTION, "ok"),
    ):
        return dispatch_tool_call(
            tc, engine, console, hooks=hooks, session_id=session_id
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
    assert _SESSION_ALLOWLIST.is_allowed("sess-1", "terminal", "terminal.git_push")

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


def test_unknown_command_cannot_be_allowlisted(tmp_path):
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    tc = _terminal_call("custom-release-script --ship")

    assert _dispatch(tc, engine, console, hooks, "sess-1") == "ok"
    request = hooks.confirm.call_args.args[0]
    assert request.policy_id == "terminal.unknown"
    assert request.session_allowable is False
    assert not _SESSION_ALLOWLIST.is_allowed("sess-1", "terminal", "terminal.unknown")

    hooks.confirm.reset_mock()
    hooks.confirm.return_value = ConfirmVerdict.DENY
    assert _dispatch(tc, engine, console, hooks, "sess-1") == "[declined by user]"
    hooks.confirm.assert_called_once()


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

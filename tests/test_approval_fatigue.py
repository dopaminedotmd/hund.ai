"""Tester for Approval Fatigue Mitigation (Session Allowlist)."""
from unittest.mock import MagicMock, patch
import pytest

from hund.agent.safety import PermissionEngine, RiskLevel
from hund.agent.tool_dispatch import dispatch_tool_call, _SESSION_ALLOWLIST
from hund.agent.types import ConfirmRequest, ConfirmVerdict
from hund.tools.default_tools import register_defaults


@pytest.fixture(autouse=True)
def clear_allowlist():
    _SESSION_ALLOWLIST.clear()
    yield
    _SESSION_ALLOWLIST.clear()


def test_confirm_gets_session_allowlisted(tmp_path):
    """Om användaren väljer ALLOW_SESSION på ett CONFIRM-verktyg, ska nästa anrop auto-tillåtas."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    
    tc = {"id": "1", "function": {"name": "terminal", "arguments": '{"command": "dir"}'}}
    
    # Första anropet: confirm anropas EN gång och returnerar ALLOW_SESSION
    res1 = dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-1")
    assert res1 != "[declined by user]"
    assert _SESSION_ALLOWLIST.is_allowed("sess-1", "terminal")
    assert "terminal" in _SESSION_ALLOWLIST
    hooks.confirm.assert_called_once()
    
    # Andra anropet ska inte anropa confirm alls (auto-tillåtet via session allowlist)
    hooks.confirm.reset_mock()
    hooks.confirm.side_effect = AssertionError("Should not prompt user")
    
    res2 = dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-1")
    assert res2 != "[declined by user]"
    hooks.confirm.assert_not_called()


def test_dangerous_cannot_be_allowlisted(tmp_path):
    """DANGEROUS verktyg får aldrig läggas till i session-allowlist även om ALLOW_SESSION returneras."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    
    tc = {"id": "1", "function": {"name": "delete_file", "arguments": '{"path": "x.txt"}'}}
    
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    
    res1 = dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-1")
    assert res1 != "[declined by user]"
    # DANGEROUS ska inte finnas i allowlist
    assert not _SESSION_ALLOWLIST.is_allowed("sess-1", "delete_file")
    assert "delete_file" not in _SESSION_ALLOWLIST
    hooks.confirm.assert_called_once()
    
    # Nästa anrop av delete_file ska fortfarande prompta användaren
    hooks.confirm.reset_mock()
    hooks.confirm.return_value = ConfirmVerdict.DENY
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    
    res2 = dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-1")
    assert res2 == "[declined by user]"
    hooks.confirm.assert_called_once()


def test_confirm_edit_returns_declined_marker(tmp_path):
    """Om EDIT returneras från confirm, ska anropet nekas med edit-marker utan att krascha."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.EDIT
    
    tc = {"id": "1", "function": {"name": "terminal", "arguments": '{"command": "echo test"}'}}
    
    res = dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-1")
    assert res == "[declined: edit requested]"
    hooks.confirm.assert_called_once()
    hooks.declined.assert_called_once_with("terminal", "edit requested (not yet implemented)")


def test_single_confirm_runs_and_allowlists_no_second_prompt(tmp_path):
    """Verifiera att exakt EN confirm-prompt körs och verktyget allowlistas och körs."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    
    tc = {"id": "1", "function": {"name": "terminal", "arguments": '{"command": "echo hi"}'}}
    
    res = dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-test")
    assert hooks.confirm.call_count == 1
    req = hooks.confirm.call_args[0][0]
    assert isinstance(req, ConfirmRequest)
    assert req.tool_name == "terminal"
    assert req.args == {"command": "echo hi"}
    assert _SESSION_ALLOWLIST.is_allowed("sess-test", "terminal")

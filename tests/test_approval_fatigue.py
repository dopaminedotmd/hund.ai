"""Tester for Approval Fatigue Mitigation (Session Allowlist)."""
from unittest.mock import MagicMock, patch
import pytest

from hund.agent.safety import PermissionEngine, RiskLevel
from hund.agent.tool_dispatch import dispatch_tool_call, _SESSION_ALLOWLIST
from hund.tools.default_tools import register_defaults


@pytest.fixture(autouse=True)
def clear_allowlist():
    _SESSION_ALLOWLIST.clear()
    yield
    _SESSION_ALLOWLIST.clear()


def test_confirm_gets_session_allowlisted(tmp_path):
    """Om användaren väljer 'a' (alla) på ett CONFIRM-verktyg, ska nästa anrop auto-tillåtas."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    
    # Första anropet: användaren svarar ja på körning, och 'a' på tillåt alla
    # console.input kallas två gånger
    console.input.side_effect = ["j", "a"]
    
    tc = {"id": "1", "function": {"name": "terminal", "arguments": '{"command": "dir"}'}}
    
    # Första anropet går igenom och lägger till terminal i allowlist
    res1 = dispatch_tool_call(tc, engine, console)
    assert res1 != "[declined by user]"
    assert "terminal" in _SESSION_ALLOWLIST
    
    # Andra anropet ska inte anropa console.input alls (eftersom det auto-tillåts via SAFE/allowlist)
    console.input.reset_mock()
    console.input.side_effect = AssertionError("Should not prompt user")
    
    res2 = dispatch_tool_call(tc, engine, console)
    assert res2 != "[declined by user]"
    console.input.assert_not_called()


def test_dangerous_cannot_be_allowlisted(tmp_path):
    """DANGEROUS verktyg får aldrig läggas till i session-allowlist."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    
    # Användaren svarar ja, och försöker svara 'a' (även om vi inte frågar, men om de skulle svara 'a' i prompten)
    # console.input kallas en gång för dangerous (eftersom vi inte erbjuder allowlist för DANGEROUS)
    console.input.side_effect = ["j"]
    
    tc = {"id": "1", "function": {"name": "delete_file", "arguments": '{"path": "x.txt"}'}}
    
    # Skapa filen så att delete fungerar
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    
    res1 = dispatch_tool_call(tc, engine, console)
    assert res1 != "[declined by user]"
    # DANGEROUS ska inte finnas i allowlist
    assert "delete_file" not in _SESSION_ALLOWLIST
    
    # Nästa anrop av delete_file ska fortfarande prompta användaren
    console.input.reset_mock()
    console.input.side_effect = ["n"]  # Neka den här gången
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    
    res2 = dispatch_tool_call(tc, engine, console)
    assert res2 == "[declined by user]"
    console.input.assert_called_once()

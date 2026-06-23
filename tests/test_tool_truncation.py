"""Tool output truncation — resultat over 50KB ska trunkeras."""
from unittest.mock import patch, MagicMock

from hund.agent.safety import PermissionEngine, RiskLevel
from hund.agent.tool_dispatch import dispatch_tool_call


def _make_tc(name: str, args: dict) -> dict:
    """Skapa ett tool_call-dict i OpenAI-format."""
    import json
    return {
        "id": "call_test",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def test_tool_output_truncation():
    """Tool-resultat over 50KB ska trunkeras med TRUNCATED-markor."""
    big_output = "x" * 100_000  # 100KB

    engine = PermissionEngine()
    console = MagicMock()
    tc = _make_tc("read_file", {"path": "big.txt"})

    with patch("hund.agent.tool_dispatch.registry") as mock_reg:
        mock_reg.call.return_value = big_output
        result = dispatch_tool_call(tc, engine, console, auto_approve_safe=True)

    assert len(result) < 100_000
    assert "[TRUNCATED" in result
    assert result.startswith("x" * 100)


def test_small_output_not_truncated():
    """Tool-resultat under 50KB ska inte trunkeras."""
    small_output = "hello world"

    engine = PermissionEngine()
    console = MagicMock()
    tc = _make_tc("read_file", {"path": "small.txt"})

    with patch("hund.agent.tool_dispatch.registry") as mock_reg:
        mock_reg.call.return_value = small_output
        result = dispatch_tool_call(tc, engine, console, auto_approve_safe=True)

    assert result == "hello world"
    assert "[TRUNCATED" not in result

"""Tests for RPC tool calling layer."""
import io
import json
import sys
from unittest.mock import patch, MagicMock

import pytest

from hund.agent.rpc import ToolRequest, ToolResponse, call_tool, serve_rpc
from hund.agent.safety import PermissionEngine, RiskLevel


def test_dataclasses():
    req = ToolRequest(id=1, tool="read_file", args={"path": "x"})
    assert req.id == 1
    assert req.tool == "read_file"
    assert req.args == {"path": "x"}

    resp = ToolResponse(id=1, result="ok", error=None)
    assert resp.id == 1
    assert resp.result == "ok"
    assert resp.error is None


def test_call_tool_success():
    """call_tool ska skriva en request till stdout och läsa svaret från stdin."""
    mock_stdin = io.StringIO('{"type": "response", "id": 1, "result": "hello", "error": null}\n')
    mock_stdout = io.StringIO()
    
    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
        res = call_tool("read_file", {"path": "test.txt"})
        
        assert res == "hello"
        req_sent = json.loads(mock_stdout.getvalue().strip())
        assert req_sent["type"] == "request"
        assert req_sent["tool"] == "read_file"
        assert req_sent["args"] == {"path": "test.txt"}


def test_call_tool_error_response():
    """Om parent returnerar ett fel, ska call_tool returnera [error] ..."""
    mock_stdin = io.StringIO('{"type": "response", "id": 1, "result": "", "error": "denied"}\n')
    mock_stdout = io.StringIO()
    
    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
        res = call_tool("read_file", {"path": "test.txt"})
        assert res == "[error] denied"


def test_serve_rpc_success():
    """serve_rpc ska läsa requests, anropa registry och skicka responses."""
    # En request rad, en vanlig rad (script output)
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "read_file", "args": {"path": "a.txt"}}\n'
        "Ordinary script output print statement\n"
    )
    write_stream = io.StringIO()
    
    mock_engine = MagicMock()
    # mock_engine.classify returnerar en mock med risk = SAFE
    mock_decision = MagicMock()
    mock_decision.risk = RiskLevel.SAFE
    mock_engine.classify.return_value = mock_decision
    
    with patch("hund.tools.registry.call", return_value="content of a.txt") as mock_reg_call:
        stdout_captured = serve_rpc(
            read_stream,
            write_stream,
            engine=mock_engine,
        )
        
        mock_reg_call.assert_called_once_with("read_file", {"path": "a.txt"})
        mock_engine.classify.assert_called_once_with("read_file", {"path": "a.txt"})
        
        # Kolla det som skrevs till stdin (write_stream)
        response_sent = json.loads(write_stream.getvalue().strip())
        assert response_sent["type"] == "response"
        assert response_sent["result"] == "content of a.txt"
        assert response_sent["error"] is None
        
        # Vanlig print stream ska returneras av serve_rpc
        assert stdout_captured == "Ordinary script output print statement"


def test_serve_rpc_blocked_by_engine():
    """Om engine klassificerar anropet som blocked, returnera fel."""
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "delete_file", "args": {"path": "a.txt"}}\n'
    )
    write_stream = io.StringIO()
    
    mock_engine = MagicMock()
    mock_decision = MagicMock()
    mock_decision.risk = RiskLevel.BLOCKED
    mock_decision.reason = "TCB protection"
    mock_engine.classify.return_value = mock_decision
    
    stdout_captured = serve_rpc(read_stream, write_stream, engine=mock_engine)
    
    response_sent = json.loads(write_stream.getvalue().strip())
    assert response_sent["error"] == "TCB protection"
    assert response_sent["result"] == ""


def test_serve_rpc_blocked_tools():
    """Om verktyget är med i blocked_tools setet, returnera fel."""
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "execute_code", "args": {"code": "print(1)"}}\n'
    )
    write_stream = io.StringIO()
    
    mock_engine = MagicMock()
    
    stdout_captured = serve_rpc(
        read_stream,
        write_stream,
        engine=mock_engine,
        blocked_tools={"execute_code"}
    )
    
    response_sent = json.loads(write_stream.getvalue().strip())
    assert "blockerad" in response_sent["error"]
    # engine.classify ska inte ens ha anropats
    mock_engine.classify.assert_not_called()

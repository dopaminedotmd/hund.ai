"""Tests for execute_code tool."""
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from hund.agent.safety import PermissionEngine, RiskLevel
from hund.tools.execute_code import run_code


def test_run_code_no_code():
    res = run_code({})
    assert "[error] 'code' parameter saknas" in res


def test_run_code_simple_print():
    """Kör ett enkelt python-script som skriver ut text."""
    res = run_code({"code": "print('hello from sub')"})
    assert "hello from sub" in res
    assert "[stderr]" not in res


def test_run_code_stderr():
    """Kör ett script som skriver till stderr."""
    res = run_code({"code": "import sys; sys.stderr.write('error message\\n')"})
    assert "[stderr]" in res
    assert "error message" in res


def test_run_code_blocked_tools():
    """Verifiera att anrop till blockerade tools ger fel."""
    code = (
        "res = call_tool('execute_code', {'code': 'print(1)'})\n"
        "print('RESULT:', res)\n"
    )
    res = run_code({"code": code})
    assert "RESULT: [error] tool 'execute_code' ar blockerad i execute_code" in res


def test_run_code_timeout():
    """Om wait() kastar TimeoutExpired, ska vi döda processen och returnera timeout-fel."""
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="python", timeout=300), 0]
        mock_popen_cls.return_value = mock_proc
        
        with patch("hund.agent.rpc.serve_rpc", return_value=""):
            res = run_code({"code": "import time; time.sleep(1)"})
            assert "[error] execute_code timeout (300s)" in res
            mock_proc.kill.assert_called_once()


def test_run_code_max_tool_calls():
    """Verifiera att anrop över gränsen blockeras i serve_rpc."""
    # Vi mockar serve_rpc för att simulera att max anrop överskridits
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_popen_cls.return_value = mock_proc
        
        with patch("hund.agent.rpc.serve_rpc", return_value="some output") as mock_serve:
            res = run_code({"code": "dummy"})
            mock_serve.assert_called_once()
            # serve_rpc ska ha anropats med max_calls=50
            assert mock_serve.call_args[1]["max_calls"] == 50

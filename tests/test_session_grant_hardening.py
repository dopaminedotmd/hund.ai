"""RED/GREEN tests for hardened session allowlist in tool dispatch (R1)."""
import json
from unittest.mock import MagicMock, patch
import pytest

from hund.agent.safety import Decision, PermissionEngine, RiskLevel
from hund.agent.tool_dispatch import SessionAllowlist, _SESSION_ALLOWLIST, dispatch_tool_call
from hund.agent.types import ConfirmVerdict
from hund.tools.default_tools import register_defaults
from hund.tools.types import ToolKind, create_success_result


@pytest.fixture(autouse=True)
def clean_allowlist():
    _SESSION_ALLOWLIST.clear()
    yield
    _SESSION_ALLOWLIST.clear()


def test_session_allowlist_requires_exact_canonical_arguments():
    """Terminal session grant matches tool+policy (any args); non-terminal binds exact args."""
    allowlist = SessionAllowlist()
    decision = Decision(
        RiskLevel.CONFIRM,
        allowed=True,
        reason="Git push requires confirmation",
        policy_id="terminal.git_push",
        session_allowable=True,
    )
    args_feature = {"command": "git push origin feature"}
    args_main = {"command": "git push origin main"}

    # Allow git push origin feature
    assert allowlist.allow("sess-1", "terminal", decision, args=args_feature) is True

    # Any args under same terminal policy matches (one click covers the session)
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_feature, risk=RiskLevel.CONFIRM) is True
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_main, risk=RiskLevel.CONFIRM) is True

    # Non-terminal tools still bind exact args
    decision_write = Decision(
        RiskLevel.CONFIRM,
        allowed=True,
        reason="Write requires confirmation",
        policy_id="write_file.content",
        session_allowable=True,
    )
    allowlist.allow("sess-1", "write_file", decision_write, args={"path": "a.txt"})
    assert allowlist.is_allowed("sess-1", "write_file", "write_file.content", args={"path": "a.txt"}, risk=RiskLevel.CONFIRM) is True
    assert allowlist.is_allowed("sess-1", "write_file", "write_file.content", args={"path": "b.txt"}, risk=RiskLevel.CONFIRM) is False

    # Different session MUST NOT match
    assert allowlist.is_allowed("sess-2", "terminal", "terminal.git_push", args=args_feature, risk=RiskLevel.CONFIRM) is False


def test_session_allowlist_negative_matching_dimensions():
    """A grant for (terminal, policy X, risk CONFIRM, args A) must NOT match other tool, policy, risk, or args."""
    allowlist = SessionAllowlist()
    decision = Decision(
        RiskLevel.CONFIRM,
        allowed=True,
        reason="Git push requires confirmation",
        policy_id="terminal.git_push",
        session_allowable=True,
    )
    args_feature = {"command": "git push origin feature"}
    args_main = {"command": "git push origin main"}

    assert allowlist.allow("sess-1", "terminal", decision, args=args_feature) is True

    # (a) Different tool MUST NOT match
    assert allowlist.is_allowed("sess-1", "write_file", "terminal.git_push", args=args_feature, risk=RiskLevel.CONFIRM) is False
    assert allowlist.is_allowed("sess-1", "execute_code", "terminal.git_push", args=args_feature, risk=RiskLevel.CONFIRM) is False

    # (b) Different policy MUST NOT match
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_pull", args=args_feature, risk=RiskLevel.CONFIRM) is False
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.unknown", args=args_feature, risk=RiskLevel.CONFIRM) is False

    # (c) Different risk MUST NOT match
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_feature, risk=RiskLevel.SAFE) is False
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_feature, risk=RiskLevel.DANGEROUS) is False

    # (d) Different args under same terminal policy MATCH (session grant is policy-scoped)
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_main, risk=RiskLevel.CONFIRM) is True
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args={"command": "git push"}, risk=RiskLevel.CONFIRM) is True


def test_session_allowlist_preserves_command_bytes_no_casefold_no_wildcard():
    """Non-terminal grants bind exact command bytes; terminal grants are policy-scoped."""
    allowlist = SessionAllowlist()
    decision = Decision(
        RiskLevel.CONFIRM,
        allowed=True,
        reason="Terminal command",
        policy_id="terminal.git_push",
        session_allowable=True,
    )
    args_lower = {"command": "git push origin feature"}
    args_upper = {"command": "git push origin FEATURE"}

    allowlist.allow("sess-1", "terminal", decision, args=args_lower)

    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_lower, risk=RiskLevel.CONFIRM) is True
    # Terminal grants are policy-scoped: case differences still match
    assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args_upper, risk=RiskLevel.CONFIRM) is True

    # Non-terminal tools still bind exact bytes
    decision_write = Decision(
        RiskLevel.CONFIRM,
        allowed=True,
        reason="Write requires confirmation",
        policy_id="write_file.content",
        session_allowable=True,
    )
    allowlist.allow("sess-1", "write_file", decision_write, args=args_lower)
    assert allowlist.is_allowed("sess-1", "write_file", "write_file.content", args=args_lower, risk=RiskLevel.CONFIRM) is True
    assert allowlist.is_allowed("sess-1", "write_file", "write_file.content", args=args_upper, risk=RiskLevel.CONFIRM) is False


def test_session_allowlist_revoke_and_clear_emits_trace_events():
    """Explicit revocation and session clear removes grants and emits trace events."""
    allowlist = SessionAllowlist()
    decision = Decision(
        RiskLevel.CONFIRM,
        allowed=True,
        reason="Terminal command",
        policy_id="terminal.git_push",
        session_allowable=True,
    )
    args1 = {"command": "git push origin feature"}
    args2 = {"command": "git push origin staging"}

    events_emitted = []
    def fake_write_event(event):
        events_emitted.append(event)

    with patch("hund.agent.tool_dispatch.write_event", side_effect=fake_write_event):
        allowlist.allow("sess-1", "terminal", decision, args=args1)
        allowlist.allow("sess-1", "terminal", decision, args=args2)
        assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args1, risk=RiskLevel.CONFIRM) is True

        # 1. Revoke specific grant entry (policy-scoped match may still hold via other entry)
        assert allowlist.revoke(
            "sess-1", "terminal", "terminal.git_push", args=args1, risk=RiskLevel.CONFIRM, run_id="run-revoke"
        ) is True
        assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args2, risk=RiskLevel.CONFIRM) is True

        # Revoke the remaining entry -> no policy-scoped match remains
        assert allowlist.revoke(
            "sess-1", "terminal", "terminal.git_push", args=args2, risk=RiskLevel.CONFIRM
        ) is True
        assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args1, risk=RiskLevel.CONFIRM) is False

        # Verify session_grant_revoked trace events (one per revoke)
        revoked_events = [e for e in events_emitted if e.event_type == "session_grant_revoked"]
        assert len(revoked_events) == 2
        assert revoked_events[0].session_id == "sess-1"
        assert revoked_events[0].tool_name == "terminal"
        assert revoked_events[0].payload_redacted["policy_id"] == "terminal.git_push"
        assert revoked_events[0].payload_redacted["args"] == args1

        # 2. Clear entire session (grant exists -> clear event emitted)
        allowlist.allow("sess-1", "terminal", decision, args={"command": "git push origin hotfix"})
        allowlist.clear_session("sess-1", run_id="run-clear")
        assert allowlist.is_allowed("sess-1", "terminal", "terminal.git_push", args=args2, risk=RiskLevel.CONFIRM) is False

        # Verify session_grant_cleared trace event
        cleared_events = [e for e in events_emitted if e.event_type == "session_grant_cleared"]
        assert len(cleared_events) == 1
        assert cleared_events[0].session_id == "sess-1"
        assert cleared_events[0].payload_redacted["session_id"] == "sess-1"


def test_dispatch_tool_call_emits_session_grant_trace_events(tmp_path):
    """Dispatching tool call emits trace events for grant add and hit."""
    register_defaults(tmp_path)
    engine = PermissionEngine(tmp_path)
    console = MagicMock()
    hooks = MagicMock()
    hooks.confirm.return_value = ConfirmVerdict.ALLOW_SESSION
    tc = {
        "id": "tc1",
        "function": {
            "name": "terminal",
            "arguments": json.dumps({"command": "git push origin feature"}),
        },
    }

    events_emitted = []
    def fake_write_event(event):
        events_emitted.append(event)

    with patch("hund.agent.tool_dispatch.registry.call_typed", return_value=create_success_result(ToolKind.EXECUTION, "ok")), \
         patch("hund.agent.tool_dispatch.write_event", side_effect=fake_write_event):

        # First call: user approves with ALLOW_SESSION -> session_grant_added
        dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-trace", run_id="run-1")
        assert any(e.event_type == "session_grant_added" for e in events_emitted)

        # Second call with same command -> session_grant_hit, no modal prompt
        hooks.confirm.reset_mock()
        dispatch_tool_call(tc, engine, console, hooks=hooks, session_id="sess-trace", run_id="run-2")
        hooks.confirm.assert_not_called()
        assert any(e.event_type == "session_grant_hit" for e in events_emitted)

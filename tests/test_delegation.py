"""Tests for subagent delegation."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from hund.agent.delegation import _run_child, delegate_tasks, DelegationResult
from hund.providers.base import Message, CompletionResult
from hund.tools.default_tools import register_defaults


class _FakeClient:
    def __init__(self, response_text="result"):
        self.response_text = response_text
        self.completions = []

    def complete(self, messages, tools=None):
        self.completions.append(messages)
        # Om sista meddelandet har tool calls, returnera ett svar utan tool_calls för att stoppa loopen
        last_msg = messages[-1]
        if getattr(last_msg, "tool_calls", None):
            return CompletionResult(text=self.response_text, tool_calls=[])
        return CompletionResult(text=self.response_text, tool_calls=[])


def test_child_blocked_tool(tmp_path):
    """Barn nekas att anropa blocked tools i restricted mode."""
    register_defaults(tmp_path)
    client = MagicMock()
    # Mocka complete att returnera ett tool call till execute_code
    mock_tc = {"id": "1", "function": {"name": "execute_code", "arguments": '{"code": "print(1)"}'}}
    client.complete.side_effect = [
        CompletionResult(text="", tool_calls=[mock_tc]),
        CompletionResult(text="done", tool_calls=[])
    ]
    
    # execute_code ska klassificeras som blocked i Restricted mode för barn
    res = _run_child(
        task_id=0,
        goal="do evil",
        context="",
        client=client,
        allowed_tools={"execute_code"}  # Skicka med för att den ska finnas i child_schemas
    )
    
    assert res.success is True
    assert res.summary == "done"


def test_child_returns_summary(tmp_path):
    """Verifiera att subagenten returnerar assistantens sammanfattning."""
    register_defaults(tmp_path)
    client = _FakeClient("Uppgiften klar. Allt ser fint ut.")
    
    res = _run_child(
        task_id=1,
        goal="skriv en dikt",
        context="",
        client=client,
        allowed_tools={"read_file"}
    )
    
    assert res.success is True
    assert res.summary == "Uppgiften klar. Allt ser fint ut."


def test_delegate_parallel(tmp_path):
    """Spawna flera tasks parallellt."""
    register_defaults(tmp_path)
    client = _FakeClient("klar")
    
    tasks = [
        {"goal": "Analysera A", "context": "A data"},
        {"goal": "Analysera B", "context": "B data"}
    ]
    
    results = delegate_tasks(tasks, client, allowed_tools={"read_file"})
    
    assert len(results) == 2
    assert results[0].success is True
    assert results[0].summary == "klar"
    assert results[1].success is True
    assert results[1].summary == "klar"


def test_child_cannot_use_execute_code():
    """Barn far inte anropa execute_code."""
    from hund.agent.safety import PermissionEngine, RiskLevel
    engine = PermissionEngine(mode="subagent")
    dec = engine.classify("execute_code", {})
    assert dec.risk == RiskLevel.BLOCKED


def test_child_cannot_use_delegate_task():
    """Barn far inte spawna barnbarn (max_depth=1)."""
    from hund.agent.safety import PermissionEngine, RiskLevel
    engine = PermissionEngine(mode="subagent")
    dec = engine.classify("delegate_task", {})
    assert dec.risk == RiskLevel.BLOCKED


def test_child_can_use_safe_tools():
    """Barn far anvanda SAFE tools som read_file."""
    from hund.agent.safety import PermissionEngine, RiskLevel
    engine = PermissionEngine(mode="subagent")
    dec = engine.classify("read_file", {"path": "test.txt"})
    assert dec.risk == RiskLevel.SAFE


def test_main_agent_can_use_restricted_tools():
    """Huvudagenten får anropa execute_code och delegate_task (CONFIRM-nivå)."""
    from hund.agent.safety import PermissionEngine, RiskLevel
    engine = PermissionEngine(mode="main_agent")
    for tool in ("execute_code", "delegate_task"):
        dec = engine.classify(tool, {})
        assert dec.risk == RiskLevel.CONFIRM



def test_child_emits_trace_with_parent_run_id(tmp_path, monkeypatch):
    import hund.paths as paths
    from hund.trace.events import list_events_by_session

    monkeypatch.setattr(paths, "hund_home", lambda: tmp_path / "home")
    monkeypatch.setattr(paths, "db_path", lambda: tmp_path / "home" / "hund.db")
    register_defaults(tmp_path)
    client = _FakeClient("klar")

    res = _run_child(
        task_id=7,
        goal="analysera",
        context="ctx",
        client=client,
        allowed_tools={"read_file"},
        parent_run_id="parent-run",
        session_id="delegation-session",
        workspace_id=str(tmp_path),
    )

    assert res.success is True
    events = list_events_by_session("delegation-session")
    assert [event.event_type for event in events] == ["run_started", "run_completed"]
    assert {event.parent_run_id for event in events} == {"parent-run"}
    assert {event.actor for event in events} == {"subagent"}


def test_delegate_tasks_passes_parent_run_id_to_children(tmp_path, monkeypatch):
    import hund.paths as paths
    from hund.trace.events import list_events_by_session

    monkeypatch.setattr(paths, "hund_home", lambda: tmp_path / "home")
    monkeypatch.setattr(paths, "db_path", lambda: tmp_path / "home" / "hund.db")
    register_defaults(tmp_path)
    client = _FakeClient("klar")

    results = delegate_tasks(
        [{"goal": "A"}, {"goal": "B"}],
        client,
        allowed_tools={"read_file"},
        parent_run_id="parent-xyz",
        session_id="delegation-parent-session",
        workspace_id=str(tmp_path),
        max_workers=1,
    )

    assert len(results) == 2
    events = list_events_by_session("delegation-parent-session")
    assert len(events) == 4
    assert {event.parent_run_id for event in events} == {"parent-xyz"}
    assert [event.event_type for event in events].count("run_started") == 2
    assert [event.event_type for event in events].count("run_completed") == 2


"""RED/GREEN tests for shared exactly-once memory capture finalization in agent loop (R1)."""
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest

from hund.agent.loop import _agent_turn
from hund.agent.safety import PermissionEngine
from hund.config import HundConfig
from hund.providers.base import Message


@pytest.fixture
def fake_runtime(tmp_path):
    console = MagicMock()
    engine = PermissionEngine(tmp_path)
    cfg = HundConfig()
    session_id = "test-session-mem"
    return console, engine, cfg, session_id


def test_memory_capture_runs_on_normal_text_response(fake_runtime, tmp_path):
    console, engine, cfg, session_id = fake_runtime
    client = MagicMock()
    # Return normal text without tool calls
    client.chat.return_value = MagicMock(
        text="hund har förstått dina önskemål.",
        tool_calls=[],
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=50,
    )
    messages = [
        Message(role="system", content="hund system"),
        Message(role="user", content="Kom ihåg att mitt favoritramverk är FastAPI."),
    ]

    with patch("hund.agent.loop._memory_capture_hook") as mock_hook:
        _agent_turn(
            console, client, messages, [], engine, cfg, session_id,
        )

        assert mock_hook.call_count == 1
        args, kwargs = mock_hook.call_args
        assert "FastAPI" in args[0]
        assert kwargs["workspace"] == Path(engine.workspace_root)
        assert kwargs["evidence_id"] is not None


def test_memory_capture_runs_on_max_tool_rounds(fake_runtime, tmp_path):
    console, engine, cfg, session_id = fake_runtime
    client = MagicMock()
    # Always return a tool call to exhaust max rounds
    client.chat.return_value = MagicMock(
        text="",
        tool_calls=[{"id": "call_1", "function": {"name": "search_files", "arguments": "{}"}}],
        finish_reason="tool_calls",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=50,
    )
    messages = [
        Message(role="system", content="hund system"),
        Message(role="user", content="Kom ihåg att jag gillar FastAPI."),
    ]

    with patch("hund.agent.loop._memory_capture_hook") as mock_hook, \
         patch("hund.agent.loop.dispatch_tool_call", return_value="ok"):
        _agent_turn(
            console, client, messages, [], engine, cfg, session_id,
        )

        # Must run exactly once upon max rounds finalization
        assert mock_hook.call_count == 1
        args, kwargs = mock_hook.call_args
        assert "FastAPI" in args[0]


def test_memory_capture_runs_on_repeated_tool_failure(fake_runtime, tmp_path):
    console, engine, cfg, session_id = fake_runtime
    client = MagicMock()
    client.chat.return_value = MagicMock(
        text="",
        tool_calls=[{"id": "call_1", "function": {"name": "search_files", "arguments": "{}"}}],
        finish_reason="tool_calls",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=50,
    )
    messages = [
        Message(role="system", content="hund system"),
        Message(role="user", content="Kom ihåg att jag gillar FastAPI."),
    ]

    with patch("hund.agent.loop._memory_capture_hook") as mock_hook, \
         patch("hund.agent.loop.dispatch_tool_call", return_value="[error] failed"):
        _agent_turn(
            console, client, messages, [], engine, cfg, session_id,
        )

        # Must run exactly once upon terminal failure exit
        assert mock_hook.call_count == 1

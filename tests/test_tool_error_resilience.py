"""Tests for tool error recovery, timeout protection, and loop resilience."""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch
import pytest

from hund.agent.loop import _agent_turn
from hund.config import HundConfig
from hund.providers.base import CompletionResult, Message
from hund.providers.openai_compatible import OpenAICompatibleClient


def test_consecutive_tool_errors_aborts_turn() -> None:
    """If tools fail with [error] 3 times in a row, the loop must terminate early."""
    console = MagicMock()
    sink = MagicMock()
    cfg = HundConfig.load()
    engine = MagicMock()
    engine.workspace_root = "."

    # Mock client that returns tool calls every time
    client = MagicMock()
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path": "missing.py"}'},
    }

    def fake_stream(messages, tools=None):
        client.last_result = CompletionResult(
            text="",
            tool_calls=[tool_call],
            finish_reason="tool_calls",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            latency_ms=50,
        )
        yield ""

    client.stream = fake_stream

    messages = [Message(role="user", content="read a missing file")]

    with patch("hund.agent.loop.dispatch_tool_call", return_value="[error] fil saknas"):
        _agent_turn(
            console,
            client,
            messages,
            schemas=[],
            engine=engine,
            cfg=cfg,
            session_id="test-session",
            sink=sink,
        )

    # Sink should have received the repeated tool failure error
    sink.error.assert_called_with("[red]repeated tool failure — stopping turn[/red]")


def test_provider_stream_deadline_timeout() -> None:
    """Verify that a stream running past its deadline raises a RuntimeError."""
    client = OpenAICompatibleClient(
        base_url="https://api.example.com",
        api_key="test-key",
        default_model="test-model",
        timeout=0.01,  # 10ms timeout for instant expiration
    )

    def mock_iter_lines():
        import time
        time.sleep(0.02)
        yield "data: {\"choices\": [{\"delta\": {\"content\": \"hello\"}}]}"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines = mock_iter_lines

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_resp
    mock_ctx.__exit__.return_value = None

    mock_http_client = MagicMock()
    mock_http_client.stream.return_value = mock_ctx
    mock_http_client.__enter__.return_value = mock_http_client
    mock_http_client.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_http_client):
        with pytest.raises(RuntimeError) as exc_info:
            list(client.stream([Message(role="user", content="hi")]))
        assert "timeout" in str(exc_info.value).lower()


def test_thinking_called_once_across_multiple_tool_rounds() -> None:
    """Verify sink.thinking() is only called once at the start of a multi-round turn."""
    console = MagicMock()
    sink = MagicMock()
    cfg = HundConfig.load()
    engine = MagicMock()
    engine.workspace_root = "."

    client = MagicMock()
    rounds = [0]

    def fake_stream(messages, tools=None):
        rounds[0] += 1
        if rounds[0] < 3:
            client.last_result = CompletionResult(
                text="",
                tool_calls=[{
                    "id": f"call_{rounds[0]}",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "foo.py"}'},
                }],
                finish_reason="tool_calls",
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
                latency_ms=50,
            )
        else:
            client.last_result = CompletionResult(
                text="final response",
                tool_calls=None,
                finish_reason="stop",
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
                latency_ms=50,
            )
            yield "final response"

    client.stream = fake_stream
    messages = [Message(role="user", content="multi step task")]

    with patch("hund.agent.loop.dispatch_tool_call", return_value="ok content"):
        _agent_turn(
            console,
            client,
            messages,
            schemas=[],
            engine=engine,
            cfg=cfg,
            session_id="test-session",
            sink=sink,
        )

    # sink.thinking() must be called exactly once
    assert sink.thinking.call_count == 1


def test_last_round_is_reserved_for_final_synthesis() -> None:
    console = MagicMock()
    sink = MagicMock()
    cfg = HundConfig.load()
    engine = MagicMock()
    engine.workspace_root = "."
    client = MagicMock()
    seen_tools = []

    def fake_stream(messages, tools=None):
        seen_tools.append(tools)
        if tools:
            client.last_result = CompletionResult(
                text="",
                tool_calls=[{
                    "id": f"call_{len(seen_tools)}",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "foo.py"}'},
                }],
                finish_reason="tool_calls",
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
                latency_ms=1,
            )
            return
        client.last_result = CompletionResult(
            text="hund har tillräcklig evidens.",
            tool_calls=None,
            finish_reason="stop",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            latency_ms=1,
        )
        yield "hund har tillräcklig evidens."

    client.stream = fake_stream
    messages = [Message(role="user", content="inspect")]
    with (
        patch("hund.agent.loop.dispatch_tool_call", return_value="ok"),
        patch("hund.agent.loop._session_save"),
        patch("hund.agent.loop._feedback_hook"),
        patch("hund.agent.loop._runtime_learning_hook"),
    ):
        _agent_turn(
            console, client, messages, schemas=[{"name": "read_file"}],
            engine=engine, cfg=cfg, session_id="test-session", sink=sink,
        )

    assert len(seen_tools) == 8
    assert all(tools for tools in seen_tools[:-1])
    assert seen_tools[-1] == []
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "hund har tillräcklig evidens."

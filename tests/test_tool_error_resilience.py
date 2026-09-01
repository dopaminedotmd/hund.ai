"""Tests for tool error recovery, timeout protection, and loop resilience."""
from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hund.agent.loop import _agent_turn
from hund.config import HundConfig
from hund.providers.base import CompletionResult, Message
from hund.providers.openai_compatible import OpenAICompatibleClient


@pytest.mark.parametrize(
    ("text", "finish_reason"),
    [
        ("", "stop"),
        ("", "tool_calls"),
        ("partial response", "length"),
        ("filtered response", "content_filter"),
    ],
)
def test_incomplete_provider_results_are_visible_failures(
    text: str, finish_reason: str
) -> None:
    console = MagicMock()
    sink = MagicMock()
    cfg = HundConfig.load()
    engine = MagicMock(workspace_root=".")
    client = MagicMock()

    def fake_stream(messages, tools=None):
        client.last_result = CompletionResult(
            text=text,
            tool_calls=[],
            finish_reason=finish_reason,
        )
        if text:
            yield text

    client.stream = fake_stream
    messages = [Message(role="user", content="continue")]

    with (
        patch("hund.agent.loop._session_save") as save,
        patch("hund.agent.loop._runtime_learning_hook") as learning,
    ):
        _agent_turn(
            console, client, messages, [], engine, cfg, "test-session", sink=sink
        )

    sink.clear_thinking.assert_called()
    sink.error.assert_called_once()
    assert [message.role for message in messages] == ["user"]
    assert not any(call.args[1] == "assistant" for call in save.call_args_list)
    learning.assert_not_called()


def test_successful_final_turn_captures_memory_once() -> None:
    console = MagicMock()
    sink = MagicMock()
    cfg = HundConfig.load()
    engine = MagicMock(workspace_root=Path("workspace"))
    client = MagicMock()

    def fake_stream(messages, tools=None):
        client.last_result = CompletionResult(
            text="hund remembers.", tool_calls=[], finish_reason="stop"
        )
        yield "hund remembers."

    client.stream = fake_stream
    messages = [Message(role="user", content="My name is William.")]
    with (
        patch("hund.agent.loop._session_save"),
        patch("hund.agent.loop._feedback_hook"),
        patch("hund.agent.loop._runtime_learning_hook"),
        patch("hund.paths.workspace_id", return_value="workspace-id"),
        patch(
            "hund.agent.memory_extractor.extract_and_record_memories"
        ) as capture,
    ):
        capture.side_effect = OSError("memory store unavailable")
        _agent_turn(
            console, client, messages, [], engine, cfg, "test-session", sink=sink
        )

    capture.assert_called_once()
    assert capture.call_args.args == ("My name is William.",)
    assert capture.call_args.kwargs["workspace_id"] == "workspace-id"
    assert capture.call_args.kwargs["evidence_id"]
    assert messages[-1].role == "assistant"


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


def test_tool_call_text_stays_hidden_until_confirmation() -> None:
    console = MagicMock()
    sink = MagicMock()
    cfg = HundConfig.load()
    engine = MagicMock(workspace_root=".")
    client = MagicMock()
    rounds = [0]
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "write_file", "arguments": '{"path":"x.txt","content":"x"}'},
    }

    def fake_stream(messages, tools=None):
        rounds[0] += 1
        if rounds[0] == 1:
            client.last_result = CompletionResult(
                text="The file is already changed.",
                tool_calls=[tool_call],
                finish_reason="tool_calls",
            )
            yield "The file is already changed."
        else:
            client.last_result = CompletionResult(
                text="hund changed the file.", tool_calls=[], finish_reason="stop"
            )
            yield "hund changed the file."

    client.stream = fake_stream
    messages = [Message(role="user", content="change x.txt")]

    with (
        patch("hund.agent.loop.dispatch_tool_call", return_value="ok"),
        patch("hund.agent.loop._session_save"),
        patch("hund.agent.loop._feedback_hook"),
        patch("hund.agent.loop._runtime_learning_hook"),
    ):
        _agent_turn(console, client, messages, [], engine, cfg, "test-session", sink=sink)

    assert all(call.args != ("The file is already changed.",) for call in sink.thinking.call_args_list)
    sink.chunk.assert_called_once_with("hund changed the file.")


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


def test_turn_cancellation_aborts_loop_immediately() -> None:
    """When sink reports cancellation (Ctrl+C), agent turn terminates immediately without emitting chunks or tools."""
    console = MagicMock()
    sink = MagicMock()
    cancelled = [False]
    sink.is_cancelled.side_effect = lambda: cancelled[0]

    cfg = HundConfig.load()
    engine = MagicMock(workspace_root=".")
    client = MagicMock()

    stream_chunks = []
    def fake_stream(messages, tools=None):
        cancelled[0] = True  # User presses Ctrl+C during streaming
        client.last_result = CompletionResult(
            text="some response that should not leak",
            tool_calls=[],
            finish_reason="stop",
        )
        yield "some chunk"

    client.stream = fake_stream
    messages = [Message(role="user", content="hello")]

    with (
        patch("hund.agent.loop._session_save") as save,
        patch("hund.agent.loop.dispatch_tool_call") as dispatch,
    ):
        _agent_turn(
            console, client, messages, [], engine, cfg, "test-session", sink=sink
        )

    sink.chunk.assert_not_called()
    sink.end_assistant.assert_not_called()
    dispatch.assert_not_called()
    assert not any(call.args[1] == "assistant" for call in save.call_args_list)

"""Tests for client stream retry backoff logic on rate limits."""
import pytest
from unittest.mock import MagicMock, patch

from hund.agent.loop import _agent_turn
from hund.providers.base import Message


def test_retry_on_429_success():
    """Om vi får 429 men det sedan lyckas, ska vi göra retry och till slut lyckas."""
    console = MagicMock()
    client = MagicMock()
    
    # Första gången kastar 429, andra gången returnerar chunks
    call_count = 0
    def mock_stream(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return ["hello", " world"]
        
    client.stream.side_effect = mock_stream
    
    # Ställ in last_result
    mock_result = MagicMock()
    mock_result.tool_calls = []
    mock_result.finish_reason = "stop"
    mock_result.prompt_tokens = 10
    mock_result.completion_tokens = 5
    mock_result.latency_ms = 100
    client.last_result = mock_result
    
    messages = [Message(role="user", content="hello")]
    
    with patch("time.sleep") as mock_sleep:
        _agent_turn(console, client, messages, [], MagicMock(), MagicMock(), "session_id")
        mock_sleep.assert_called_once_with(1)  # delay = 2 ** 0 = 1 sekund
        
    assert call_count == 2
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "hello world"


def test_retry_on_429_fails_after_max_retries():
    """Om vi får 429 hela tiden ska vi sluta efter 3 retries (4 försök totalt)."""
    console = MagicMock()
    client = MagicMock()
    
    client.stream.side_effect = RuntimeError("HTTP 429 Too Many Requests")
    
    messages = [Message(role="user", content="hello")]
    
    with patch("time.sleep") as mock_sleep:
        _agent_turn(console, client, messages, [], MagicMock(), MagicMock(), "session_id")
        assert mock_sleep.call_count == 3  # 1s, 2s, 4s
        
    assert messages == [Message(role="user", content="hello")]


def test_no_retry_on_other_errors():
    """Om vi får ett annat fel än 429 ska vi inte göra retry."""
    console = MagicMock()
    client = MagicMock()
    
    client.stream.side_effect = RuntimeError("500 Internal Server Error")
    
    messages = [Message(role="user", content="hello")]
    
    with patch("time.sleep") as mock_sleep:
        _agent_turn(console, client, messages, [], MagicMock(), MagicMock(), "session_id")
        mock_sleep.assert_not_called()
        
    assert messages == [Message(role="user", content="hello")]

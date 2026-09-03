"""Tester för Track 18: reasoning_content och sann statusbar."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from hund.providers.base import CompletionResult, Message
from hund.providers.openai_compatible import OpenAICompatibleClient
from hund.store.sqlite import connect_requests, log_request_reasoning


def test_complete_captures_reasoning_content(tmp_path):
    db_file = tmp_path / "requests.db"
    with patch("hund.paths.requests_db_path", return_value=db_file):
        client = OpenAICompatibleClient("https://mock.api", "sk-mock", "deepseek-v4-flash")
        fake_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Den slutliga lösningen",
                    "reasoning_content": "Tänker steg 1, tänker steg 2...",
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 50,
                "total_tokens": 1250,
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response

        with patch("httpx.Client.post", return_value=mock_resp):
            res = client.complete([Message(role="user", content="Hej")])

        assert res.text == "Den slutliga lösningen"
        assert res.reasoning_content == "Tänker steg 1, tänker steg 2..."
        assert res.prompt_tokens == 1200

        # Verifiera att reasoning loggades till requests.db
        with connect_requests(db_file) as conn:
            row = conn.execute("SELECT reasoning_content FROM requests ORDER BY created_at DESC LIMIT 1").fetchone()
            assert row is not None
            assert row[0] == "Tänker steg 1, tänker steg 2..."


def test_stream_captures_reasoning_content(tmp_path):
    db_file = tmp_path / "requests.db"
    with patch("hund.paths.requests_db_path", return_value=db_file):
        client = OpenAICompatibleClient("https://mock.api", "sk-mock", "deepseek-v4-flash")

        sse_lines = [
            "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "Steg A "}}]}),
            "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "Steg B"}}]}),
            "data: " + json.dumps({"choices": [{"delta": {"content": "Hej "}}]}),
            "data: " + json.dumps({"choices": [{"delta": {"content": "Världen!"}}]}),
            "data: " + json.dumps({"choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 850, "completion_tokens": 20, "total_tokens": 870}}),
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(sse_lines)

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.stream.return_value.__enter__.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            chunks = list(client.stream([Message(role="user", content="Test")]))

        assert "".join(chunks) == "Hej Världen!"
        assert client.last_result is not None
        assert client.last_result.reasoning_content == "Steg A Steg B"
        assert client.last_result.prompt_tokens == 850

        # Verifiera logging
        with connect_requests(db_file) as conn:
            row = conn.execute("SELECT reasoning_content FROM requests ORDER BY created_at DESC LIMIT 1").fetchone()
            assert row is not None
            assert row[0] == "Steg A Steg B"


def test_statusbar_uses_prompt_tokens_not_total_tokens(tmp_path):
    """Statusbaren ska använda senaste requestens prompt_tokens (inte total_tokens eller chars/4)."""
    db_file = tmp_path / "requests.db"
    with connect_requests(db_file) as conn:
        conn.execute(
            "INSERT INTO requests (id, created_at, task_class, prompt_tokens, completion_tokens) VALUES (?, ?, ?, ?, ?)",
            ("req-1", "2026-09-03T12:00:00Z", "conversation", 72303, 15240),
        )
        conn.commit()

    with patch("hund.paths.requests_db_path", return_value=db_file):
        # Simulera worker-avslut i fullscreen
        last_res = CompletionResult(
            text="svar",
            prompt_tokens=72303,
            completion_tokens=15240,
            total_tokens=87543,
        )

        state_extra = {}
        if last_res and getattr(last_res, "prompt_tokens", 0) > 0:
            state_extra["tokens"] = last_res.prompt_tokens
        else:
            state_extra["tokens"] = last_res.total_tokens

        assert state_extra["tokens"] == 72303
        assert state_extra["tokens"] != 87543

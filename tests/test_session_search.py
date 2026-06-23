"""Tester for session_search tool."""
from unittest.mock import patch
from hund.tools.session_search import search_sessions

def test_list_returns_recent():
    mock_rows = [
        ("abc12345def", "2026-06-23T20:00:00", "hej", 10, 1),
    ]
    with patch("hund.agent.sessions.list_sessions", return_value=mock_rows):
        result = search_sessions({"mode": "list"})
        assert "abc12345" in result
        assert "10 msg" in result
        assert "*" in result  # active marker

def test_search_returns_matches():
    mock_rows = [
        ("abc12345def", "user", "[CLAUDE]...[md]...", "2026-06-23T20:00:00"),
    ]
    with patch("hund.agent.sessions.search", return_value=mock_rows):
        result = search_sessions({"mode": "search", "query": "CLAUDE"})
        assert "CLAUDE" in result

def test_search_empty_query():
    result = search_sessions({"mode": "search", "query": ""})
    assert "error" in result

def test_search_no_results():
    with patch("hund.agent.sessions.search", return_value=[]):
        result = search_sessions({"mode": "search", "query": "xyzzy"})
        assert "inga traffar" in result

def test_limit_respected():
    mock_rows = [(f"id{i}", "user", f"snippet{i}", "2026-01-01") for i in range(30)]
    with patch("hund.agent.sessions.search", return_value=mock_rows):
        result = search_sessions({"mode": "search", "query": "test", "limit": 3})
        lines = result.split("\n")
        assert len(lines) <= 3

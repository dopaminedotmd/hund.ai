"""Tests for DuckDuckGo web_search tool."""
from unittest.mock import patch, MagicMock
from hund.tools.web_search import search_web

def test_search_returns_results():
    mock_results = [
        {"title": "Test", "href": "https://test.com", "body": "description"}
    ]
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = mock_results
        mock_ddgs.return_value.__enter__.return_value = instance
        result = search_web({"query": "test"})
        assert "Test" in result
        assert "https://test.com" in result

def test_search_empty_query():
    result = search_web({"query": ""})
    assert "error" in result

def test_search_no_results():
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = []
        mock_ddgs.return_value.__enter__.return_value = instance
        result = search_web({"query": "xyzzy123"})
        assert "inga resultat" in result

def test_search_api_error():
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        mock_ddgs.side_effect = RuntimeError("connection failed")
        result = search_web({"query": "test"})
        assert "error" in result

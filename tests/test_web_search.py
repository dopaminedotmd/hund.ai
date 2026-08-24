"""Tests for DuckDuckGo web_search tool."""
from unittest.mock import patch, MagicMock
from pathlib import Path

from hund.tools.types import ToolCallContext, ToolStatus
from hund.tools.url_provenance import UrlProvenanceStore
from hund.tools.web_search import search_web, search_web_typed

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


def test_typed_search_registers_result_urls():
    store = UrlProvenanceStore("search-test")
    context = ToolCallContext("search-test", "turn", Path.cwd(), store)
    mock_results = [
        {"title": "Test", "href": "https://example.com/page", "body": "description"}
    ]
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = mock_results
        mock_ddgs.return_value.__enter__.return_value = instance
        result = search_web_typed({"query": "test"}, context)
    assert result.status == ToolStatus.SUCCESS
    assert store.is_allowed("https://example.com/page")

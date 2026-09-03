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
    with patch("hund.tools.web_search._BACKOFF_SECONDS", 0.0), patch("hund.tools.web_search.DDGS") as mock_ddgs:
        mock_ddgs.side_effect = RuntimeError("connection failed")
        result = search_web({"query": "test"})
        assert "error" in result


def test_typed_search_registers_result_urls():
    store = UrlProvenanceStore("search-test")
    context = ToolCallContext("search-test", Path.cwd(), url_provenance=store)
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


def test_search_passes_max_results_15():
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = []
        mock_ddgs.return_value.__enter__.return_value = instance
        search_web_typed({"query": "test"}, None)
        instance.text.assert_called_once_with("test", max_results=15)


def test_search_retry_on_ddgs_exception_succeeds():
    mock_results = [{"title": f"T{i}", "href": f"https://example.com/{i}", "body": "b"} for i in range(5)]
    inst_fail = MagicMock()
    inst_fail.text.side_effect = RuntimeError("transient network drop")
    inst_ok = MagicMock()
    inst_ok.text.return_value = mock_results

    with patch("hund.tools.web_search._BACKOFF_SECONDS", 0.0), patch("hund.tools.web_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.__enter__.side_effect = [inst_fail, inst_ok]
        res = search_web_typed({"query": "gemma"}, None)

    assert res.status == ToolStatus.SUCCESS
    assert res.metadata["result_count"] == 5
    assert "[sparsamt resultat:" not in res.payload


def test_search_retry_fails_both_returns_guidance_error():
    with patch("hund.tools.web_search._BACKOFF_SECONDS", 0.0), patch("hund.tools.web_search.DDGS") as mock_ddgs:
        mock_ddgs.side_effect = RuntimeError("ddgs server unreachable")
        res = search_web_typed({"query": "gemma"}, None)

    assert res.status == ToolStatus.NETWORK_ERROR
    assert res.metadata["result_count"] == 0
    assert res.public_error == "sökningen misslyckades — försök igen, eventuellt med annan formulering"
    assert "sökningen misslyckades — försök igen, eventuellt med annan formulering" in res.to_llm_text()


def test_search_sparse_signal_under_4_results():
    sparse_results = [
        {"title": "Result 1", "href": "https://example.com/1", "body": "Snippet 1"},
        {"title": "Result 2", "href": "https://example.com/2", "body": "Snippet 2"},
    ]
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = sparse_results
        mock_ddgs.return_value.__enter__.return_value = instance
        res = search_web_typed({"query": "very specific query"}, None)

    assert res.status == ToolStatus.SUCCESS
    assert res.metadata["result_count"] == 2
    assert res.payload.startswith("[sparsamt resultat: 2 träffar — överväg breddad sökning]")


def test_search_empty_results_guidance_message():
    with patch("hund.tools.web_search.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = []
        mock_ddgs.return_value.__enter__.return_value = instance
        res = search_web_typed({"query": "nothing"}, None)

    assert res.status == ToolStatus.EMPTY
    assert res.metadata["result_count"] == 0
    assert res.public_error == "inga resultat — bredda eller förenkla sökfrågan"
    assert res.to_llm_text() == "(inga resultat — bredda eller förenkla sökfrågan)"

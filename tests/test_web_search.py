"""Tests for Brave Search web_search tool."""
import os
import pytest
from unittest.mock import patch, MagicMock
import httpx

from hund.tools.web_search import search_web


def test_search_web_missing_key():
    """Om BRAVE_API_KEY saknas, returnera felmeddelande."""
    with patch.dict(os.environ, {}, clear=True):
        res = search_web({"query": "python"})
        assert "[error] BRAVE_API_KEY saknas" in res


def test_search_web_missing_query():
    """Om query saknas, returnera felmeddelande."""
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test_key"}):
        res = search_web({})
        assert "[error] query saknas" in res


def test_search_web_success():
    """Om anropet lyckas, formatera och returnera resultaten."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "Python Website",
                    "url": "https://python.org",
                    "description": "Official Python programming language website.",
                },
                {
                    "title": "PyPI",
                    "url": "https://pypi.org",
                    "description": "Python Package Index.",
                }
            ]
        }
    }
    
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test_key"}):
        with patch("httpx.get", return_value=mock_response) as mock_get:
            res = search_web({"query": "python"})
            mock_get.assert_called_once()
            assert "Python Website" in res
            assert "https://python.org" in res
            assert "Official Python programming language website." in res
            assert "PyPI" in res


def test_search_web_no_results():
    """Om Brave Search returnerar tomt svar, returnera 'inga resultat'."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"web": {"results": []}}
    
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test_key"}):
        with patch("httpx.get", return_value=mock_response) as mock_get:
            res = search_web({"query": "asdfghjkl"})
            assert res == "inga resultat"


def test_search_web_http_error():
    """Vid HTTP-fel, returnera felbeskrivning."""
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden access to API"
    
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test_key"}):
        with patch("httpx.get", side_effect=httpx.HTTPStatusError("Forbidden", request=MagicMock(), response=mock_response)) as mock_get:
            res = search_web({"query": "python"})
            assert "[error] HTTP 403: Forbidden access to API" in res
